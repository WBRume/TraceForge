"""Workspace Asset 服务层模块边界守护测试。

重构后 services 按子域组织：common / requirements(+preview) / tasks /
task_process / task_final_workflow / traceability / overview。本文件做两件事：

1. 依赖方向守护（AST 解析 import，防止子域反向耦合回潮）；
2. 新拆出的纯逻辑模块（segmentation / prompt / primitives 覆盖谓词）的单测。
"""

import ast
import os
import sys

import pytest

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.workspace_asset.services.common.primitives import (  # noqa: E402
    clean_optional,
    coverage_status,
    dedupe_by_id,
    is_human_confirmation,
)
from app.domains.workspace_asset.services.requirements.preview.prompt import (  # noqa: E402
    build_requirement_preview_prompt,
    coalesce_simple_import_preview_items,
    extract_json_object,
    normalize_ai_preview_items,
)
from app.domains.workspace_asset.services.requirements.segmentation import (  # noqa: E402
    direct_import_title,
    extract_acceptance_criteria,
    looks_like_single_requirement,
    segment_requirements,
)


SERVICES_FS_ROOT = os.path.join(BACKEND_ROOT, "app", "domains", "workspace_asset", "services")
SERVICES_PKG = "app.domains.workspace_asset.services"
SUBDOMAINS = ("common", "requirements", "tasks", "task_process", "task_final_workflow")

# 允许的子域间依赖边（tasks -> requirements 仅限 presenters 单向渲染复用）。
ALLOWED_EDGES = {
    ("requirements", "common"),
    ("tasks", "common"),
    ("tasks", "requirements"),
    ("task_process", "common"),
    ("task_final_workflow", "common"),
    ("task_final_workflow", "task_process"),
    ("task_final_workflow", "tasks"),
    # 过程资产写与 final workflow 之间存在业务上的双向联动
    # （Evidence 创建联动专家评审、终审校验复核专家评审），
    # 以函数级延迟导入打破模块级环；此处登记为合法边。
    ("task_process", "task_final_workflow"),
}


def _subdomain_of(module: str):
    rel = module[len(SERVICES_PKG) + 1:]
    head = rel.split(".")[0]
    return head if head in SUBDOMAINS else None


def _iter_service_modules():
    for root, _dirs, files in os.walk(SERVICES_FS_ROOT):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            module = (
                path[len(BACKEND_ROOT) + 1:-3]
                .replace("\\", ".")
                .replace("/", ".")
            )
            yield path, module


def _imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def test_subdomain_dependency_directions_are_acyclic_and_whitelisted():
    edges = set()
    offenders = []
    for path, module in _iter_service_modules():
        src_pkg = _subdomain_of(module)
        if src_pkg is None:
            continue
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        for imported in _imported_modules(tree):
            if not imported.startswith(SERVICES_PKG + "."):
                continue
            dst_pkg = _subdomain_of(imported)
            if dst_pkg is None or dst_pkg == src_pkg:
                continue
            edges.add((src_pkg, dst_pkg))
            if (src_pkg, dst_pkg) not in ALLOWED_EDGES:
                offenders.append((path, src_pkg, dst_pkg))
    assert not offenders, f"子域依赖方向违规: {offenders}"
    # 已登记的边必须真实存在，防止白名单腐化
    assert edges == ALLOWED_EDGES, f"依赖边与白名单不一致: 实际={sorted(edges)}"


def test_common_subpackage_has_no_inward_imports():
    for path, module in _iter_service_modules():
        if _subdomain_of(module) != "common":
            continue
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        for imported in _imported_modules(tree):
            if imported.startswith(SERVICES_PKG + "."):
                head = imported[len(SERVICES_PKG) + 1:].split(".")[0]
                # 允许 common 依赖自身与顶层叶子模块（human_delta_compare_service
                # 只依赖 models/schemas，是过程资产展示的既有底层依赖）。
                assert head in {"common", "human_delta_compare_service"}, (
                    f"common 不得依赖其他子域: {path} -> {imported}"
                )


# ── segmentation：Markdown 分段与验收标准抽取 ──


def test_segment_requirements_by_headings():
    markdown = "# Feature A\n\nBody A\n\n# Feature B\n\nBody B\n"
    items = segment_requirements(markdown)
    assert [item["title"] for item in items] == ["Feature A", "Feature B"]
    assert items[0]["body"] == "Body A"
    assert [item["source_ref"] for item in items] == ["heading:1", "heading:2"]
    assert [item["order_index"] for item in items] == [0, 1]


def test_segment_requirements_falls_back_to_list_items_then_whole_document():
    numbered = "1. First requirement\n   detail\n2. Second requirement\n"
    items = segment_requirements(numbered)
    assert [item["title"] for item in items] == ["First requirement", "Second requirement"]

    single = "One loose requirement without structure\n"
    items = segment_requirements(single)
    assert len(items) == 1
    assert items[0]["title"] == "One loose requirement without structure"
    assert items[0]["source_ref"] == "document:1"
    assert segment_requirements("") == []


def test_extract_acceptance_criteria_supports_checkboxes_and_sections():
    markdown = (
        "# Req\n\n"
        "Acceptance Criteria\n"
        "- [x] Login works\n"
        "- [ ] Logout works\n"
        "* Plain item\n"
        "\n"
        "# Other\n"
        "- [ ] belongs to other section\n"
    )
    criteria = extract_acceptance_criteria(markdown.splitlines())
    assert criteria == ["Login works", "Logout works", "Plain item"]


