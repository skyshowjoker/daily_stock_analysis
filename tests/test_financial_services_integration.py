from src.services.financial_services_integration import (
    build_financial_services_capability_catalog,
)


def test_capability_catalog_marks_real_tools_and_external_boundaries():
    catalog = build_financial_services_capability_catalog(
        ["get_realtime_quote", "get_daily_history", "get_stock_info"]
    )

    assert catalog["mode"] == "native_dsa_tools"
    market_data = next(
        item for item in catalog["local_capabilities"] if item["id"] == "market_data"
    )
    assert market_data["status"] == "partial"
    assert "get_realtime_quote" in market_data["available_tools"]
    assert "get_capital_flow" in market_data["missing_tools"]
    assert any(
        item["id"] == "licensed_financial_mcp"
        and item["status"] == "not_integrated"
        for item in catalog["external_boundaries"]
    )


def test_financial_research_skill_bundles_load():
    from src.agent.skills.base import load_skills_from_directory

    skills = load_skills_from_directory("strategies/financial_research")
    names = {skill.name for skill in skills}

    assert {
        "earnings_analysis",
        "investment_thesis",
        "catalyst_calendar",
        "comparable_analysis",
    } <= names
    assert all("get_financial_services_capabilities" in skill.instructions for skill in skills)
