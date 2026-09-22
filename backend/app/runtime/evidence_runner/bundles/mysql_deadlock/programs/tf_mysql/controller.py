"""Independent MySQL observer and bounded transaction broker for the fixture."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
import pymysql


def connect(config, *, fixture=False):
    options = {k: config[k] for k in ("host", "port", "user", "password", "database") if k in config}
    options.update(connect_timeout=5, read_timeout=10, write_timeout=10, autocommit=not fixture,
                   charset="utf8mb4")
    return pymysql.connect(**options)


def status(connection):
    with connection.cursor() as cursor:
        cursor.execute("SHOW ENGINE INNODB STATUS")
        row = cursor.fetchone()
        return str(row[2]) if row else ""


def correlated(status_text, table, connection_ids):
    latest = status_text.split("LATEST DETECTED DEADLOCK", 1)
    if len(latest) != 2:
        return False
    block = latest[1].split("TRANSACTIONS", 1)[0]
    found = {int(value) for value in re.findall(r"MySQL thread id (\d+)", block)}
    return table in block and len(found & set(connection_ids)) >= 2


def observe(config, sample):
    started = time.time()
    with connect(config) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION(), @@transaction_isolation")
            version, isolation = cursor.fetchone()
            cursor.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                           (config["database"], config["table"]))
            engine = cursor.fetchone()
        raw = status(connection)
    # Recent status alone is insufficient. It must match the independently
    # bound incident sample's table, time window and participating connections.
    valid_sample = (sample.get("error_code") == 1213 and sample.get("table") == config["table"]
                    and isinstance(sample.get("captured_at"), (int, float))
                    and 0 <= started - sample["captured_at"] <= 3600
                    and isinstance(sample.get("connection_ids"), list)
                    and correlated(raw, config["table"], sample["connection_ids"]))
    return {"connection_ok": True, "version": version, "isolation": isolation,
            "table_engine": engine[0] if engine else None, "window": [started, time.time()],
            "correlated_samples": 1 if valid_sample else 0, "innodb_status": raw,
            "observed_error_code": sample.get("error_code") if valid_sample else None}


def _read_lines(stream, messages):
    try:
        while True:
            line = stream.readline(16_385)
            if not line:
                break
            if len(line) > 16_384:
                messages.put({"protocol_error": "TARGET_MESSAGE_TOO_LARGE"})
                return
            messages.put(json.loads(line), timeout=1)
    except (ValueError, OSError, queue.Full):
        try:
            messages.put({"protocol_error": "TARGET_PROTOCOL_INVALID"}, timeout=1)
        except queue.Full:
            pass
    finally:
        try:
            messages.put(None, timeout=1)
        except queue.Full:
            pass


def invoke(config, table, source, operation, request, barrier=None, delay=0.03):
    report = {"request": request, "locks": [], "acquired": [], "reads": {}, "errors": [], "operations": [],
              "committed": False, "completed": False, "outcome": "unknown", "started_at": time.time()}
    program = Path(__file__).with_name("target.py")
    # No credentials, parent PYTHONPATH, HOME or model tokens in target env.
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "TRACEFORGE_RUN_TOKEN", "TRACEFORGE_SPAWN_TOKEN", "WORKER_BOOT_ID") if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONSAFEPATH="1")
    process = subprocess.Popen([sys.executable, "-I", "-B", str(program), str(source), operation],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", cwd=str(source), env=env)
    messages = queue.Queue(maxsize=256)
    reader = threading.Thread(target=_read_lines, args=(process.stdout, messages), daemon=True)
    reader.start()
    connection = None
    try:
        connection = connect(config, fixture=True)
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout=5")
            cursor.execute("SELECT CONNECTION_ID()")
            report["connection_id"] = cursor.fetchone()[0]
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        begun, finished = False, False
        deadline = time.monotonic() + 20
        for _ in range(64):
            message = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if not isinstance(message, dict) or "operation" not in message:
                raise ValueError("TARGET_PROTOCOL_INCOMPLETE")
            op = message["operation"]
            if op == "done":
                if not finished:
                    raise ValueError("TARGET_TRANSACTION_NOT_SETTLED")
                report.update(completed=True, outcome=message.get("outcome"), target_error=message.get("error"))
                break
            response = {}
            try:
                with connection.cursor() as cursor:
                    if op == "begin" and not begun:
                        if barrier:
                            barrier.wait(timeout=10)
                        connection.begin()
                        begun = True
                    elif op in {"lock", "set_balance"} and begun and not finished:
                        account_id = message.get("account_id")
                        if type(account_id) is not int or account_id not in {1, 2}:
                            raise ValueError("INVALID_ACCOUNT")
                        if op == "lock":
                            report["locks"].append(account_id)
                            cursor.execute(f"SELECT balance FROM `{table}` WHERE id=%s FOR UPDATE", (account_id,))
                            response["value"] = int(cursor.fetchone()[0])
                            report["reads"].setdefault(str(account_id), response["value"])
                            report["acquired"].append(account_id)
                            # Bounded delay after a first lock; no post-lock
                            # barrier that could deadlock the corrected code.
                            if len(report["acquired"]) == 1:
                                time.sleep(delay)
                        else:
                            balance = message.get("balance")
                            if type(balance) is not int or not 0 <= balance <= 1_000_000 or account_id not in report["acquired"]:
                                raise ValueError("INVALID_BALANCE_WRITE")
                            cursor.execute(f"UPDATE `{table}` SET balance=%s WHERE id=%s", (balance, account_id))
                            report["operations"].append({"account_id": account_id, "balance": balance})
                    elif op == "commit" and begun and not finished:
                        connection.commit()
                        report["committed"] = True
                        finished = True
                    elif op == "rollback" and begun and not finished:
                        connection.rollback()
                        finished = True
                    else:
                        raise ValueError("TARGET_OPERATION_NOT_ALLOWED")
            except pymysql.MySQLError as exc:
                code = exc.args[0] if exc.args and type(exc.args[0]) is int else 0
                report["errors"].append(code)
                response = {"error": f"MYSQL_{code}"}
                if code == 1213:
                    report["deadlock_status"] = status(connection)
            process.stdin.write(json.dumps(response) + "\n")
            process.stdin.flush()
        if not report["completed"]:
            raise ValueError("TARGET_REQUEST_INCOMPLETE")
        process.wait(timeout=2)
        report["exit_code"] = process.returncode
    except (OSError, ValueError, queue.Empty, threading.BrokenBarrierError, subprocess.TimeoutExpired, pymysql.MySQLError) as exc:
        report["harness_error"] = type(exc).__name__ + ":" + (str(exc)[:160] if not isinstance(exc, pymysql.MySQLError) else "DATABASE_OPERATION_FAILED")
    finally:
        if connection:
            connection.rollback()
            connection.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        reader.join(timeout=1)
        report["ended_at"] = time.time()
    return report


def batch(config, source, operation, requests, *, concurrent=True, delay=0.03, retain=False):
    if not re.fullmatch(r"tf_playbook_[a-zA-Z0-9_]+", config["database"]):
        raise ValueError("FIXTURE_DATABASE_PREFIX_REQUIRED")
    execution = os.environ.get("TF_EXECUTION_ID", "").replace("-", "")
    table = "tf_" + execution + "_" + uuid.uuid4().hex[:16] if re.fullmatch(r"[a-f0-9]{32}", execution) else "tf_accounts_" + uuid.uuid4().hex
    with connect(config) as admin:
        with admin.cursor() as cursor:
            cursor.execute(f"CREATE TABLE `{table}` (id INT PRIMARY KEY, balance BIGINT NOT NULL) ENGINE=InnoDB")
            cursor.executemany(f"INSERT INTO `{table}` VALUES (%s,%s)", [(1, 1000), (2, 1000)])
        try:
            barrier = threading.Barrier(len(requests)) if concurrent and len(requests) > 1 else None
            with ThreadPoolExecutor(max_workers=len(requests) if concurrent else 1) as pool:
                jobs = [pool.submit(invoke, config, table, source, operation, request, barrier, delay) for request in requests]
                reports = [job.result() for job in jobs]
            with admin.cursor() as cursor:
                cursor.execute(f"SELECT id,balance FROM `{table}` ORDER BY id")
                balances = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
            ids = [r["connection_id"] for r in reports if "connection_id" in r]
            has_cycle = any(correlated(r.get("deadlock_status", ""), table, ids) for r in reports)
            return {"table": table, "requests": reports, "balances": balances,
                    "correlated_lock_cycle": has_cycle, "parallel_clients": len(requests) if concurrent else 1,
                    "requested_count": len(requests), "source": str(source)}
        finally:
            # Table is freshly generated here, never supplied by the model.
            if not retain:
                with admin.cursor() as cursor:
                    cursor.execute(f"DROP TABLE `{table}`")
