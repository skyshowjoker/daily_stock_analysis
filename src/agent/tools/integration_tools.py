# -*- coding: utf-8 -*-
"""Agent tools for inspecting optional financial-services integrations."""

from src.agent.tools.registry import ToolDefinition
from src.services.financial_services_integration import (
    build_financial_services_capability_catalog,
)


def _handle_get_financial_services_capabilities() -> dict:
    """Return the real local/external capability boundary for research workflows."""
    from src.agent.factory import get_tool_registry

    registry = get_tool_registry()
    available_tools = [
        name
        for name in registry.list_names()
        if name != "get_financial_services_capabilities"
    ]
    return build_financial_services_capability_catalog(available_tools)


get_financial_services_capabilities_tool = ToolDefinition(
    name="get_financial_services_capabilities",
    description=(
        "Inspect which financial research services and tools are actually available. "
        "Use this before a workflow needs licensed external data, Office artifacts, "
        "or other optional integrations; never assume unavailable services exist."
    ),
    parameters=[],
    handler=_handle_get_financial_services_capabilities,
    category="data",
)


ALL_INTEGRATION_TOOLS = [get_financial_services_capabilities_tool]
