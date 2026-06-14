from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import rag as rag_endpoint
from src.services.rag_enrichment import RagEnrichment
from src.services.rag_service import RagService
from src.storage import DatabaseManager


class _FakeEmbeddingService:
    is_available = True
    model = "test/semantic-v1"
    batch_size = 32

    def embed_texts(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _client_with_service(monkeypatch, tmp_path, embedding_service=None):
    DatabaseManager.reset_instance()
    db_url = f"sqlite:///{tmp_path / 'rag_api.db'}"
    monkeypatch.setattr(
        rag_endpoint,
        "RagService",
        lambda: RagService(
            DatabaseManager(db_url=db_url),
            embedding_service=embedding_service,
        ),
    )
    app = FastAPI()
    app.include_router(rag_endpoint.router, prefix="/api/v1/rag")
    return TestClient(app)


def teardown_function():
    DatabaseManager.reset_instance()


def test_rag_api_ingests_searches_lists_and_deletes(monkeypatch, tmp_path):
    client = _client_with_service(monkeypatch, tmp_path)

    create_response = client.post(
        "/api/v1/rag/documents",
        json={
            "title": "风险偏好",
            "content": "偏好低杠杆和稳定现金流。单笔亏损达到百分之八时重新评估。",
            "source_type": "preference",
            "tags": ["preference", "risk"],
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["duplicate"] is False
    assert created["chunk_count"] >= 1
    assert created["source_type"] == "preference"
    assert created["tags"] == ["preference", "risk"]

    search_response = client.post(
        "/api/v1/rag/search",
        json={"query": "亏损 风险", "top_k": 5, "tags": ["preference"]},
    )
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload["results"]
    assert search_payload["results"][0]["document_id"] == created["document_id"]

    list_response = client.get("/api/v1/rag/documents")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    delete_response = client.delete(f"/api/v1/rag/documents/{created['document_id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] == 1

    empty_response = client.get("/api/v1/rag/documents")
    assert empty_response.status_code == 200
    assert empty_response.json()["total"] == 0


def test_rag_api_uploads_and_auto_enriches_document(monkeypatch, tmp_path):
    client = _client_with_service(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.services.rag_service.enrich_rag_document",
        lambda **kwargs: RagEnrichment(
            summary="文档总结了现金流与风险纪律。",
            source_type="note",
            tags=["现金流", "风险管理"],
            method="local",
        ),
    )

    response = client.post(
        "/api/v1/rag/documents/upload",
        files={
            "file": (
                "research.txt",
                "投资研究笔记\n\n关注自由现金流，并控制组合回撤。".encode("utf-8"),
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "投资研究笔记"
    assert payload["summary"] == "文档总结了现金流与风险纪律。"
    assert payload["source_type"] == "note"
    assert payload["tags"] == ["现金流", "风险管理"]
    assert payload["parser"] == "plain-text"

    listing = client.get("/api/v1/rag/documents").json()
    assert listing["items"][0]["summary"] == payload["summary"]


def test_rag_api_rejects_unsupported_upload(monkeypatch, tmp_path):
    client = _client_with_service(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/rag/documents/upload",
        files={"file": ("archive.zip", b"not-a-document", "application/zip")},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["error"] == "unsupported_file_type"


def test_rag_api_rebuilds_semantic_index(monkeypatch, tmp_path):
    client = _client_with_service(
        monkeypatch,
        tmp_path,
        embedding_service=_FakeEmbeddingService(),
    )
    created = client.post(
        "/api/v1/rag/documents",
        json={
            "title": "语义检索材料",
            "content": "企业拥有稳定的自由现金流与持续提价能力。",
            "source_type": "article",
        },
    )
    assert created.status_code == 200

    response = client.post(
        "/api/v1/rag/embeddings/rebuild",
        json={"force": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["embedding_model"] == "test/semantic-v1"
    assert payload["updated_chunks"] == 1

    stats = client.get("/api/v1/rag/stats").json()
    assert stats["semantic_enabled"] is True
    assert stats["embedding_coverage_pct"] == 100.0
