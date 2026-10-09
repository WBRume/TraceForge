"""Bounded probes. Only fixed diagnostics and non-sensitive facts leave this module."""

import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.core.feature_settings import feature_settings
from app.core.offload import run_db_txn
from app.core.redis_client import get_redis_client
from app.domains.system_config.services.feature_catalog import CATALOG


def result(feature, status, mode, explanation, guidance="", **facts):
    return {
        "feature": feature,
        "title": CATALOG[feature][0],
        "status": status,
        "mode": mode,
        "explanation": explanation,
        "guidance": guidance,
        "facts": facts,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def probe_speech(values, app, draft):
    mode = values["mode"]
    if mode == "off":
        return result("speech", "DISABLED", mode, "语音输入已停用", "配置 API 凭据后选择 API 流式模式")
    if mode == "offline":
        return result(
            "speech",
            "DEGRADED",
            mode,
            "离线识别由客户端提供，浏览器不支持",
            "使用包含离线模型的客户端；客户端会独立检查模型资源",
            client_assets_required=True,
        )
    if not values["api_key"]:
        return result("speech", "NOT_CONFIGURED", mode, "语音服务未生效：识别凭据缺失", "填写所选供应商的 API Key")
    from app.domains.ai.routers.speech import _RATE_SCRIPT
    from app.domains.ai.speech.registry import get_provider

    provider, transport = get_provider(values)
    if not provider.configured(values):
        return result("speech", "NOT_CONFIGURED", mode, "语音插件配置不完整", "填写插件要求的凭据和服务地址")

    try:
        redis = await get_redis_client()
        await redis.eval(_RATE_SCRIPT, 1, "traceforge:speech:probe:" + str(time.time_ns()))
    except Exception:
        return result(
            "speech",
            "DEGRADED",
            mode,
            "共享限流组件不可用，语音凭据分发已受限",
            "检查基础 Redis 连接与 Lua 执行权限",
            rate_limiter=False,
        )
    async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
        checked = await provider.probe(client, values, draft=draft)
    return result(
        "speech",
        "READY" if checked.verified else "DEGRADED",
        mode,
        checked.explanation,
        checked.guidance,
        rate_limiter=True,
        credentials_verified=checked.verified,
        transport=transport,
        provider=values.get("provider", "bailian"),
    )


def make_search_client(values):
    from elasticsearch import AsyncElasticsearch

    return AsyncElasticsearch(
        values["es_url"],
        basic_auth=(values["es_username"], values["es_password"]),
        ca_certs=feature_settings.SEARCH_ES_CA_CERTS or None,
        request_timeout=3,
        max_retries=0,
    )


async def search_worker_health(values, app):
    from app.domains.search.worker import heartbeat_binding, worker_heartbeats

    local = values["backend"] == "sqlite" or values["backend"] == "auto" and not values["es_url"]
    kinds = ("search",) if local else ("search", "embedding")
    workers = getattr(app.state, "search_runtime", None)
    if values["workers_enabled"]:
        return bool(
            workers
            and workers.tasks
            and any(not task.done() for task in workers.tasks)
            and all(time.monotonic() - worker_heartbeats.get(kind, 0) < 30 for kind in kinds)
        )
    try:
        redis = await get_redis_client()
        expected = heartbeat_binding(values["es_url"], values["backend"])
        received = [await redis.get("traceforge:feature:search-worker:" + kind) for kind in kinds]
        return all((value.decode() if isinstance(value, bytes) else value) == expected for value in received)
    except Exception:
        return False


async def probe_search(values, app, draft):
    from app.domains.search import sqlite_index
    from app.domains.search.embedding import embed, encrypt_key
    from app.domains.search.service import configuration

    if not values["enabled"]:
        return result("search", "DISABLED", "off", "全局搜索已停用")
    local_ready = await asyncio.to_thread(sqlite_index.ready)
    if values["backend"] == "sqlite" or (values["backend"] == "auto" and not values["es_url"]):
        online = await search_worker_health(values, app)
        return result(
            "search",
            "READY" if draft or local_ready and online else "DEGRADED",
            "sqlite",
            "本地引擎连接通过，保存后构建索引"
            if draft
            else "本地轻量检索可用"
            if local_ready and online
            else "本地索引或工作进程尚未就绪",
            "配置远程引擎与向量模型可启用语义检索",
            index_ready=local_ready,
            worker_online=online,
        )
    if not values["es_url"]:
        return result("search", "NOT_CONFIGURED", "elasticsearch", "远程搜索地址缺失", "填写 Elasticsearch 地址")
    try:
        async with make_search_client(values) as es:
            health = await es.cluster.health()
            if health.get("status") == "red":
                raise ValueError("cluster unhealthy")
            target, profile = await run_db_txn(configuration)
            remote_ready = bool(target and await es.indices.exists(index=target["physical_index"]))
            if remote_ready:
                await es.count(index=target["physical_index"])
    except Exception:
        return result(
            "search",
            "DEGRADED",
            "sqlite" if values["backend"] == "auto" else "elasticsearch",
            "远程引擎不可用，已回退本地检索" if values["backend"] == "auto" else "远程引擎连接或索引权限校验失败",
            "检查地址、认证、证书与索引权限",
            local_index_ready=local_ready,
            remote_connected=False,
        )
    if values["embedding_api_key"]:
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
            await embed(
                client,
                {
                    "endpoint": values["embedding_endpoint"],
                    "model_id": values["embedding_model"],
                    "protocol": values.get("embedding_protocol", "openai_compatible"),
                    "encrypted_api_key": encrypt_key(values["embedding_api_key"]),
                },
                ["连接测试"],
                runtime_credentials=False,
            )
    if not draft and not values["embedding_api_key"] and profile and profile.get("encrypted_api_key"):
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
            await embed(client, profile, ["连接测试"], runtime_credentials=False)
    if draft:
        return result(
            "search",
            "READY",
            "semantic" if values["embedding_api_key"] else "lexical",
            "远程连接验证通过；保存后自动构建并核验索引",
            remote_connected=True,
            index_ready=remote_ready,
        )
    runtime = getattr(app.state, "feature_runtime", None)
    switching = runtime and (
        runtime.search_pending
        or runtime.search_target
        and (not target or runtime.search_target != target["physical_index"])
    )
    semantic = bool(
        remote_ready
        and profile
        and target["verified"]
        and profile.get("encrypted_api_key")
        and target["semantic_indexing_state"] == "ready"
        and not switching
    )
    if semantic and values["embedding_api_key"]:
        semantic = (
            profile["endpoint"] == values["embedding_endpoint"]
            and profile["model_id"] == values["embedding_model"]
            and (profile.get("protocol") or "openai_compatible")
            == values.get("embedding_protocol", "openai_compatible")
        )
    online = await search_worker_health(values, app)
    if not online:
        return result(
            "search",
            "DEGRADED",
            "semantic" if semantic else "lexical",
            "索引工作进程未在线",
            "刷新状态并检查后台工作进程",
            worker_online=False,
        )
    return result(
        "search",
        "READY" if semantic else "DEGRADED",
        "semantic" if semantic else "lexical" if remote_ready else "sqlite",
        "完整语义与向量检索已就绪" if semantic else "远程连接可用，语义索引尚未就绪",
        "等待索引构建；可在向量索引管理中检查任务与核验结果",
        remote_connected=True,
        index_ready=remote_ready,
        semantic_ready=semantic,
        worker_online=online,
        indexing_state=target["semantic_indexing_state"] if target else "not_configured",
    )


def make_agent(values):
    from app.agents.registry import get_agent_backend

    name = values["backend"]
    if name == "opencode":
        return get_agent_backend(
            name,
            server_url=values["opencode_url"],
            username=values["opencode_username"],
            password=values["opencode_password"],
        )
    if name == "dsh":
        return get_agent_backend(
            name,
            server_url=values["dsh_url"],
            browser_token=values["dsh_browser_token"],
            browser_cookie=values["dsh_browser_cookie"],
        )
    return get_agent_backend(name)


async def probe_agent(values, app, draft):
    if values["backend"] == "mock":
        return result("agent", "DEGRADED", "mock", "当前使用模拟 Agent", "配置真实 Agent 后端")
    backend = make_agent(values)
    try:
        await backend.probe()
    finally:
        await backend.close()
    if values["backend"] == "claude-code":
        return result(
            "agent",
            "DEGRADED",
            "claude-code",
            "Claude Code CLI 可用，模型认证与会话连通尚未验证",
            "完成 CLI 登录或配置服务端模型凭据，再通过实际任务验证",
            binary_available=True,
            authentication_verified=False,
        )
    return result("agent", "READY", values["backend"], "Agent 后端连接与协议校验通过")


async def probe_oauth(values, app, draft):
    if not values["enabled"]:
        return result("oauth", "DISABLED", "github", "GitHub 登录已停用")
    if not all(values[k] for k in ("client_id", "client_secret", "redirect_uri_web")):
        return result("oauth", "NOT_CONFIGURED", "github", "登录通道缺少应用凭据或网页回调地址", "完善 GitHub 应用配置")
    async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
        # A read-only token check authenticates the app, then rejects an invalid token.
        # This does not verify that a callback URL is registered at GitHub.
        response = await client.post(
            "https://api.github.com/applications/" + quote(values["client_id"], safe="") + "/token",
            auth=(values["client_id"], values["client_secret"]),
            headers={"Accept": "application/vnd.github+json"},
            json={"access_token": "traceforge-probe-invalid-token"},
        )
    if response.status_code != 404:
        return result("oauth", "DEGRADED", "github", "GitHub 应用认证或连接校验失败", "检查 Client ID、Secret 与网络")
    return result(
        "oauth",
        "READY",
        "github",
        "GitHub 应用认证通道可用",
        "回调地址登记需要通过一次实际登录确认",
        credentials_verified=True,
        callback_verified=False,
    )


async def probe_diagnosis(values, app, draft):
    level = values["enforcement"]
    if not values["worker_enabled"]:
        return result("diagnosis", "DISABLED", level, "诊断工作进程已停用")
    runtime = getattr(app.state, "feature_runtime", None)
    online = bool(
        runtime
        and runtime.playbook_task
        and not runtime.playbook_task.done()
        and runtime.playbook_worker
        and time.monotonic() - runtime.playbook_worker.last_poll_at < 15
    )
    if level != "ADVISORY_GUARD":
        from app.agents.runtime_control import BackendRuntimeControl
        from app.domains.diagnosis_playbook.models import PlaybookRun

        agent_values = {field.key: getattr(feature_settings, field.env) for field in CATALOG["agent"][1]}
        backend = make_agent(agent_values)
        control = BackendRuntimeControl(backend)

        def environments(db):
            rows = db.query(PlaybookRun).order_by(PlaybookRun.updated_at.desc()).limit(100).all()
            return [row.data_json.get("environment", {}) for row in rows if row.data_json]

        try:
            candidates = await run_db_txn(environments)
            candidate = next(
                (
                    env
                    for env in candidates
                    if env
                    and env.get("backend_isolation_verified") is True
                    and env.get("backend_host_identity") == control.host_identity
                    and env.get("enforcement") == level
                ),
                None,
            )
            verified = bool(candidate)
            if candidate:
                await control.negotiate(candidate, configured_enforcement=level)
        finally:
            await backend.close()
        return result(
            "diagnosis",
            "READY" if verified and (online or draft) else "DEGRADED",
            level,
            "强制防线已启用，每次执行将核验绑定环境" if verified else "尚无满足当前防线的已验证执行环境",
            "安装并验证隔离执行环境；不满足约束的任务会被拒绝执行",
            worker_online=online,
            sandbox_verified=verified,
            per_run_verification_required=True,
        )
    return result(
        "diagnosis",
        "READY" if online or draft else "DEGRADED",
        level,
        "建议防线可用；此模式不提供强制沙箱隔离" if online or draft else "诊断工作进程尚未在线",
        "需要强制隔离时配置工作树代理或容器沙箱",
        worker_online=online,
        sandbox_enforced=False,
    )


PROBES = {
    "speech": probe_speech,
    "search": probe_search,
    "diagnosis": probe_diagnosis,
    "oauth": probe_oauth,
    "agent": probe_agent,
}


async def probe(feature, values, app, *, draft=False):
    try:
        async with asyncio.timeout(8):
            return await PROBES[feature](values, app, draft)
    except Exception:
        mode = str(values.get("mode", values.get("backend", values.get("enforcement", "github"))))
        return result(
            feature,
            "DEGRADED",
            mode,
            "服务探测失败或超时",
            "检查凭据、服务地址、网络与依赖健康状态；探针不会返回上游错误内容",
        )
