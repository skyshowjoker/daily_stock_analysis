from src.services.rag_service import RagService
from src.storage import DatabaseManager


def _fresh_service() -> RagService:
    DatabaseManager.reset_instance()
    return RagService(DatabaseManager(db_url="sqlite:///:memory:"))


def teardown_function():
    DatabaseManager.reset_instance()


def test_ingest_chunks_deduplicates_and_retrieves_chinese_content():
    service = _fresh_service()
    content = (
        "我的投资偏好是优先选择现金流稳定、负债率较低的公司。\n\n"
        "风险纪律：单笔交易亏损达到百分之八时必须重新评估，不追高。"
    )

    first = service.ingest_document(
        title="个人投资纪律",
        content=content,
        source_type="preference",
        tags=["preference", "risk"],
    )
    duplicate = service.ingest_document(
        title="重复内容",
        content=content,
        source_type="note",
    )

    assert first.chunk_count >= 1
    assert duplicate.duplicate is True
    assert duplicate.document_id == first.document_id

    result = service.search("我的止损风险纪律", top_k=5)
    assert result["results"]
    assert result["results"][0]["document_id"] == first.document_id
    assert "风险纪律" in result["results"][0]["content"]


def test_document_list_detail_delete_and_stats():
    service = _fresh_service()
    created = service.ingest_document(
        title="价值投资摘录",
        content="安全边际来自价格显著低于保守估值。长期回报取决于企业质量与买入价格。",
        source_type="book",
        source_uri="book://value-investing",
        tags=["valuation"],
    )

    listing = service.list_documents()
    assert listing["total"] == 1
    assert listing["items"][0]["source_type"] == "book"

    detail = service.get_document(created.document_id, include_chunks=True)
    assert detail is not None
    assert detail["chunks"]
    assert service.stats()["document_count"] == 1

    assert service.delete_document(created.document_id) is True
    assert service.get_document(created.document_id) is None
    assert service.stats()["document_count"] == 0


def test_agent_rag_tools_are_registered():
    from src.agent.factory import get_tool_registry

    registry = get_tool_registry()
    assert "search_investment_knowledge" in registry.list_names()
    assert "get_investment_knowledge_stats" in registry.list_names()
