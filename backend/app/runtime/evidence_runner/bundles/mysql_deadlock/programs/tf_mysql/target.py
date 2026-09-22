"""Transaction-port adapter for a real application entry, in a child process.

Only domain operations cross the pipe. Database credentials and the oracle stay
in the controller. stdout is reserved for the protocol; app prints go to stderr.
"""
import contextlib
import importlib.util
import importlib
import json
from pathlib import Path
import sys


class Transaction:
    def __init__(self, output):
        self.output = output

    def call(self, operation, **arguments):
        self.output.write(json.dumps({"operation": operation, **arguments}) + "\n")
        self.output.flush()
        response = json.loads(sys.stdin.readline())
        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("value")

    def lock_account(self, account_id):
        return self.call("lock", account_id=account_id)

    def set_balance(self, account_id, balance):
        return self.call("set_balance", account_id=account_id, balance=balance)


def main():
    source, operation = Path(sys.argv[1]).resolve(strict=True), sys.argv[2]
    module_name, symbol = operation.split(":")
    module_path = (source / (module_name.replace(".", "/") + ".py")).resolve(strict=True)
    if not module_path.is_relative_to(source):
        raise ValueError("TARGET_PATH_ESCAPE")
    request = json.loads(sys.stdin.readline())
    output = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        # Use a file-spec import, so the target cannot shadow trusted controller
        # packages or the Python stdlib through the controller's import path.
        sys.path.insert(0, str(source))
        module = importlib.import_module(module_name)
        function = getattr(module, symbol)
        tx = Transaction(output)
        tx.call("begin")
        try:
            function(tx, request["source_id"], request["target_id"], request["amount"])
            tx.call("commit")
            output.write(json.dumps({"operation": "done", "outcome": "success"}) + "\n")
        except Exception as exc:
            tx.call("rollback")
            output.write(json.dumps({"operation": "done", "outcome": "error", "error": str(exc)[:200]}) + "\n")
        output.flush()


if __name__ == "__main__":
    main()
