from src.services.rag_service import RagService
from src.storage import DatabaseManager


class _FakeEmbeddingService:
    is_available = True
    model = "test/semantic-v1"
    batch_size = 32

    def embed_texts(self, texts):
        vectors = []
        for text in texts:
            if "护城河" in text or "持续提价能力" in text:
                vectors.append([1.0, 0.0, 0.0])
            elif "周期库存" in text:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


class _UnavailableAdapter:
    is_available = False


class _UnexpectedAdapter:
    is_available = True

    def call_text(self, *args, **kwargs):
        raise AssertionError("duplicate upload should skip LLM enrichment")


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


def test_semantic_retrieval_recalls_content_without_keyword_overlap():
    DatabaseManager.reset_instance()
    service = RagService(
        DatabaseManager(db_url="sqlite:///:memory:"),
        embedding_service=_FakeEmbeddingService(),
    )
    target = service.ingest_document(
        title="消费品牌研究",
        content="企业拥有持续提价能力，客户仍保持较高复购率。",
        source_type="article",
    )
    service.ingest_document(
        title="周期行业跟踪",
        content="周期库存处于高位，价格可能继续承压。",
        source_type="article",
    )

    result = service.search("这家公司是否具备护城河", top_k=2)

    assert result["retrieval_mode"] == "hybrid_semantic_fts_lexical"
    assert result["results"][0]["document_id"] == target.document_id
    assert "semantic" in result["results"][0]["retrieval"]
    assert "semantic" in result["results"][0]["score_components"]


def test_rebuild_embeddings_backfills_existing_chunks():
    service = _fresh_service()
    service.ingest_document(
        title="消费品牌研究",
        content="企业拥有持续提价能力，客户仍保持较高复购率。",
        source_type="article",
    )
    semantic_service = RagService(
        service.db,
        embedding_service=_FakeEmbeddingService(),
    )

    before = semantic_service.stats()
    rebuilt = semantic_service.rebuild_embeddings()
    after = semantic_service.stats()

    assert before["embedded_chunk_count"] == 0
    assert rebuilt.updated_chunks == 1
    assert rebuilt.failed_chunks == 0
    assert after["embedded_chunk_count"] == 1
    assert after["embedding_coverage_pct"] == 100.0


def test_ingest_file_auto_enriches_and_preserves_trace_metadata():
    service = _fresh_service()
    created = service.ingest_file(
        data=(
            "我的投资偏好\n\n优先选择现金流稳定、负债率较低的公司，"
            "并严格执行止损纪律。"
        ).encode("utf-8"),
        filename="investment-preference.txt",
        content_type="text/plain",
        llm_adapter=_UnavailableAdapter(),
    )

    assert created.source_type == "preference"
    assert created.summary
    assert created.tags
    assert created.parser == "plain-text"

    detail = service.get_document(created.document_id)
    assert detail is not None
    assert detail["summary"] == created.summary
    assert detail["metadata"]["file_name"] == "investment-preference.txt"
    assert detail["metadata"]["auto_classified"] is True
    assert detail["source_uri"] == "upload://investment-preference.txt"

    stats = service.stats()
    assert ".pdf" in stats["supported_extensions"]
    assert stats["max_upload_mb"] == 20
    assert stats["auto_enrichment"] is True


def test_duplicate_file_skips_enrichment_before_ingest():
    service = _fresh_service()
    data = "重复材料\n\n关注现金流与风险纪律。".encode("utf-8")
    first = service.ingest_file(
        data=data,
        filename="first.txt",
        content_type="text/plain",
        llm_adapter=_UnavailableAdapter(),
    )
    duplicate = service.ingest_file(
        data=data,
        filename="duplicate.txt",
        content_type="text/plain",
        llm_adapter=_UnexpectedAdapter(),
    )

    assert duplicate.duplicate is True
    assert duplicate.document_id == first.document_id


def test_agent_rag_tools_are_registered():
    from src.agent.factory import get_tool_registry

    registry = get_tool_registry()
    assert "search_investment_knowledge" in registry.list_names()
    assert "get_investment_knowledge_stats" in registry.list_names()
