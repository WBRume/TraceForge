"""Cosine cutoffs for the default BGE-M3 retrieval space."""

import re
import unicodedata

_QUERY_PARTS = re.compile(r"[\u3400-\u9fff]+|[^\W_]+")
_HAN = re.compile(r"[\u3400-\u9fff]")


def minimum_semantic_similarity(query: str) -> float:
    """Require stronger semantic evidence for short phrases and single terms."""
    parts = _QUERY_PARTS.findall(unicodedata.normalize("NFKC", query))
    if len(parts) <= 1 and not any(_HAN.search(part) and len(part) > 4 for part in parts):
        return 0.70
    return 0.58
