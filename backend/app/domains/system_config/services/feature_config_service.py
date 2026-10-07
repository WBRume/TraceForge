"""Encrypted DB overrides > startup environment, with explicit preserve/clear/reset."""

import base64
import hashlib
import hmac
import json
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.domains.system_config.models.feature_config import FeatureConfig
from app.domains.system_config.services.feature_catalog import CATALOG
from app.domains.system_config.services.system_config_service import SystemConfigError


def cipher():
    explicit = settings.FEATURE_CONFIG_MASTER_KEY.get_secret_value().strip()
    key = (
        explicit.encode()
        if explicit
        else base64.urlsafe_b64encode(
            hmac.digest(settings.JWT_SECRET_KEY.encode(), b"traceforge:feature-config:v1", "sha256")
        )
    )
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        raise SystemConfigError("业务配置主密钥格式无效", 503) from None


def fields_for(feature):
    if feature not in CATALOG:
        raise SystemConfigError("未知业务特性", 404)
    return CATALOG[feature][1]


def decrypt(row):
    if row is None:
        return {}
    try:
        values = json.loads(cipher().decrypt(row.encrypted_values.encode()))
        if not isinstance(values, dict):
            raise ValueError
        validate_values(row.feature, values)
        return values
    except (InvalidToken, ValueError, TypeError, SystemConfigError):
        # A corrupt override must not silently re-enable an ENV feature.
        raise SystemConfigError("业务配置无法解密或校验，请检查主密钥或恢复环境配置", 503) from None


def validate_values(feature, values):
    fields = {field.key: field for field in fields_for(feature)}
    if not isinstance(values, dict) or set(values) - fields.keys():
        raise SystemConfigError("配置包含不支持的字段", 422)
    for key, value in values.items():
        if value is not None and not fields[key].validate(value):
            raise SystemConfigError(f"配置字段校验失败：{fields[key].label}", 422)


def effective(feature, overrides):
    return {
        field.key: field.default() if overrides.get(field.key) is None else overrides[field.key]
        for field in fields_for(feature)
    }


def legacy_search_values(db, *, include_key=True):
    # Preserve pre-existing, encrypted vector profiles during feature-center adoption.
    from app.domains.search.embedding import EmbeddingError, decrypt_key
    from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget

    target = (
        db.query(SearchIndexTarget)
        .filter(
            SearchIndexTarget.status.in_(["active", "standby"]),
            ~SearchIndexTarget.physical_index.like("traceforge-search-runtime-%"),
        )
        .order_by((SearchIndexTarget.status == "active").desc(), SearchIndexTarget.created_at.desc())
        .first()
    )
    profile = (
        db.get(SearchEmbeddingProfile, target.embedding_profile_id) if target and target.embedding_profile_id else None
    )
    if not profile:
        return {}
    key = ""
    if include_key and profile.encrypted_api_key:
        try:
            key = decrypt_key(profile.encrypted_api_key)
        except (EmbeddingError, ValueError):
            # A replacement in the feature center can repair legacy key failures.
            key = ""
    return {"embedding_endpoint": profile.endpoint, "embedding_model": profile.model_id, "embedding_api_key": key}


def resolve(db, feature, overrides):
    values = effective(feature, overrides)
    if feature == "search":
        row = db.get(FeatureConfig, feature)
        if row is None or overrides:
            legacy = legacy_search_values(db, include_key="embedding_api_key" not in overrides)
            values.update({key: value for key, value in legacy.items() if key not in overrides})
    return values


def read(db, feature):
    fields_for(feature)
    row = db.get(FeatureConfig, feature)
    overrides = decrypt(row)
    return resolve(db, feature, overrides), overrides, row.revision if row else 0


def snapshot(db):
    rows = db.query(FeatureConfig).all()
    return {row.feature: decrypt(row) for row in rows if row.feature in CATALOG}


def environment_snapshot(overrides):
    result = {}
    for feature, values in overrides.items():
        for field in fields_for(feature):
            if field.key in values:
                result[field.env] = field.default() if values[field.key] is None else values[field.key]
    return result


def public_value(field, value):
    if field.kind == "secret":
        if value and field.key in {"api_key", "embedding_api_key"} and len(value) > 12:
            return f"{value[:4]}********{value[-4:]}"
        return "********" if value else ""
    if field.kind in {"url", "https"} and value:
        try:
            parts = urlsplit(value)
            # Older ENV URLs may embed authentication that new online fields reject.
            return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
        except ValueError:
            return ""
    return value


def public(db, feature):
    try:
        values, overrides, revision = read(db, feature)
    except SystemConfigError as exc:
        if exc.status_code != 503:
            raise
        row = db.get(FeatureConfig, feature)
        return {
            "feature": feature,
            "title": CATALOG[feature][0],
            "revision": row.revision,
            "configured": True,
            "fields": [],
            "error": str(exc),
        }
    row = db.get(FeatureConfig, feature)
    legacy_fields = (
        legacy_search_values(db, include_key=False).keys() if feature == "search" and (row is None or overrides) else ()
    )
    return {
        "feature": feature,
        "title": CATALOG[feature][0],
        "revision": revision,
        "configured": bool(overrides),
        "fields": [
            {
                "key": field.key,
                "label": field.label,
                "kind": field.kind,
                "value": public_value(field, values[field.key]),
                "has_value": bool(values[field.key]),
                "source": "database"
                if (
                    field.key in overrides
                    and overrides[field.key] is not None
                    or field.key not in overrides
                    and field.key in legacy_fields
                )
                else "environment",
                "options": list(field.options),
                "minimum": field.minimum,
                "maximum": field.maximum,
                "hint": field.hint,
            }
            for field in fields_for(feature)
        ],
    }


def draft(db, feature, values, revision, reset=False):
    validate_values(feature, values)
    row = db.get(FeatureConfig, feature)
    if revision != (row.revision if row else 0):
        raise SystemConfigError("配置已被其他管理员修改，请刷新后重试", 409)
    overrides = {} if reset else decrypt(row)
    for key, value in values.items():
        if value is None:
            # Persist the ENV choice so a legacy DB profile cannot supersede it.
            overrides[key] = None
        else:
            overrides[key] = value.strip() if isinstance(value, str) else value
    return (effective(feature, {}) if reset else resolve(db, feature, overrides)), overrides


def save(db, feature, values, revision, actor, reset=False):
    _, overrides = draft(db, feature, values, revision, reset)
    if not values and not reset:
        return public(db, feature)
    encrypted = cipher().encrypt(json.dumps(overrides, ensure_ascii=False).encode()).decode()
    if revision:
        changed = db.execute(
            update(FeatureConfig)
            .where(FeatureConfig.feature == feature, FeatureConfig.revision == revision)
            .values(encrypted_values=encrypted, revision=revision + 1, updated_by=actor)
        )
        if changed.rowcount != 1:
            raise SystemConfigError("配置已被其他管理员修改，请刷新后重试", 409)
    else:
        db.add(FeatureConfig(feature=feature, encrypted_values=encrypted, revision=1, updated_by=actor))
        try:
            db.flush()
        except IntegrityError:
            raise SystemConfigError("配置已被其他管理员修改，请刷新后重试", 409) from None
    db.expire_all()
    return public(db, feature)


def fingerprint(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
