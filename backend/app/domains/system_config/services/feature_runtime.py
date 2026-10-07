"""Load DB snapshots and reconcile app-owned resources, with bounded cross-process refresh."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.feature_settings import feature_settings
from app.core.offload import run_db_txn
from app.domains.system_config.services import feature_config_service as configs
from app.domains.system_config.services.system_config_service import SystemConfigError

logger = logging.getLogger(__name__)


def load_runtime(db):
    from app.domains.system_config.models.feature_config import FeatureConfig

    overrides, errors = {}, {}
    disabled = {
        "speech": {"mode": "off"},
        "search": {"enabled": False},
        "diagnosis": {"worker_enabled": False},
        "oauth": {"enabled": False},
        "agent": {"backend": "unavailable"},
    }
    for row in db.query(FeatureConfig).all():
        if row.feature not in disabled:
            continue
        try:
            overrides[row.feature] = configs.decrypt(row)
        except SystemConfigError:
            overrides[row.feature] = disabled[row.feature]
            errors[row.feature] = "配置解密失败，请检查部署主密钥或恢复环境配置"
    return overrides, errors


class FeatureRuntime:
    def __init__(self, app):
        self.app = app
        self.lock = asyncio.Lock()
        self.task = None
        self.playbook_task = None
        self.playbook_worker = None
        self.applied = {}
        self.errors = {}
        self.search_target = None
        self.search_pending = False
        self.search_task = None

    async def initialize(self):
        try:
            overrides, self.errors = await run_db_txn(load_runtime)
            from app.config import settings as environment

            from .search_configuration import bind_existing_targets

            await run_db_txn(lambda db: bind_existing_targets(db, environment.SEARCH_ES_URL))
            feature_settings.replace(configs.environment_snapshot(overrides))
        except SQLAlchemyError:
            # Old ENV-only installations may not have run this additive migration.
            feature_settings.replace({})
            logger.warning("Runtime feature store unavailable; using startup environment")
        await self._set_diagnosis(feature_settings.DIAGNOSIS_PLAYBOOK_WORKER_ENABLED)

    async def refresh(self):
        async with self.lock:
            overrides, errors = await run_db_txn(load_runtime)
            effective = {feature: configs.effective(feature, overrides.get(feature, {})) for feature in configs.CATALOG}
            if "search" not in errors:
                effective["search"] = await run_db_txn(lambda db: configs.read(db, "search")[0])
            search_changed = effective["search"] != self.applied.get("search")
            diagnosis_changed = effective["diagnosis"] != self.applied.get("diagnosis")
            if search_changed and self.applied:
                from .search_configuration import bind_existing_targets

                await run_db_txn(lambda db: bind_existing_targets(db, self.applied["search"]["es_url"]))
            published = configs.environment_snapshot(overrides)
            # Legacy vector metadata is a DB default, independent of whether the
            # new feature override document has been created yet.
            published["SEARCH_EMBEDDING_ENDPOINT"] = effective["search"]["embedding_endpoint"]
            published["SEARCH_EMBEDDING_MODEL"] = effective["search"]["embedding_model"]
            published["SEARCH_EMBEDDING_API_KEY"] = effective["search"]["embedding_api_key"]
            feature_settings.replace(published)
            self.errors = errors | {key: value for key, value in self.errors.items() if key == "search_runtime"}
            if search_changed:
                from app.domains.search import router as search

                if self.search_task:
                    self.search_task.cancel()
                    await asyncio.gather(self.search_task, return_exceptions=True)
                    self.search_task = None
                self.errors.pop("search_runtime", None)
                if self.applied:
                    await self.app.state.search_runtime.stop(grace_seconds=5)
                    await search.replace_client(self.app)
                self.app.state.search_runtime.start()
                self.search_target = None
                # Existing ENV-only search/index administration remains authoritative.
                self.search_pending = "search" in overrides and effective["search"]["enabled"]
            if diagnosis_changed:
                await self._set_diagnosis(effective["diagnosis"]["worker_enabled"])
            self.applied = effective

    async def _set_diagnosis(self, enabled):
        if enabled and self.playbook_task is not None and not self.playbook_task.done():
            return
        if self.playbook_task is not None:
            self.playbook_task.cancel()
            await asyncio.gather(self.playbook_task, return_exceptions=True)
            self.playbook_task = None
            self.playbook_worker = None
        if enabled:
            from app.domains.diagnosis_playbook.worker import PlaybookWorker

            self.playbook_worker = PlaybookWorker(feature_settings.DIAGNOSIS_PLAYBOOK_EVIDENCE_ROOT)
            self.playbook_task = asyncio.create_task(self.playbook_worker.run(), name="diagnosis-worker")

    def start(self):
        self.task = asyncio.create_task(self._watch(), name="feature-config-refresh")

    async def _watch(self):
        while True:
            try:
                await self.refresh()
                if self.search_pending and (self.search_task is None or self.search_task.done()):
                    self.search_task = asyncio.create_task(self._maintain_search(), name="dynamic-search-index")
                if self.applied.get("diagnosis", {}).get("worker_enabled") and (
                    self.playbook_task is None or self.playbook_task.done()
                ):
                    await self._set_diagnosis(True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Feature reconciliation retry after %s", type(exc).__name__)
            await asyncio.sleep(2)

    async def _maintain_search(self):
        from .search_configuration import activate_when_ready, prepare_search

        values = dict(self.applied["search"])
        while self.applied.get("search") == values:
            try:
                if self.search_pending:
                    self.search_target = await prepare_search(self.app, values)
                    self.search_pending = False
                if self.search_target:
                    await activate_when_ready(self.app, self.search_target)
                self.errors.pop("search_runtime", None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors["search_runtime"] = "运行资源尚未就绪；请检查连接与索引构建状态"
                logger.warning("Dynamic search setup retry after %s", type(exc).__name__)
            await asyncio.sleep(5)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.search_task:
            self.search_task.cancel()
            await asyncio.gather(self.search_task, return_exceptions=True)
        await self._set_diagnosis(False)
