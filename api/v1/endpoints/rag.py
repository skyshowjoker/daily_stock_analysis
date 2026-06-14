# -*- coding: utf-8 -*-
"""Investment RAG knowledge-base endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from api.v1.errors import api_error
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.rag import (
    RagDeleteResponse,
    RagDocumentCreateRequest,
    RagDocumentCreateResponse,
    RagDocumentDetail,
    RagDocumentListResponse,
    RagEmbeddingRebuildRequest,
    RagEmbeddingRebuildResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagStatsResponse,
)
from src.services.document_parser import (
    DocumentParseError,
    DocumentTooLargeError,
    UnsupportedDocumentError,
)
from src.services.rag_service import RagService

logger = logging.getLogger(__name__)
router = APIRouter()


def _bad_request(exc: Exception) -> HTTPException:
    return api_error(400, "validation_error", str(exc))


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return api_error(500, "internal_error", message)


@router.post(
    "/documents",
    response_model=RagDocumentCreateResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Ingest investment knowledge",
)
def create_document(request: RagDocumentCreateRequest) -> RagDocumentCreateResponse:
    try:
        result = RagService().ingest_document(
            title=request.title,
            content=request.content,
            source_type=request.source_type,
            source_uri=request.source_uri or "",
            author=request.author or "",
            published_at=request.published_at,
            tags=request.tags,
            metadata=request.metadata,
            replace_existing=request.replace_existing,
        )
        return RagDocumentCreateResponse(**result.__dict__)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Knowledge ingestion failed", exc)


@router.post(
    "/documents/upload",
    response_model=RagDocumentCreateResponse,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Upload and automatically process an investment document",
)
async def upload_document(
    file: UploadFile = File(..., description="PDF, DOC, DOCX, TXT, Markdown, RTF, HTML or ODT document"),
) -> RagDocumentCreateResponse:
    service = RagService()
    filename = (file.filename or "").strip()
    if not filename:
        raise api_error(400, "validation_error", "请选择要上传的文档")

    try:
        data = await file.read(service.max_upload_bytes + 1)
    except Exception as exc:
        raise _internal_error("读取上传文档失败", exc)
    finally:
        await file.close()

    if len(data) > service.max_upload_bytes:
        raise api_error(
            413,
            "file_too_large",
            f"文件超过 {service.max_upload_bytes // (1024 * 1024)}MB 限制",
        )

    try:
        result = await run_in_threadpool(
            service.ingest_file,
            data=data,
            filename=filename,
            content_type=file.content_type or "",
        )
        return RagDocumentCreateResponse(**result.__dict__)
    except DocumentTooLargeError as exc:
        raise api_error(413, "file_too_large", str(exc))
    except UnsupportedDocumentError as exc:
        raise api_error(415, "unsupported_file_type", str(exc))
    except DocumentParseError as exc:
        raise _bad_request(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("文档解析与入库失败", exc)


@router.get(
    "/documents",
    response_model=RagDocumentListResponse,
    responses={500: {"model": ErrorResponse}},
    summary="List knowledge documents",
)
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_type: str = Query(""),
    query: str = Query(""),
) -> RagDocumentListResponse:
    try:
        return RagDocumentListResponse(**RagService().list_documents(
            page=page,
            page_size=page_size,
            source_type=source_type,
            query=query,
        ))
    except Exception as exc:
        raise _internal_error("List knowledge documents failed", exc)


@router.get(
    "/documents/{document_id}",
    response_model=RagDocumentDetail,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get knowledge document",
)
def get_document(document_id: int) -> RagDocumentDetail:
    try:
        payload = RagService().get_document(document_id, include_chunks=True)
        if payload is None:
            raise api_error(404, "not_found", f"Knowledge document not found: {document_id}")
        return RagDocumentDetail(**payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _internal_error("Get knowledge document failed", exc)


@router.delete(
    "/documents/{document_id}",
    response_model=RagDeleteResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Delete knowledge document",
)
def delete_document(document_id: int) -> RagDeleteResponse:
    try:
        deleted = RagService().delete_document(document_id)
        if not deleted:
            raise api_error(404, "not_found", f"Knowledge document not found: {document_id}")
        return RagDeleteResponse(deleted=1)
    except HTTPException:
        raise
    except Exception as exc:
        raise _internal_error("Delete knowledge document failed", exc)


@router.post(
    "/search",
    response_model=RagSearchResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Retrieve investment knowledge",
)
def search_knowledge(request: RagSearchRequest) -> RagSearchResponse:
    try:
        return RagSearchResponse(**RagService().search(
            request.query,
            top_k=request.top_k,
            tags=request.tags,
        ))
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Knowledge search failed", exc)


@router.post(
    "/embeddings/rebuild",
    response_model=RagEmbeddingRebuildResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Build or refresh semantic embeddings",
)
def rebuild_embeddings(
    request: RagEmbeddingRebuildRequest,
) -> RagEmbeddingRebuildResponse:
    try:
        result = RagService().rebuild_embeddings(
            document_id=request.document_id,
            force=request.force,
        )
        return RagEmbeddingRebuildResponse(**result.__dict__)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Semantic index rebuild failed", exc)


@router.get(
    "/stats",
    response_model=RagStatsResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get RAG knowledge-base stats",
)
def get_stats() -> RagStatsResponse:
    try:
        return RagStatsResponse(**RagService().stats())
    except Exception as exc:
        raise _internal_error("Get knowledge stats failed", exc)
