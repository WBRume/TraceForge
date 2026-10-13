"""Physical search partitions and retrieval policy, versioned independently of sources."""

SCHEMA_VERSION = 2
CORPORA = {"history": ("task", "message"), "knowledge": ("case", "playbook")}


def corpus_for(kind):
    for corpus, kinds in CORPORA.items():
        if kind in kinds:
            return corpus
    raise ValueError("SEARCH_INVALID_KIND")


def corpora_for(kind="all"):
    return tuple(CORPORA) if kind == "all" else (corpus_for(kind),)


def partitioned(target):
    return target.get("schema_version", 1) >= SCHEMA_VERSION


def physical_indices(target, kind="all"):
    name = target["physical_index"]
    return [f"{name}-{corpus}" for corpus in corpora_for(kind)] if partitioned(target) else [name]


def write_index(target, kind):
    return physical_indices(target, kind)[0]


def semantic_enabled(target, kind):
    return not partitioned(target) or kind == "all" or corpus_for(kind) == "knowledge"
