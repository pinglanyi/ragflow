"""Tool system: register all tools with the registry on import."""

from rag.advanced_rag.harness.tools.registry import (
    _inspector_schema,
    _navigate_schema,
    _search_schema,
    register_tool,
)

# Register tools
# Search tools
from rag.advanced_rag.harness.tools.search import (
    bm25_search,
    hybrid_search,
    structured_query,
    vector_search,
    web_search,
)

register_tool("hybrid_search", _search_schema("hybrid_search", "Embedding + Keywords search"), hybrid_search)
register_tool("vector_search", _search_schema("vector_search", "Embedding search"), vector_search)
register_tool("bm25_search", _search_schema("bm25_search", "Keywords search"), bm25_search)
register_tool("web_search", _search_schema("web_search", "Internet search"), web_search)
register_tool("structured_query", _search_schema("structured_query", "SQL search"), structured_query)

# Navigation tools (require compilation)
from rag.advanced_rag.harness.tools.navigation import (
    catalog_navigate,
    dataset_navigate,
    mindmap_navigate,
)

# catalog_navigate covers both the tree/TOC outline and the page index.
register_tool(
    "catalog_navigate",
    _navigate_schema("catalog_navigate", "Answer from the document's compiled catalog (table of contents / page index)"),
    catalog_navigate,
    requires_compilation=True,
    compilation_type=("toc", "page_index"),
)
register_tool("mindmap_navigate", _navigate_schema("mindmap_navigate", "Navigate by mindmap"), mindmap_navigate, requires_compilation=True, compilation_type="mindmap")
register_tool(
    "dataset_navigate",
    _navigate_schema("dataset_navigate", "Find the most relevant documents via the dataset map, then search within them"),
    dataset_navigate,
    requires_compilation=True,
    compilation_type="tree",
)

# Exploration tools (require compilation)
from rag.advanced_rag.harness.tools.exploration import graph_explore, wiki_query

register_tool("graph_explore", _search_schema("graph_explore", "Knowledge graph exploration"), graph_explore, requires_compilation=True, compilation_type="knowledge_graph")
register_tool("wiki_query", _search_schema("wiki_query", "Wiki search"), wiki_query, requires_compilation=True, compilation_type="wiki")

# Inspector tools read the indexed MLLM Markdown and preserve source metadata.
from rag.advanced_rag.harness.tools.inspector import (
    compare_sources,
    grep_within,
    open_context,
    read_document,
    request_adjacent,
)

register_tool(
    "inspector_open_context",
    _inspector_schema(
        "inspector_open_context",
        "Read source context on both sides of a known chunk, up to 20 whole chunks each side",
        {"chunk_id": {"type": "string"}, "width": {"type": "integer", "minimum": 1, "maximum": 20000, "default": 500}},
        ["chunk_id"],
    ),
    open_context,
)
register_tool("inspector_compare", _inspector_schema("inspector_compare", "Compare previously retrieved chunks", {"chunk_ids": {"type": "array", "items": {"type": "string"}}}), compare_sources)
register_tool(
    "inspector_grep_within",
    _inspector_schema(
        "inspector_grep_within",
        "Scan indexed document Markdown for literal phrase or all whitespace-separated terms; no regex or cross-chunk matching",
        {
            "doc_id": {"type": "string"},
            "pattern": {"type": "string", "maxLength": 1000},
            "mode": {"type": "string", "enum": ["phrase", "term"], "default": "phrase"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        },
        ["doc_id", "pattern"],
    ),
    grep_within,
)
register_tool(
    "inspector_request_adjacent",
    _inspector_schema(
        "inspector_request_adjacent",
        "Read previous/next source chunks in the anchor's document, including unseen chunks",
        {"chunk_id": {"type": "string"}, "direction": {"type": "string", "enum": ["prev", "next"], "default": "next"}, "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 3}},
        ["chunk_id"],
    ),
    request_adjacent,
)
register_tool(
    "inspector_read_document",
    _inspector_schema(
        "inspector_read_document",
        "Read a range by zero-based visible chunk ordinal, not page or character offset; source coordinates required",
        {"doc_id": {"type": "string"}, "start": {"type": "integer", "minimum": 0, "maximum": 9999, "default": 0}, "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
        ["doc_id"],
    ),
    read_document,
)

# Built-in agent tools
# (generate_report and think_tool are handled by the agent loop itself, not by Pipeline)
