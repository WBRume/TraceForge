"""Only registered entrypoints call this trusted controller with sealed inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from .controller import batch, observe
from .oracle import facts, target_failed


def run(phase):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-manifest")
    parser.add_argument("--manifest")
    parser.add_argument("--snapshot")
    parser.add_argument("--case")
    arguments = parser.parse_args()
    manifest = json.loads(Path(os.environ["TF_MYSQL_MANIFEST"]).read_text(encoding="utf-8"))
    if manifest["phase"] != phase:
        raise ValueError("MANIFEST_PHASE_MISMATCH")
    for candidate in (arguments.manifest, arguments.input_manifest):
        if candidate and Path(candidate).resolve() != Path(os.environ["TF_MYSQL_MANIFEST"]).resolve():
            raise ValueError("MANIFEST_BINDING_MISMATCH")
    if phase == "REPRODUCE" and (arguments.case != "transfer_pair" or Path(arguments.snapshot).resolve() != Path(manifest["source"]).resolve()):
        raise ValueError("TARGET_BINDING_MISMATCH")
    credentials = json.loads(os.environ.pop("TF_MYSQL_CONNECTIONS"))
    count = manifest["parallel_clients"]
    requests = [{"source_id": 1 if i % 2 == 0 else 2, "target_id": 2 if i % 2 == 0 else 1, "amount": 1} for i in range(count)]
    config, source, operation = credentials["fixture"], manifest["source"], manifest["target_operation"]
    started = time.time()
    report = {"phase": phase, "manifest_digest": hashlib.sha256(Path(os.environ["TF_MYSQL_MANIFEST"]).read_bytes()).hexdigest(),
              "parallel_clients": count, "observed_error_code": manifest["observed_error_code"]}
    if phase == "PROBE":
        report["probe"] = observe(credentials["observation"], manifest["observed_sample"])
    elif phase == "HYPOTHESIZE":
        report["hypotheses"] = manifest["hypotheses"]
        report["branches"] = {}
        for hypothesis in manifest["hypotheses"]:
            # Sequential priority queue, with fresh independent fixtures per
            # branch. One hypothesis cannot mutate another's experimental state.
            report["branches"][hypothesis["id"]] = {
                "concurrent": batch(config, source, operation, requests),
                "sequential": batch(config, source, operation, requests, concurrent=False, delay=0)}
    elif phase == "REPRODUCE":
        report["baseline"] = batch(config, source, operation, requests)
    else:
        report["baseline"] = batch(config, source, operation, requests)
        report["patch"] = batch(config, manifest["patch"], operation, requests)
        scenarios = {"same_account": (1, 1, 1), "insufficient_funds": (1, 2, 1001), "invalid_amount": (1, 2, -1), "valid_transfer": (1, 2, 7)}
        report["regressions"] = {name: batch(config, manifest["patch"], operation,
            [{"source_id": args[0], "target_id": args[1], "amount": args[2]}], concurrent=False, delay=0) for name, args in scenarios.items()}
        report.update(baseline_oracle_digest=manifest["oracle_digest"], patch_oracle_digest=manifest["oracle_digest"],
                      baseline_environment_digest=manifest["environment_digest"], patch_environment_digest=manifest["environment_digest"])
    report["duration_seconds"] = time.time() - started
    # Only the controller writes this stream. Application stdout has its own
    # bounded protocol pipe and can never emit a collector report directly.
    print(json.dumps(report, ensure_ascii=False))
    if phase == "REPRODUCE":
        return 1 if target_failed(report["baseline"]) else 0
    # Gates evaluate the physical facts, not the command's success alone.
    return 0


def entry(phase):
    try:
        code = run(phase)
    except Exception as exc:
        # Credential-bearing database exceptions are deliberately not printed.
        print(json.dumps({"harness_error": type(exc).__name__, "phase": phase}), file=sys.stderr)
        code = 2
    raise SystemExit(code)
