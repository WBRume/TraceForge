from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.search.es import bulk_write, ensure_indices, index_mapping, scope_filters, search_body
from app.domains.search.relevance import minimum_semantic_similarity
from app.domains.search.rrf import search_target
from app.domains.search.storage import physical_indices, semantic_enabled
from app.domains.search.worker import prepare_document

TARGET = {"physical_index": "traceforge-search-test", "schema_version": 2}


@pytest.mark.parametrize(
    ("query", "minimum"),
    [
        ("测试", 0.70),
        ("Redis", 0.70),
        ("连接池", 0.70),
        ("连接池耗尽", 0.58),
        ("数据库可用会话用光后业务请求积压", 0.58),
        ("connection pool exhausted", 0.58),
    ],
)
def test_vector_retrieval_has_a_stricter_cutoff_for_short_queries(query, minimum):
    assert minimum_semantic_similarity(query) == minimum
    assert search_body(query, [], [1, 0, 0], "p")["knn"]["similarity"] == minimum
    assert "knn" not in search_body(query, [])


@pytest.mark.asyncio
async def test_partition_creation_resumes_and_excludes_redundant_source_text():
    es = SimpleNamespace(indices=SimpleNamespace(exists=AsyncMock(side_effect=[True, False]), create=AsyncMock()))
    assert not await ensure_indices(es, TARGET, 3)
    es.indices.create.assert_awaited_once_with(
        index="traceforge-search-test-knowledge", body=index_mapping(3, compact=True)
    )
    mapping = es.indices.create.call_args.kwargs["body"]["mappings"]
    assert set(mapping["_source"]["excludes"]) == {"title", "content_text", "symbols"}
    assert mapping["properties"]["content_text"]["index_options"] == "freqs"
    assert physical_indices(TARGET, "message") == ["traceforge-search-test-history"]
    assert physical_indices({"physical_index": "legacy", "schema_version": 1}) == ["legacy"]


@pytest.mark.asyncio
async def test_mixed_bulk_and_version_conflicts_use_the_same_physical_partition():
    docs = [
        {"entity_key": f"{kind}:1", "kind": kind, "source_version": 1, "deleted": True} for kind in ("message", "case")
    ]
    es = SimpleNamespace(
        bulk=AsyncMock(return_value={"items": [{"index": {"status": 201}}, {"index": {"status": 409}}]}),
        get=AsyncMock(return_value={"_source": docs[1], "_version": 3}),
    )
    assert await bulk_write(es, TARGET, docs) == {"message:1": None, "case:1": None}
    operations = es.bulk.call_args.kwargs["operations"]
    assert operations[0]["index"]["_index"].endswith("-history")
    assert operations[2]["index"]["_index"].endswith("-knowledge")
    assert es.get.call_args.kwargs["index"].endswith("-knowledge")


@pytest.mark.parametrize("kind,semantic", [("task", False), ("message", False), ("case", True), ("playbook", True)])
def test_only_knowledge_documents_prepare_vectors(kind, semantic):
    doc = {"kind": kind, "projection_hash": "hash", "deleted": False}
    result = prepare_document(doc, TARGET, {"id": "p", "fingerprint": "space"})
    assert ("embedding_input_hash" in result) == semantic
    assert semantic_enabled(TARGET, kind) == semantic
    assert semantic_enabled({"schema_version": 1}, kind)


@pytest.mark.asyncio
async def test_partition_recall_has_separate_rankings_and_shared_acl():
    def hit(key):
        return {"_id": key, "_source": {"entity_key": key}}

    async def search(*, body):
        if "knn" in body:
            return {"hits": {"hits": [hit("case:semantic")]}}
        index = body["query"]["bool"]["filter"][-1]["term"]["_index"]
        return {
            "hits": {
                "hits": [hit(f"message:{i}") for i in range(200)]
                if index.endswith("history")
                else [hit("case:lexical")]
            }
        }

    es = SimpleNamespace(
        search=AsyncMock(side_effect=search),
        open_point_in_time=AsyncMock(return_value={"id": "pit"}),
        close_point_in_time=AsyncMock(),
    )
    filters = scope_filters(["only-this-workspace"])
    hits = await search_target(es, TARGET, "连接池", filters, vector=[1, 0, 0], profile_id="p")
    assert {"case:lexical", "case:semantic"} <= {h["_id"] for h in hits[:4]}
    for call in es.search.call_args_list:
        body = call.kwargs["body"]
        assert "highlight" not in body
        assert body["pit"]["id"] == "pit"
        actual = body["knn"]["filter"] if "knn" in body else body["query"]["bool"]["filter"]
        assert {"terms": {"workspace_id": ["only-this-workspace"]}} in actual
        if "query" in body:
            assert body["query"]["bool"]["should"][0]["multi_match"]["auto_generate_synonyms_phrase_query"] is False
    es.close_point_in_time.assert_awaited_once_with(id="pit")
