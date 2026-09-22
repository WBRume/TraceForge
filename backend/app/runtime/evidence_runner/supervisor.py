"""Journal before spawn; unknown executions are reconciled, never re-executed.

Local evidence files alone are not an isolation boundary. Only a certified bundle
probe may authorize execution, and collectors run outside the tested process.
"""
import asyncio
from dataclasses import asdict
import json
import hashlib
import os
from pathlib import Path
import time
import uuid
from app.agents.supervision.supervisor import ProcessSupervisor
from app.domains.diagnosis_playbook.contracts import PlaybookError, digest


class EvidenceRunner:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.identity = f"{os.getpid()}/{uuid.uuid4()}"
        self.supervisor = ProcessSupervisor()

    def directory(self, execution_id):
        try:
            uuid.UUID(execution_id)
        except (ValueError, TypeError) as exc:
            raise PlaybookError("INVALID_EXECUTION_ID") from exc
        directory = self.root / execution_id
        if directory.resolve().parent != self.root:
            raise PlaybookError("EVIDENCE_PATH_ESCAPE")
        return directory

    def inspect(self, envelope):
        directory = self.directory(envelope.execution_id)
        if not directory.exists():
            return None
        manifest = directory / "receipt.json"
        if not manifest.exists():
            raise PlaybookError("EXECUTION_UNKNOWN", status=409)
        receipt = json.loads(manifest.read_text(encoding="utf-8"))
        if receipt["envelope_digest"] != digest(asdict(envelope)):
            raise PlaybookError("EXECUTION_ID_CONFLICT", status=409)
        if receipt.get("receipt_digest") != digest({k: v for k, v in receipt.items() if k != "receipt_digest"}):
            raise PlaybookError("RECEIPT_DIGEST_MISMATCH", status=409)
        for artifact in receipt.get("artifacts", []):
            path = directory / artifact["name"]
            if not path.resolve().is_relative_to(directory.resolve()) or not path.is_file() or self._file_digest(path) != artifact["digest"]:
                raise PlaybookError("SEALED_ARTIFACT_CHANGED", status=409)
        return receipt

    @staticmethod
    def _file_digest(path):
        with path.open("rb") as stream:
            return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()

    @staticmethod
    def _seal(path, data):
        # Exclusive immutable keys and fsync before acknowledging the receipt.
        with path.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())

    async def reconcile(self, envelope, bundle=None):
        """Expired owner recovery: stop the old identity, seal interruption only.

        A missing process journal is deliberately UNKNOWN. No fresh execution
        or target-pass claim can be inferred from an empty directory.
        """
        from datetime import datetime
        directory = self.directory(envelope.execution_id)
        identity_path = directory / "process.json"
        if not identity_path.is_file():
            raise PlaybookError("EXECUTION_UNKNOWN", status=409)
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        intent = json.loads((directory / "intent.json").read_text(encoding="utf-8"))
        if digest(intent) != digest(asdict(envelope)):
            raise PlaybookError("EXECUTION_ID_CONFLICT", status=409)
        stopped = await self.supervisor.stop_persisted(identity["pid"], datetime.fromisoformat(identity["started_at"]),
            "playbook_owner_lost", process_group_id=identity.get("process_group_id"), run_token=envelope.execution_id)
        if stopped.confirmed_dead is not True:
            raise PlaybookError("TERMINATION_UNKNOWN", status=409)
        # A concurrent owner may have sealed the authoritative result meanwhile.
        if (directory / "receipt.json").exists():
            return self.inspect(envelope)
        cleanup_confirmed = True
        if bundle and bundle.cleanup:
            try:
                await asyncio.to_thread(bundle.cleanup, envelope)
            except Exception:
                cleanup_confirmed = False
        artifacts = []
        for name in ("stdout", "stderr"):
            path = directory / name
            if path.is_file():
                artifacts.append({"name": name, "digest": self._file_digest(path), "size": path.stat().st_size})
        receipt = {**asdict(envelope), "envelope_digest": digest(asdict(envelope)),
            "runner_identity": self.identity, "exit_code": -1, "termination": "CONFIRMED",
            "timed_out": False, "cancelled": True, "facts": {"runner.interrupted": True},
            "artifacts": artifacts, "sealed_at": time.time(), "cleanup_confirmed": cleanup_confirmed}
        receipt["receipt_digest"] = digest(receipt)
        try:
            self._seal(directory / "receipt.json", receipt)
        except FileExistsError:
            return self.inspect(envelope)
        return receipt

    async def execute(self, envelope, bundle, *, emit, cancelled):
        existing = self.inspect(envelope)
        if existing is not None:
            return existing
        directory = self.directory(envelope.execution_id)
        try:
            directory.mkdir()
        except FileExistsError as exc:
            raise PlaybookError("EXECUTION_UNKNOWN", status=409) from exc
        self._seal(directory / "intent.json", asdict(envelope))
        process = None
        managed = None
        timed_out, cancel_requested = False, False
        started = time.monotonic()
        try:
            if str(Path(envelope.cwd).resolve(strict=True)) != envelope.cwd:
                raise PlaybookError("EXECUTION_PATH_CHANGED", status=409)
            child_environment = await asyncio.to_thread(bundle.child_environment, envelope) if bundle.child_environment else {}
        except Exception as exc:
            # No process creation has been attempted. This is an authoritative
            # preparation failure, unlike a lost post-spawn attach callback.
            receipt = {**asdict(envelope), "envelope_digest": digest(asdict(envelope)),
                "runner_identity": self.identity, "exit_code": -1, "termination": "CONFIRMED",
                "timed_out": False, "cancelled": False, "process_started": False,
                "facts": {"runner.preparation_error": type(exc).__name__}, "artifacts": [],
                "sealed_at": time.time(), "cleanup_confirmed": True}
            receipt["receipt_digest"] = digest(receipt)
            self._seal(directory / "receipt.json", receipt)
            return receipt
        try:
            # Bundle code/root is isolated from source and cwd, and the executable
            # is resolved by server configuration, never the task's PATH.
            async def attached(identity):
                self._seal(directory / "process.json", {"pid": identity.pid, "started_at": identity.started_at.isoformat(),
                                                        "process_group_id": identity.process_group_id, "containment_id": identity.containment_id})
                return True
            managed = await self.supervisor.spawn(
                [bundle.executable, *envelope.argv[1:]], cwd=envelope.cwd,
                run_token=envelope.execution_id, worker_boot_id=self.identity,
                on_process_started=attached,
                env={"PATH": str(Path(bundle.executable).parent), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                     "PYTHONPATH": bundle.root, "PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1",
                     "PYTHONDONTWRITEBYTECODE": "1", **child_environment},
            )
            process = managed.process
            if process.stdin:
                process.stdin.close()

            async def pump(stream, name):
                with (directory / name).open("xb") as output:
                    while chunk := await stream.read(8192):
                        output.write(chunk)
                        await emit("runner.tail", {"stream": name, "content": chunk.decode("utf-8", errors="replace")})
                    output.flush()
                    os.fsync(output.fileno())

            pumps = [asyncio.create_task(pump(process.stdout, "stdout")), asyncio.create_task(pump(process.stderr, "stderr"))]
            try:
                while process.returncode is None:
                    elapsed = time.monotonic() - started
                    cancel_requested = await cancelled()
                    timed_out = elapsed >= envelope.timeout_seconds
                    if cancel_requested or timed_out:
                        break
                    await emit("runner.heartbeat", {"elapsed_seconds": round(elapsed), "stage": "RUNNING_VERIFICATION"})
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except TimeoutError:
                        pass
            finally:
                stopped = await managed.close(reason="playbook_execution_settled")
                await asyncio.wait_for(asyncio.gather(*pumps), timeout=10)
                if not stopped.confirmed_dead:
                    raise PlaybookError("TERMINATION_UNKNOWN", status=409)
                self.supervisor.forget(managed)
            try:
                facts, artifacts = await asyncio.to_thread(bundle.collect, envelope, directory)
            except Exception as exc:
                # The process is confirmed dead. Preserve an ERROR receipt so
                # an invalid/truncated report cannot strand recovery forever.
                facts, artifacts = {"runner.collector_error": type(exc).__name__}, []
            cleanup_confirmed = True
            if bundle.cleanup:
                try:
                    await asyncio.to_thread(bundle.cleanup, envelope)
                except Exception as exc:
                    cleanup_confirmed = False
                    facts["runner.cleanup_error"] = type(exc).__name__
            sealed_artifacts = []
            from app.domains.diagnosis_playbook.compiler import safe_relative
            for name in dict.fromkeys(["stdout", "stderr", *artifacts]):
                path = directory / name
                if not safe_relative(name) or not path.resolve(strict=True).is_relative_to(directory.resolve()):
                    raise PlaybookError("ARTIFACT_PATH_ESCAPE")
                sealed_artifacts.append({"name": name, "digest": self._file_digest(path), "size": path.stat().st_size})
            receipt = {**asdict(envelope), "envelope_digest": digest(asdict(envelope)),
                       "runner_identity": self.identity, "exit_code": process.returncode,
                       "termination": "CONFIRMED", "timed_out": timed_out, "cancelled": cancel_requested,
                       "facts": facts, "artifacts": sealed_artifacts, "sealed_at": time.time(),
                       "duration_seconds": round(time.monotonic() - started, 3), "cleanup_confirmed": cleanup_confirmed}
            receipt["receipt_digest"] = digest(receipt)
            self._seal(directory / "receipt.json", receipt)
            return receipt
        except BaseException:
            # Keep intent/process journal to make retry return UNKNOWN. Never delete it.
            if managed is not None:
                await managed.close(reason="playbook_execution_error")
                self.supervisor.forget(managed)
            raise
