"""ES mapping, bounded lexical/vector recall and strict external-version writes."""
from copy import deepcopy
from app.config import settings
from app.domains.search.projection import es_version


def create_client():
    from elasticsearch import AsyncElasticsearch
    return AsyncElasticsearch(settings.SEARCH_ES_URL,
        basic_auth=(settings.SEARCH_ES_USERNAME, settings.SEARCH_ES_PASSWORD),
        ca_certs=settings.SEARCH_ES_CA_CERTS or None, request_timeout=2, max_retries=0)


def index_mapping(dimension=None):
    props = {k: {"type": "keyword"} for k in (
        "entity_key", "kind", "workspace_id", "task_id", "message_id", "creator_id", "role",
        "message_type", "projection_hash", "embedding_profile_id", "embedding_input_hash")}
    props.update({"source_version": {"type": "long"}, "schema_version": {"type": "integer"},
        "session_generation": {"type": "integer"}, "created_at": {"type": "date"},
        "deleted": {"type": "boolean"}, "semantic_ready": {"type": "boolean"}})
    for field in ("title", "content_text"):
        props[field] = {"type": "text", "analyzer": "tf_text", "index_options": "offsets"}
    props["symbols"] = {"type": "keyword", "normalizer": "tf_lower", "fields": {
        "parts": {"type": "text", "analyzer": "tf_symbol_index", "search_analyzer": "tf_symbol_search"}}}
    if dimension:
        props["semantic_passages"] = {"type": "nested", "properties": {
            **{k: {"type": "integer"} for k in ("chunk_no", "start_char", "end_char")},
            "vector": {"type": "dense_vector", "dims": dimension, "index": True,
                       "similarity": "cosine", "index_options": {"type": "int8_hnsw"}}}}
    return {"settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "2s",
        "analysis": {"analyzer": {
            "tf_text": {"type": "custom", "tokenizer": "standard", "filter": ["cjk_width", "lowercase", "cjk_bigram"]},
            "tf_symbol_index": {"type": "custom", "tokenizer": "keyword", "filter": ["tf_symbol_parts", "lowercase", "flatten_graph"]},
            "tf_symbol_search": {"type": "custom", "tokenizer": "keyword", "filter": ["tf_symbol_parts", "lowercase"]}},
            "filter": {"tf_symbol_parts": {"type": "word_delimiter_graph", "preserve_original": True}},
            "normalizer": {"tf_lower": {"type": "custom", "filter": ["lowercase"]}}}},
        "mappings": {"dynamic": "strict", "properties": props}}


def scope_filters(workspaces, *, kind="all", task_id=None, role=None, date_from=None, date_to=None):
    filters = [{"term": {"deleted": False}}, {"terms": {"workspace_id": list(workspaces)}}]
    if kind != "all":
        filters.append({"term": {"kind": kind}})
    if task_id:
        filters.append({"term": {"task_id": task_id}})
    if role:
        filters.append({"bool": {"should": [{"term": {"kind": "task"}}, {"term": {"role": role}}], "minimum_should_match": 1}})
    if date_from or date_to:
        filters.append({"range": {"created_at": {**({"gte": date_from} if date_from else {}), **({"lt": date_to} if date_to else {})}}})
    return filters


def search_body(query, filters, vector=None, profile_id=None):
    bm25 = {"bool": {"filter": deepcopy(filters), "minimum_should_match": 1, "should": [
        {"multi_match": {"query": query, "fields": ["title^4", "content_text", "symbols.parts^2"]}},
        {"term": {"symbols": {"value": query.lower(), "boost": 6}}}]}}
    body = {"size": 200, "timeout": "900ms", "_source": ["entity_key", "kind", "source_version", "projection_hash", "workspace_id", "task_id", "message_id"]}
    if vector is None:
        body["query"] = bm25
        body["highlight"] = {"type": "unified", "encoder": "html", "pre_tags": ["\ue000"], "post_tags": ["\ue001"],
            "fields": {"title": {"number_of_fragments": 1, "fragment_size": 160}, "content_text": {"number_of_fragments": 1, "fragment_size": 240}}}
    else:
        body["knn"] = {"field": "semantic_passages.vector", "query_vector": vector,
            "k": 200, "num_candidates": 1000, "filter": deepcopy(filters) + [
                {"term": {"semantic_ready": True}}, {"term": {"embedding_profile_id": profile_id}}],
            "inner_hits": {"size": 1, "_source": False, "fields": ["semantic_passages.start_char", "semantic_passages.end_char"]}}
    return body


async def bulk_write(client, target, documents):
    """Return per-entity success; verify 409 identity, never accept HTTP 200 blindly."""
    import json
    operations = []
    for doc in documents:
        phase = int(bool(doc.get("deleted") or doc.get("semantic_ready")))
        operations.extend([{"index": {"_index": target, "_id": doc["entity_key"],
            "version": es_version(doc["source_version"], phase), "version_type": "external"}}, doc])
    if len(json.dumps(operations, ensure_ascii=False).encode()) > 8 * 1024 * 1024:
        raise ValueError("SEARCH_DOCUMENT_TOO_LARGE")
    response = await client.bulk(operations=operations)
    results = {}
    for doc, item in zip(documents, response["items"], strict=True):
        status = item["index"]["status"]
        if status == 409:
            current = await client.get(index=target, id=doc["entity_key"], source_excludes=["semantic_passages.vector"])
            actual = current["_source"]
            expected = es_version(doc["source_version"], int(bool(doc.get("deleted") or doc.get("semantic_ready"))))
            ok = current["_version"] > expected
            if current["_version"] == expected:
                fields = ("entity_key", "source_version", "deleted") if doc.get("deleted") else ("entity_key", "source_version", "projection_hash", "embedding_profile_id", "embedding_input_hash")
                ok = all(actual.get(k) == doc.get(k) for k in fields)
                if doc.get("deleted"):
                    ok = ok and not any(k in actual for k in ("content_text", "title", "symbols", "semantic_passages"))
            results[doc["entity_key"]] = None if ok else "SEARCH_VERSION_IDENTITY_MISMATCH"
        else:
            results[doc["entity_key"]] = None if 200 <= status < 300 else f"SEARCH_BULK_{status}"
    return results
