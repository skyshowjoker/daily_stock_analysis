# -*- coding: utf-8 -*-
"""RAG knowledge-base API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


RagSourceType = Literal["article", "news", "book", "note", "preference", "url", "other"]


class RagDocumentCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=1_000_000)
    source_type: RagSourceType = "article"
    source_uri: Optional[str] = Field(None, max_length=1000)
    author: Optional[str] = Field(None, max_length=128)
    published_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list, max_length=20)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    replace_existing: bool = False


class RagDocumentItem(BaseModel):
    id: int
    title: str
    source_type: str
    source_uri: str = ""
    author: str = ""
    published_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    status: str
    chunk_count: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RagDocumentCreateResponse(BaseModel):
    document_id: int
    title: str
    chunk_count: int
    duplicate: bool = False
    summary: str = ""
    source_type: str = "other"
    tags: List[str] = Field(default_factory=list)
    enrichment_method: str = ""
    parser: str = ""


class RagDocumentListResponse(BaseModel):
    items: List[RagDocumentItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class RagChunkItem(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    content: str
    char_count: int
    token_estimate: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RagDocumentDetail(RagDocumentItem):
    chunks: List[RagChunkItem] = Field(default_factory=list)


class RagSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(8, ge=1, le=30)
    tags: List[str] = Field(default_factory=list, max_length=20)


class RagSearchResultItem(BaseModel):
    chunk_id: int
    document_id: int
    chunk_index: int
    title: str
    source_type: str
    source_uri: str = ""
    tags: List[str] = Field(default_factory=list)
    content: str
    score: float
    retrieval: str
    score_components: Dict[str, float] = Field(default_factory=dict)
    created_at: Optional[str] = None


class RagSearchResponse(BaseModel):
    query: str
    top_k: int
    results: List[RagSearchResultItem] = Field(default_factory=list)
    retrieval_mode: str


class RagStatsResponse(BaseModel):
    document_count: int
    chunk_count: int
    chunk_size: int
    chunk_overlap: int
    retrieval_mode: str
    by_source_type: Dict[str, int] = Field(default_factory=dict)
    supported_extensions: List[str] = Field(default_factory=list)
    max_upload_mb: int = 20
    auto_enrichment: bool = True
    semantic_enabled: bool = False
    embedding_model: str = ""
    embedded_chunk_count: int = 0
    embedding_coverage_pct: float = 0.0


class RagEmbeddingRebuildRequest(BaseModel):
    document_id: Optional[int] = Field(None, ge=1)
    force: bool = False


class RagEmbeddingRebuildResponse(BaseModel):
    enabled: bool
    embedding_model: str
    updated_chunks: int
    skipped_chunks: int
    failed_chunks: int
    error: str = ""


class RagDeleteResponse(BaseModel):
    deleted: int
