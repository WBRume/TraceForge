"""Admin-only feature management. Never echo request bodies or decrypted credentials."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.logging import audit_log
from app.core.offload import run_db_txn
from app.dependencies import require_admin
from app.domains.system_config.services import capability_probe as probes
from app.domains.system_config.services import feature_config_service as configs
from app.domains.system_config.services.system_config_service import SystemConfigError

router = APIRouter(prefix="/system-configs", tags=["Feature Configs"], dependencies=[Depends(require_admin)])


async def transaction(fn):
    try:
        return await run_db_txn(fn)
    except SystemConfigError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


async def parse_patch(request):
    try:
        raw = await request.body()
        if len(raw) > 65536:
            raise ValueError
        body = json.loads(raw)
        if not isinstance(body, dict) or set(body) - {"values", "revision", "reset"}:
            raise ValueError
        revision = body.get("revision")
        reset = body.get("reset", False)
        values = body.get("values", {})
        if type(revision) is not int or not 0 <= revision < 2_000_000_000:
            raise ValueError
        if type(reset) is not bool or not isinstance(values, dict) or reset and values:
            raise ValueError
        return values, revision, reset
    except (ValueError, TypeError, UnicodeDecodeError):
        raise HTTPException(422, "配置请求格式无效") from None


def no_cache(response):
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"


@router.get("/features")
async def list_features(response: Response):
    no_cache(response)
    return await transaction(lambda db: {"items": [configs.public(db, feature) for feature in configs.CATALOG]})


@router.get("/features/{feature}")
async def get_feature(feature: str, response: Response):
    no_cache(response)
    return await transaction(lambda db: configs.public(db, feature))


@router.put("/features/{feature}")
async def save_feature(feature: str, request: Request, response: Response, user=Depends(require_admin)):
    values, revision, reset = await parse_patch(request)
    saved = await transaction(lambda db: configs.save(db, feature, values, revision, user.id, reset))
    audit_log(
        action="update_feature_config",
        outcome="success",
        resource_type="feature_config",
        resource_id=feature,
        user_id=user.id,
        changed_fields=list(values),
        reset=reset,
        revision=saved["revision"],
    )
    runtime = getattr(request.app.state, "feature_runtime", None)
    applied = False
    if runtime:
        try:
            await runtime.refresh()
            applied = True
        except Exception:
            # Commit succeeded; background reconciliation retries without losing the config.
            applied = False
    else:
        from app.core.feature_settings import feature_settings

        overrides = await transaction(configs.snapshot)
        feature_settings.replace(configs.environment_snapshot(overrides))
        applied = True
    no_cache(response)
    return {
        "config": saved,
        "applied": applied,
        "message": "配置已保存并应用；能力就绪状态由探针确认" if applied else "配置已保存，后台正在重试应用",
    }


@router.post("/features/{feature}/test")
async def test_feature(feature: str, request: Request, response: Response, user=Depends(require_admin)):
    values, revision, reset = await parse_patch(request)
    effective, _ = await transaction(lambda db: configs.draft(db, feature, values, revision, reset))
    status = await probes.probe(feature, effective, request.app, draft=True)
    audit_log(
        action="test_feature_config",
        outcome=status["status"],
        resource_type="feature_config",
        resource_id=feature,
        user_id=user.id,
    )
    no_cache(response)
    return status


@router.get("/capabilities")
async def capabilities(request: Request, response: Response):
    def read(db):
        results = {}
        errors = {}
        for feature in configs.CATALOG:
            try:
                results[feature] = configs.read(db, feature)[0]
            except SystemConfigError:
                errors[feature] = probes.result(
                    feature, "DEGRADED", "unavailable", "业务配置无法解密或校验", "检查部署主密钥或恢复环境配置"
                )
        return results, errors

    values, errors = await transaction(read)
    statuses = await asyncio.gather(*(probes.probe(feature, value, request.app) for feature, value in values.items()))
    by_feature = {item["feature"]: item for item in statuses} | errors
    runtime = getattr(request.app.state, "feature_runtime", None)
    for feature, message in runtime.errors.items() if runtime else []:
        if feature == "search_runtime":
            feature = "search"
        if feature in by_feature:
            by_feature[feature].update(status="DEGRADED", explanation=message)
    no_cache(response)
    return {"items": [by_feature[feature] for feature in configs.CATALOG]}