def test_direct_import_title_prefers_first_heading_then_filename():
    assert direct_import_title("x.md", "# My Feature\nbody") == "My Feature"
    # 无 heading 时取首个非空行，最后才回退到文件名
    assert direct_import_title("auth-flow.md", "plain text body") == "plain text body"
    assert direct_import_title("auth-flow.md", "") == "auth-flow"
    assert direct_import_title("", "") == "Imported Requirement"


def test_looks_like_single_requirement_guards_over_splitting():
    assert looks_like_single_requirement("Short single requirement text") is True
    assert looks_like_single_requirement("# A\n\n# B\n") is False
    long_text = "x" * 1000
    assert looks_like_single_requirement(long_text) is False
    assert looks_like_single_requirement("REQ-1: one\nREQ-2: two") is False


# ── preview prompt / AI 输出解析 ──


def test_build_requirement_preview_prompt_embeds_boundaries_and_document():
    prompt = build_requirement_preview_prompt(
        mode="import",
        markdown="Doc body",
        source_kind="document",
        source_ref="r1",
        source_uri="file:///a.md",
        file_name="a.md",
    )
    assert "只输出 JSON" in prompt
    assert "不创建 Task" in prompt
    assert "Preview mode: import" in prompt
    assert "Doc body" in prompt


def test_extract_json_object_strips_code_fence_and_embedded_json():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('prefix {"a": {"b": 2}} suffix') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        extract_json_object("[1, 2]")


def test_normalize_ai_preview_items_maps_camelcase_and_marks_ai_split():
    payload = {
        "items": [
            {"title": "A", "acceptanceCriteria": ["c1"], "sourceRef": "r1", "taskPrompt": "p"},
            {"body": "no title but body\nsecond line"},
            "not-a-dict",
        ]
    }
    items = normalize_ai_preview_items(payload)
    assert len(items) == 2
    assert items[0]["acceptance_criteria"] == ["c1"]
    assert items[0]["source_metadata"]["task_prompt"] == "p"
    assert items[0]["source_metadata"]["ai_split"] is True
    assert items[1]["title"] == "no title but body"


def test_coalesce_keeps_single_simple_requirement_unsplit():
    markdown = "Short single requirement"
    multi = [
        {"title": f"part {i}", "source_metadata": {}, "source_ref": f"ai:{i}"} for i in range(3)
    ]
    coalesced = coalesce_simple_import_preview_items(markdown=markdown, file_name="a.md", items=multi)
    assert len(coalesced) == 1
    assert coalesced[0]["source_metadata"]["split_decision"] == "kept_single_simple_requirement"

    structured = "# A\n\n# B\n"
    kept = coalesce_simple_import_preview_items(
        markdown=structured,
        file_name="a.md",
        items=[{"title": "A", "source_metadata": {}}, {"title": "B", "source_metadata": {}}],
    )
    assert len(kept) == 2


# ── primitives：coverage 谓词 ──


def _evidence(status, source_type, confirmed_by=None, confirmed_at=None):
    class _E:
        pass

    e = _E()
    e.status = status
    e.source_type = source_type
    e.confirmed_by_id = confirmed_by
    e.confirmed_at = confirmed_at
    return e


def test_is_human_confirmation_requires_confirmed_human_evidence():
    from app.domains.workspace_asset.models.workspace_asset import EvidenceSourceType, EvidenceStatus

    from datetime import datetime

    ok = _evidence(
        EvidenceStatus.CONFIRMED,
        EvidenceSourceType.HUMAN_CONFIRMATION,
        confirmed_by="user-1",
        confirmed_at=datetime.utcnow(),
    )
    assert is_human_confirmation(ok)
    not_confirmed = _evidence(EvidenceStatus.UNCONFIRMED, EvidenceSourceType.HUMAN_CONFIRMATION)
    assert not is_human_confirmation(not_confirmed)
    machine = _evidence(
        EvidenceStatus.CONFIRMED,
        EvidenceSourceType.RUN_LOG,
        confirmed_by="user-1",
        confirmed_at=datetime.utcnow(),
    )
    assert not is_human_confirmation(machine)


def test_coverage_status_state_machine():
    from app.domains.workspace_asset.models.workspace_asset import EvidenceSourceType, EvidenceStatus

    from datetime import datetime

    assert coverage_status(0, []) == "not_available"
    assert coverage_status(1, []) == "waiting_evidence"

    plain_confirmed = _evidence(EvidenceStatus.CONFIRMED, EvidenceSourceType.RUN_LOG)
    assert coverage_status(1, [plain_confirmed]) == "waiting_human_confirmation"

    human = _evidence(
        EvidenceStatus.CONFIRMED,
        EvidenceSourceType.HUMAN_CONFIRMATION,
        confirmed_by="user-1",
        confirmed_at=datetime.utcnow(),
    )
    assert coverage_status(1, [plain_confirmed, human]) == "verified"


def test_dedupe_and_clean_optional_primitives():
    class _Item:
        def __init__(self, item_id):
            self.id = item_id

    a, b = _Item("1"), _Item("2")
    assert [item.id for item in dedupe_by_id([a, b, a, _Item(None)])] == ["1", "2"]
    assert clean_optional("  x ", limit=2) == "x"
    assert clean_optional("   ") is None
