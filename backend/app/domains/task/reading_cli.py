"""阅读进度数据升级 CLI（可恢复命令）。

用法：
    python -m app.domains.task.reading_cli backfill --batch-size 200
    python -m app.domains.task.reading_cli verify --task-id <uuid>
    python -m app.domains.task.reading_cli status
    python -m app.domains.task.reading_cli cleanup-receipts --batch-size 500
"""
from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys

# 全量模型注册（与生产 app 全量加载等价）：User 等跨域 relationship
# 依赖全部 mapper 注册完成后才能解析，缺步会 InvalidRequestError。
from app import domains as _domains

for _name in [n for _, n, _ in pkgutil.iter_modules(_domains.__path__)]:
    try:
        _models_pkg = importlib.import_module(f"app.domains.{_name}.models")
    except ModuleNotFoundError:
        continue
    if hasattr(_models_pkg, "__path__"):
        for _, _mod, _ in pkgutil.walk_packages(_models_pkg.__path__, prefix=f"app.domains.{_name}.models."):
            importlib.import_module(_mod)

from app.database import SessionLocal
from app.domains.task.models.task import SddTask
from app.domains.task.services import reading_backfill_service


def _open_session():
    """每批独立 Session（短事务）；不跨批持有连接。"""
    return SessionLocal()


def cmd_backfill(args: argparse.Namespace) -> int:
    batch_size = max(1, int(args.batch_size or 200))
    overall_ok = True
    while True:
        progressed = False
        session = _open_session()
        try:
            task_ids = reading_backfill_service.iter_task_ids(session)
            ready_or_skipped = 0
            for task_id in task_ids:
                task_row = session.query(SddTask.reading_ready).filter_by(id=task_id).first()
                if task_row is not None and task_row[0]:
                    ready_or_skipped += 1
                    continue
                result = reading_backfill_service.backfill_task_batch(
                    session, task_id=task_id, batch_size=batch_size
                )
                session.commit()
                if result.get("blocked"):
                    print(
                        json.dumps(
                            {"level": "warn", **result},
                            ensure_ascii=False,
                        )
                    )
                    continue
                if result.get("created") or result.get("batch"):
                    print(json.dumps(result, ensure_ascii=False))
                    progressed = True
                if result.get("done"):
                    verify = reading_backfill_service.verify_task(session, task_id=task_id)
                    session.commit()
                    print(json.dumps(verify, ensure_ascii=False))
                    if not verify.get("ok"):
                        overall_ok = False
                ready_or_skipped += 1
            done = len(task_ids) == ready_or_skipped
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        if done or not progressed:
            break
    print(json.dumps({"phase": "backfill", "all_ok": overall_ok}, ensure_ascii=False))
    return 0 if overall_ok else 1


def cmd_verify(args: argparse.Namespace) -> int:
    session = _open_session()
    try:
        result = reading_backfill_service.verify_task(session, task_id=str(args.task_id))
        session.commit()
    finally:
        session.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_status(_args: argparse.Namespace) -> int:
    session = _open_session()
    try:
        result = reading_backfill_service.backfill_status(session)
    finally:
        session.close()
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


def cmd_cleanup_receipts(args: argparse.Namespace) -> int:
    batch_size = max(1, int(args.batch_size or 500))
    total = {"removed_stale_epoch": 0, "removed_covered": 0}
    while True:
        session = _open_session()
        try:
            result = reading_backfill_service.cleanup_receipts(session, batch_size=batch_size)
        finally:
            session.close()
        for key in total:
            total[key] += int(result.get(key) or 0)
        if int(result.get("removed_stale_epoch") or 0) + int(result.get("removed_covered") or 0) < batch_size:
            break
    print(json.dumps(total, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.domains.task.reading_cli")
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser("backfill", help="按任务有界回填历史阅读条目（可恢复）")
    backfill.add_argument("--batch-size", type=int, default=200)
    backfill.set_defaults(func=cmd_backfill)

    verify = sub.add_parser("verify", help="核对任务阅读条目覆盖与指纹，通过则置 ready")
    verify.add_argument("--task-id", required=True)
    verify.set_defaults(func=cmd_verify)

    status = sub.add_parser("status", help="查看各任务回填状态")
    status.set_defaults(func=cmd_status)

    cleanup = sub.add_parser("cleanup-receipts", help="清理旧 epoch / 被前缀覆盖回执")
    cleanup.add_argument("--batch-size", type=int, default=500)
    cleanup.set_defaults(func=cmd_cleanup_receipts)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
