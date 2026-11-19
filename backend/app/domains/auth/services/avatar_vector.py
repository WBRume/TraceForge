"""Prepare a self-contained SVG image and its avatar viewport."""

import math
from xml.etree import ElementTree as ET

from app.domains.auth.services.avatar_image import AVATAR_MAX_UPLOAD_BYTES, AvatarImageTooLargeError

SVG_MIME = "image/svg+xml"
_SVG = "{http://www.w3.org/2000/svg}"
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_XML_TEXT_ATTRS = {"{http://www.w3.org/XML/1998/namespace}space", "{http://www.w3.org/XML/1998/namespace}lang"}
_BLOCKED_TAGS = {"script", "foreignObject", "iframe", "object", "embed", "handler", "listener", "a"}
_ANIMATION_TAGS = {"animate", "animateTransform", "animateColor", "set"}
_BLOCKED_ANIMATION_ATTRS = {"href", "src", "id", "style"}
_IMAGE_DATA_PREFIXES = tuple(f"data:image/{kind};base64," for kind in ("png", "jpeg", "gif", "webp", "avif"))


def _avatar_viewport(raw: str) -> str:
    """Validate source dimensions and crop coordinates before storing them in the URL fragment."""
    try:
        width, height, left, top, side = (float(value) for value in raw.split())
    except ValueError as exc:
        raise ValueError("Invalid SVG avatar crop") from exc
    values = width, height, left, top, side
    if not all(map(math.isfinite, values)):
        raise ValueError("Invalid SVG avatar crop")
    tolerance = 1e-6
    minimum = min(width, height)
    if (
        minimum < 1
        or width * height > 32_000_000
        or min(left, top) < 0
        or side < minimum / 4 - tolerance
        or side > minimum + tolerance
        or left + side > width + tolerance
        or top + side > height + tolerance
    ):
        raise ValueError("Invalid SVG avatar crop")
    return ",".join(format(value, ".12g") for value in values)


def _keep_child(element: ET.Element) -> bool:
    if not element.tag.startswith(_SVG):
        return False
    local = element.tag.removeprefix(_SVG)
    if local in _BLOCKED_TAGS:
        return False
    if local in _ANIMATION_TAGS:
        attribute = element.get("attributeName", "").strip().lower()
        return bool(
            attribute
            and ":" not in attribute
            and not attribute.startswith("on")
            and attribute not in _BLOCKED_ANIMATION_ATTRS
        )
    return True


def _clean_vector(root: ET.Element) -> None:
    pending = [root]
    while pending:
        element = pending.pop()
        for child in list(element):
            if _keep_child(child):
                pending.append(child)
            else:
                element.remove(child)
        for name, value in list(element.attrib.items()):
            if name in {"href", _XLINK_HREF}:
                value = value.strip()
                allowed = value.startswith("#") or (
                    element.tag == f"{_SVG}image" and value.lower().startswith(_IMAGE_DATA_PREFIXES)
                )
                if not allowed:
                    del element.attrib[name]
            elif name.lower().startswith("on") or ("}" in name and name not in _XML_TEXT_ATTRS):
                del element.attrib[name]


def encode_avatar_svg(raw: bytes) -> tuple[bytes, str]:
    """Extract the SVG source from the editor payload and return its viewport fragment."""
    try:
        markup = raw.decode("utf-8")
        if "<!DOCTYPE" in markup.upper():
            raise ValueError("SVG document type declarations are not supported")
        envelope = ET.fromstring(markup)
    except (UnicodeError, ET.ParseError) as exc:
        raise ValueError("Invalid SVG avatar") from exc
    if envelope.tag != f"{_SVG}svg" or len(envelope) != 1 or envelope[0].tag != f"{_SVG}svg":
        raise ValueError("Expected an SVG avatar crop")
    viewport = _avatar_viewport(envelope.get("data-avatar-crop", ""))
    source = envelope[0]
    _clean_vector(source)
    try:
        image = ET.tostring(source, encoding="utf-8")
    except RecursionError as exc:
        raise ValueError("SVG avatar nesting exceeds the processing limit") from exc
    if len(image) > AVATAR_MAX_UPLOAD_BYTES:
        raise AvatarImageTooLargeError("Encoded SVG avatar exceeds the size limit")
    return image, f"#crop={viewport}"
