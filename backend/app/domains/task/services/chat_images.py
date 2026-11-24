"""Storage and authorization for task chat image attachments."""

from collections.abc import Sequence
from hashlib import sha256
from io import BytesIO
from uuid import NAMESPACE_URL, UUID, uuid5

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session, load_only
from typing_extensions import TypedDict

from app.agents.contract import AgentInputImage
from app.agents.registry import registered_backends
from app.agents.selection import normalize_backend_name, resolve_workspace_backend
from app.domains.task.models.chat import TaskChatImage
from app.domains.task.models.task import SddTask

CHAT_IMAGES_KEY = "chat_images"
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}


class ChatImageError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class ChatImageRef(TypedDict):
    id: str
    filename: str
    media_type: str


def _reference(image: TaskChatImage) -> ChatImageRef:
    return {"id": image.id, "filename": image.filename, "media_type": image.media_type}


def require_image_backend(db: Session, task: SddTask) -> None:
    backend = normalize_backend_name(task.agent_backend) or resolve_workspace_backend(db, task.workspace_id)
    entry = registered_backends().get(backend)
    if not entry or not entry.backend_cls.capabilities.supports_image_input:
        raise ChatImageError("当前 Agent 未接入图片输入", 422)


def store_image(db: Session, task: SddTask, actor_id: str, filename: str, raw: bytes) -> ChatImageRef:
    """Validate raster bytes and reuse the receipt if the same upload is retried."""
    require_image_backend(db, task)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ChatImageError("图片不能超过 5 MiB", 413)
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or filename in {".", ".."} or len(filename) > 255 or any(ord(char) < 32 for char in filename):
        raise ChatImageError("图片文件名无效", 422)
    try:
        with Image.open(BytesIO(raw), formats=list(MEDIA_TYPES)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ChatImageError("图片像素超过上限", 413)
            media_type = MEDIA_TYPES[image.format]
            image.verify()
    except UnidentifiedImageError as exc:
        raise ChatImageError("请选择有效的 PNG、JPEG、WebP 或 GIF 图片", 415) from exc
    except Image.DecompressionBombError as exc:
        raise ChatImageError("图片像素超过上限", 413) from exc
    except ChatImageError:
        raise
    except (EOFError, OSError, SyntaxError, ValueError) as exc:
        raise ChatImageError("图片文件损坏", 422) from exc

    digest = sha256(filename.encode() + b"\x00" + raw).hexdigest()
    image_id = str(uuid5(NAMESPACE_URL, f"traceforge/task-chat-image/{task.id}/{actor_id}/{digest}"))
    db.query(SddTask.id).filter_by(id=task.id).with_for_update().one()
    existing = db.get(TaskChatImage, image_id)
    if existing is not None:
        return _reference(existing)
    image = TaskChatImage(
        id=image_id, task_id=task.id, creator_id=actor_id, filename=filename, media_type=media_type, data=raw
    )
    db.add(image)
    return _reference(image)


def resolve_references(db: Session, task: SddTask, actor_id: str, image_ids: object) -> list[ChatImageRef]:
    """Resolve only images uploaded for this task by the sender, in message order."""
    if image_ids is None or image_ids == []:
        return []
    if not isinstance(image_ids, list) or len(image_ids) > MAX_IMAGES:
        raise ChatImageError("每条消息最多附加 4 张图片", 422)
    try:
        ids = [str(UUID(image_id)) for image_id in image_ids]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ChatImageError("图片标识无效", 422) from exc
    if len(set(ids)) != len(ids):
        raise ChatImageError("同一张图片不能重复附加", 422)
    require_image_backend(db, task)
    rows = (
        db.query(TaskChatImage)
        .options(load_only(TaskChatImage.id, TaskChatImage.filename, TaskChatImage.media_type))
        .filter(TaskChatImage.task_id == task.id, TaskChatImage.creator_id == actor_id, TaskChatImage.id.in_(ids))
        .all()
    )
    references = {row.id: _reference(row) for row in rows}
    if len(references) != len(ids):
        raise ChatImageError("图片不存在或不属于当前任务和发送者", 404)
    return [references[image_id] for image_id in ids]


def load_agent_images(db: Session, task_id: str, references: Sequence[ChatImageRef]) -> tuple[AgentInputImage, ...]:
    """Read the immutable attachments for one accepted input."""
    if not references:
        return ()
    ids = [reference["id"] for reference in references]
    rows = db.query(TaskChatImage).filter(TaskChatImage.task_id == task_id, TaskChatImage.id.in_(ids)).all()
    images = {row.id: AgentInputImage(row.filename, row.media_type, bytes(row.data)) for row in rows}
    if len(images) != len(ids):
        raise ChatImageError("消息的图片附件已不可用", 404)
    return tuple(images[image_id] for image_id in ids)
