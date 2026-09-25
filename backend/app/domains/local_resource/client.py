"""Authenticated intranet transport; never interprets host paths locally."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import socket
from urllib.parse import urlsplit
import httpx
from app.agents.http_transport import agent_ssl_context
from cryptography.fernet import Fernet
from app.config import settings


class ResourceError(ValueError):
    def __init__(self, message, code="RESOURCE_UNAVAILABLE", status_code=409):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def require_enabled():
    if settings.LOCAL_RESOURCES_MODE != "intranet":
        raise ResourceError("当前本地资源仅支持内网部署，暂不支持公网部署", "LOCAL_RESOURCES_DISABLED", 403)


def validate_url(value):
    require_enabled()
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ResourceError("服务地址必须是无凭据的 HTTP(S) 地址", "INVALID_RESOURCE_URL", 422)
    if parsed.path not in ("", "/"):
        raise ResourceError("服务地址不能包含路径", "INVALID_RESOURCE_URL", 422)
    try:
        addresses = {ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(parsed.hostname, parsed.port or 80, type=socket.SOCK_STREAM)}
        networks = [ipaddress.ip_network(item.strip()) for item in settings.LOCAL_RESOURCES_ALLOWED_NETWORKS.split(",") if item.strip()]
    except (ValueError, OSError) as exc:
        raise ResourceError("无法解析内网服务地址", "INVALID_RESOURCE_URL") from exc
    if not addresses or any(ip.is_link_local or ip.is_multicast or ip.is_unspecified or not any(ip in net for net in networks) for ip in addresses):
        raise ResourceError("服务地址不在部署允许的内网范围内", "RESOURCE_NETWORK_FORBIDDEN", 403)
    return value.rstrip("/")


def encrypt_credentials(value):
    if not settings.LOCAL_RESOURCES_ENCRYPTION_KEY:
        raise ResourceError("请配置 LOCAL_RESOURCES_ENCRYPTION_KEY", "RESOURCE_ENCRYPTION_NOT_CONFIGURED")
    return Fernet(settings.LOCAL_RESOURCES_ENCRYPTION_KEY.encode()).encrypt(json.dumps(value).encode()).decode()


def decrypt_credentials(value):
    try:
        return json.loads(Fernet(settings.LOCAL_RESOURCES_ENCRYPTION_KEY.encode()).decrypt(value.encode()))
    except Exception as exc:
        raise ResourceError("本地资源凭据不可解密，请检查部署密钥", "RESOURCE_CREDENTIAL_UNAVAILABLE") from exc


class ResourceClient:
    def __init__(self, profile, *, timeout=300):
        self.profile = profile
        self.timeout = timeout
        self.url = validate_url(profile["resource_service_url"])
        self.credentials = decrypt_credentials(profile["encrypted_credentials"])

    def request(self, method, path, body=None):
        # No proxy inheritance or redirects into another security boundary.
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False, verify=agent_ssl_context(), follow_redirects=False) as client:
                response = client.request(method, self.url + path, json=body,
                    headers={"Authorization": "Bearer " + self.credentials["host_token"]})
            if response.status_code >= 300:
                detail = response.json().get("detail", {})
                message = detail.get("message", "资源服务请求失败") if isinstance(detail, dict) else str(detail)
                code = detail.get("code", "RESOURCE_OPERATION_FAILED") if isinstance(detail, dict) else "RESOURCE_OPERATION_FAILED"
                if "PATH_OUTSIDE_RESOURCE_ROOT" in message:
                    code = "PATH_OUTSIDE_RESOURCE_ROOT"
                raise ResourceError(message, code)
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, ResourceError):
                raise
            raise ResourceError("同机资源服务不可用，请检查地址、端口和认证", "RESOURCE_HOST_UNAVAILABLE") from exc

    def identity(self):
        identity = self.request("GET", "/v1/identity")
        if identity.get("protocol_version") != 1:
            raise ResourceError("资源服务协议不兼容", "RESOURCE_PROTOCOL_MISMATCH")
        expected = self.profile.get("host_id")
        if expected and identity.get("host_id") != expected:
            raise ResourceError("资源主机身份已改变，请重新配置", "RESOURCE_HOST_CHANGED")
        return identity

    def operation(self, task_id, kind, payload, operation_id=None):
        import uuid
        body = {"task_id": task_id, "resource_id": self.profile["id"], "kind": kind,
                "payload": payload, "operation_id": operation_id or str(uuid.uuid4())}
        body["payload_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.identity()
        return self.request("POST", "/v1/operations", body)["result"]
