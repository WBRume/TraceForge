"""Launch the real host process without a platform .env or database."""
import base64
import hashlib
import json
import os
import platform
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest


@pytest.mark.parametrize("packaged", [False, True])
def test_standalone_host_and_restart(tmp_path, packaged):
    backend = Path(__file__).parents[2]
    system = {"win32": "windows", "darwin": "darwin"}.get(sys.platform, "linux")
    architecture = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    executable = backend.parent / "resource-host/dist" / f"{system}-{architecture}" / (
        "traceforge-resource-host.exe" if os.name == "nt" else "traceforge-resource-host")
    if os.environ.get("TRACEFORGE_RESOURCE_HOST_TEST_BINARY"):
        executable = Path(os.environ["TRACEFORGE_RESOURCE_HOST_TEST_BINARY"])
    if packaged and not executable.is_file():
        pytest.skip("Build Resource Host to verify the distribution")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = tmp_path / "host.json"
    config.write_text(json.dumps(dict(state_root=str(tmp_path / "state"), allowed_roots=[str(workspace)],
                                    token="x" * 32, port=port)))
    bun = backend.parent / "resource-host/node_modules/bun/bin" / ("bun.exe" if os.name == "nt" else "bun")
    if not packaged and not bun.is_file():
        pytest.skip("Install resource-host development dependencies")
    args = [str(executable)] if packaged else [str(bun), str(backend.parent / "resource-host/src/main.ts")]
    env = {key: value for key, value in os.environ.items() if not key.startswith(("DB_", "JWT_", "TRACEFORGE_RESOURCE_HOST"))}
    if packaged:
        # The executable must work without Node, Bun or Python discoverable on PATH.
        env["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else "/usr/bin:/bin"
    with (tmp_path / "host.log").open("w+") as log, httpx.Client(
        base_url=f"http://127.0.0.1:{port}", headers={"Authorization": "Bearer " + "x" * 32}, trust_env=False, timeout=60,
    ) as client:
        def launch():
            return subprocess.Popen([*args, "--config", str(config)], cwd=tmp_path, env=env, stdout=log, stderr=log,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        def ready(process):
            for _ in range(120):
                if process.poll() is not None:
                    log.seek(0)
                    pytest.fail(log.read())
                try:
                    response = client.get("/v1/identity")
                    response.raise_for_status()
                    assert response.json()["implementation"] == "typescript"
                    return response.json()["host_id"]
                except httpx.ConnectError:
                    time.sleep(.25)
            pytest.fail("Host startup timeout")
        def operation(kind, payload, key):
            body = dict(operation_id=key, task_id="smoke", resource_id="resource", kind=kind, payload=payload)
            body["payload_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            response = client.post("/v1/operations", json=body)
            assert response.status_code == 200, response.text
            return response.json()["result"]
        process = launch()
        try:
            identity = ready(process)
            payload = dict(workspace_root=str(workspace), repositories=[])
            first = operation("provision", payload, "provision")
            data = b"hello standalone"
            operation("materialize", dict(files=[dict(path="note.txt", content=base64.b64encode(data).decode(),
                                                      sha256=hashlib.sha256(data).hexdigest())]), "file")
            assert (workspace / "tasks/smoke/note.txt").read_bytes() == data
            checkpoint = operation("snapshot", dict(action="create", provider="opencode"), "snapshot")
            assert operation("snapshot", dict(action="exists", checkpoint_root=checkpoint["root"]), "exists")["exists"]
            operation("documents", dict(action="list"), "docs")
            operation("skills", dict(action="manifest"), "skills")
            process.terminate()
            process.wait(timeout=10)
            process = launch()
            assert ready(process) == identity
            assert operation("provision", payload, "provision") == first
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
