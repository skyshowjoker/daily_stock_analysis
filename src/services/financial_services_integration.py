# -*- coding: utf-8 -*-
"""Capability mapping for Anthropic financial-services style workflows."""

from __future__ import annotations

from typing import Any, Dict, List


_LOCAL_CAPABILITIES = (
    {
        "id": "market_data",
        "name": "Market data and fundamentals",
        "tools": ["get_realtime_quote", "get_daily_history", "get_stock_info", "get_capital_flow"],
        "description": "Quotes, OHLCV, valuation, fundamentals, capital flow, and chip distribution.",
    },
    {
        "id": "research_intelligence",
        "name": "Research intelligence",
        "tools": ["search_stock_news", "search_comprehensive_intel"],
        "description": "News, earnings outlook, industry trends, catalysts, and risk searches.",
    },
    {
        "id": "technical_analysis",
        "name": "Technical analysis",
        "tools": ["analyze_trend", "calculate_ma", "get_volume_analysis", "analyze_pattern"],
        "description": "Trend, moving-average, volume, support/resistance, and pattern analysis.",
    },
    {
        "id": "portfolio_and_backtest",
        "name": "Portfolio and backtest",
        "tools": ["get_portfolio_snapshot", "get_stock_backtest_summary", "get_skill_backtest_summary"],
        "description": "Portfolio context and historical analysis-performance summaries.",
    },
)

_EXTERNAL_BOUNDARIES = (
    {
        "id": "licensed_financial_mcp",
        "name": "Licensed financial-data MCP connectors",
        "status": "not_integrated",
        "reason": "The upstream connectors require separate vendor subscriptions, credentials, and MCP runtimes.",
    },
    {
        "id": "office_artifact_plugins",
        "name": "Spreadsheet, document, and presentation plugins",
        "status": "not_integrated",
        "reason": "The server Agent runtime currently produces reports, but does not expose Office artifact plugins as Agent tools.",
    },
    {
        "id": "managed_agent_orchestration",
        "name": "Managed multi-agent workflows",
        "status": "adapted",
        "reason": "DSA uses its own decision, technical, intelligence, risk, and portfolio agents instead of upstream managed agents.",
    },
)


def build_financial_services_capability_catalog(available_tools: List[str]) -> Dict[str, Any]:
    """Map upstream-style financial workflows onto real DSA runtime capabilities."""
    available = set(available_tools)
    local = []
    for capability in _LOCAL_CAPABILITIES:
        configured_tools = list(capability["tools"])
        active_tools = [name for name in configured_tools if name in available]
        missing_tools = [name for name in configured_tools if name not in available]
        local.append(
            {
                **capability,
                "status": "available" if active_tools and not missing_tools else "partial",
                "available_tools": active_tools,
                "missing_tools": missing_tools,
            }
        )

    return {
        "integration": "anthropics/financial-services-adapter",
        "mode": "native_dsa_tools",
        "availability_scope": "registered_tools",
        "local_capabilities": local,
        "external_boundaries": list(_EXTERNAL_BOUNDARIES),
        "guidance": (
            "Registered tools may still report missing credentials or unavailable data at call time. "
            "Use available_tools for analysis, preserve their runtime errors, and treat external_boundaries "
            "marked not_integrated as unavailable. Never invent licensed data or Office artifacts."
        ),
    }
