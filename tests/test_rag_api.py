from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import rag as rag_endpoint
from src.services.rag_service import RagService
from src.storage import DatabaseManager


def _client_with_service(monkeypatch, tmp_path):
    DatabaseManager.reset_instance()
    db_url = f"sqlite:///{tmp_path / 'rag_api.db'}"
    monkeypatch.setattr(rag_endpoint, "RagService", lambda: RagService(DatabaseManager(db_url=db_url)))
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
