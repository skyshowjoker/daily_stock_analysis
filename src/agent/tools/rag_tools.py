# -*- coding: utf-8 -*-
"""RAG knowledge-base tools for the Agent framework."""

from src.agent.tools.registry import ToolDefinition, ToolParameter
from src.services.rag_service import RagService


def _handle_search_investment_knowledge(query: str, top_k: int = 5, tags: str = "") -> dict:
    """Search investment knowledge and user preference chunks."""
    tag_list = [item.strip() for item in str(tags or "").split(",") if item.strip()]
    return RagService().search(query, top_k=top_k, tags=tag_list)


def _handle_get_investment_knowledge_stats() -> dict:
    """Return knowledge-base health and coverage stats."""
    return RagService().stats()


search_investment_knowledge_tool = ToolDefinition(
    name="search_investment_knowledge",
    description=(
        "Search the local RAG knowledge base for investment principles, user preferences, "
        "article/book/news notes, risk rules, and prior research. Use this before making "
        "personalized investment suggestions or when the user asks to apply stored preferences."
    ),
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="Natural-language retrieval query, e.g. '我的仓位偏好和止损纪律'",
        ),
        ToolParameter(
            name="top_k",
            type="integer",
            description="Maximum chunks to return (1-30)",
            required=False,
            default=5,
        ),
        ToolParameter(
            name="tags",
            type="string",
            description="Optional comma-separated tag filter, e.g. 'preference,risk'",
            required=False,
            default="",
        ),
    ],
    handler=_handle_search_investment_knowledge,
    category="search",
)


get_investment_knowledge_stats_tool = ToolDefinition(
    name="get_investment_knowledge_stats",
    description="Inspect local RAG knowledge-base document/chunk counts and retrieval mode.",
    parameters=[],
    handler=_handle_get_investment_knowledge_stats,
    category="data",
)


ALL_RAG_TOOLS = [
    search_investment_knowledge_tool,
    get_investment_knowledge_stats_tool,
]
