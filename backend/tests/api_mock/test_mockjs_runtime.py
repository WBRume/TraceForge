import shutil

import pytest

from app.domains.api_mock.services.api_mock.preview_service import _render_mockjs


@pytest.mark.skipif(shutil.which("node") is None, reason="Node runtime is not installed")
def test_mockjs_renders_random_template_with_real_node():
    values = [_render_mockjs('{"value|1-1000000":1}', None) for _ in range(5)]
    assert all(isinstance(row.get("value"), int) and 1 <= row["value"] <= 1000000 for row in values)
    assert len({row["value"] for row in values}) > 1


@pytest.mark.skipif(shutil.which("node") is None, reason="Node runtime is not installed")
def test_mockjs_renders_fixed_array_length_with_real_node():
    assert _render_mockjs('{"items|3":[{"ok":true}]}', None) == {"items": [{"ok": True}] * 3}
