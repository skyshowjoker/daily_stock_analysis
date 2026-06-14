# -*- coding: utf-8 -*-
"""Local RAG knowledge base for investment knowledge and preferences."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, or_, select, text

from src.services.document_parser import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    ParsedDocument,
    parse_uploaded_document,
)
from src.services.rag_enrichment import RagEnrichment, enrich_rag_document
from src.services.rag_embedding_service import (
    RagEmbeddingError,
    RagEmbeddingService,
)
from src.storage import DatabaseManager, RagChunk, RagDocument

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 1200
_DEFAULT_CHUNK_OVERLAP = 180
_DEFAULT_TOP_K = 8
_DEFAULT_SEMANTIC_SCAN_LIMIT = 20_000
_MAX_CONTENT_CHARS = 1_000_000
_SOURCE_TYPES = {"article", "news", "book", "note", "preference", "url", "other"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_.$%-]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class RagIngestResult:
    document_id: int
    title: str
    chunk_count: int
    duplicate: bool = False
    summary: str = ""
    source_type: str = "other"
    tags: tuple[str, ...] = ()
    enrichment_method: str = ""
    parser: str = ""


@dataclass(frozen=True)
class RagEmbeddingRebuildResult:
    enabled: bool
    embedding_model: str
    updated_chunks: int
    skipped_chunks: int
    failed_chunks: int
    error: str = ""


class RagService:
    """RAG document ingestion and retrieval service.

    Retrieval combines provider embeddings, SQLite FTS5/BM25 and a lexical
    fallback for Chinese text. Semantic retrieval is enabled only when an
    embedding model is explicitly configured.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        embedding_service: Optional[RagEmbeddingService] = None,
    ):
        self.db = db_manager or DatabaseManager.get_instance()
        self.embedding_service = embedding_service or RagEmbeddingService()
        self.chunk_size = self._read_int_env("RAG_CHUNK_SIZE", _DEFAULT_CHUNK_SIZE, 300, 4000)
        self.chunk_overlap = self._read_int_env("RAG_CHUNK_OVERLAP", _DEFAULT_CHUNK_OVERLAP, 0, self.chunk_size // 2)
        self.default_top_k = self._read_int_env("RAG_DEFAULT_TOP_K", _DEFAULT_TOP_K, 1, 30)
        self.semantic_scan_limit = self._read_int_env(
            "RAG_SEMANTIC_SCAN_LIMIT",
            _DEFAULT_SEMANTIC_SCAN_LIMIT,
            100,
            200_000,
        )
        self.max_upload_bytes = MAX_UPLOAD_BYTES
        self._sqlite_available = bool(getattr(self.db, "_is_sqlite_engine", False))
        self._fts_available = self._sqlite_available
        self._ensure_schema_extensions()
        self._ensure_fts_table()

    @staticmethod
    def _read_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _normalize_text(content: str) -> str:
        text_value = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
        text_value = re.sub(r"[ \t]+\n", "\n", text_value)
        text_value = re.sub(r"\n{3,}", "\n\n", text_value)
        return text_value.strip()

    @staticmethod
    def _hash_text(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        raw = value.strip()
        if not raw:
            return None
        try:
            if raw.endswith("Z"):
                raw = f"{raw[:-1]}+00:00"
            return datetime.fromisoformat(raw)
        except ValueError:
            try:
                return datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                return None

    @staticmethod
    def _normalize_tags(tags: Optional[Sequence[str] | str]) -> List[str]:
        if tags is None:
            return []
        if isinstance(tags, str):
            raw_items = tags.split(",")
        else:
            raw_items = list(tags)
        normalized = []
        seen = set()
        for item in raw_items:
            tag = str(item or "").strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            normalized.append(tag[:40])
        return normalized[:20]

    @staticmethod
    def _serialize_json(value: Any) -> str:
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _parse_json(value: Optional[str]) -> Dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _ensure_fts_table(self) -> None:
        if not self._sqlite_available:
            self._fts_available = False
            return
        with self.db.session_scope() as session:
            try:
                session.execute(
                    text(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts
                        USING fts5(
                            chunk_id UNINDEXED,
                            document_id UNINDEXED,
                            title,
                            tags,
                            content,
                            tokenize='unicode61'
                        )
                        """
                    )
                )
                self._fts_available = True
            except Exception as exc:
                self._fts_available = False
                logger.warning("SQLite FTS5 is unavailable; RAG will use lexical retrieval only: %s", exc)

    def _ensure_schema_extensions(self) -> None:
        if not self._sqlite_available:
            return
        with self.db.session_scope() as session:
            existing_columns = {
                row[1]
                for row in session.execute(text("PRAGMA table_info(rag_chunks)")).all()
            }
            optional_columns = {
                "embedding_model": "VARCHAR(128)",
                "embedding_dimensions": "INTEGER",
                "embedding_json": "TEXT",
            }
            for column_name, column_type in optional_columns.items():
                if column_name not in existing_columns:
                    session.execute(text(f"ALTER TABLE rag_chunks ADD COLUMN {column_name} {column_type}"))

    def _chunk_text(self, content: str) -> List[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        if not paragraphs:
            paragraphs = [content]

        chunks: List[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(paragraph) > self.chunk_size:
                if current:
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(self._split_long_block(paragraph))
                continue

            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                chunks.append(current.strip())
                current = self._with_overlap(chunks[-1], paragraph)

        if current:
            chunks.append(current.strip())
        return [chunk for chunk in chunks if chunk.strip()]

    def _split_long_block(self, block: str) -> List[str]:
        parts: List[str] = []
        start = 0
        while start < len(block):
            end = min(len(block), start + self.chunk_size)
            if end < len(block):
                boundary = max(block.rfind("。", start, end), block.rfind(".", start, end), block.rfind("\n", start, end))
                if boundary > start + self.chunk_size * 0.55:
                    end = boundary + 1
            parts.append(block[start:end].strip())
            if end >= len(block):
                break
            start = max(end - self.chunk_overlap, start + 1)
        return parts

    def _with_overlap(self, previous: str, next_block: str) -> str:
        if not previous or self.chunk_overlap <= 0:
            return next_block
        overlap = previous[-self.chunk_overlap:].strip()
        return f"{overlap}\n\n{next_block}".strip() if overlap else next_block

    def ingest_document(
        self,
        *,
        title: str,
        content: str,
        source_type: str = "article",
        source_uri: str = "",
        author: str = "",
        published_at: Optional[str] = None,
        tags: Optional[Sequence[str] | str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replace_existing: bool = False,
    ) -> RagIngestResult:
        normalized_title = str(title or "").strip()[:255]
        normalized_content = self._normalize_text(content)
        if not normalized_title:
            raise ValueError("title is required")
        if not normalized_content:
            raise ValueError("content is required")
        if len(normalized_content) > _MAX_CONTENT_CHARS:
            raise ValueError(f"content exceeds max length {_MAX_CONTENT_CHARS}")

        normalized_source_type = (source_type or "article").strip().lower()
        if normalized_source_type not in _SOURCE_TYPES:
            normalized_source_type = "other"

        normalized_tags = self._normalize_tags(tags)
        normalized_metadata = dict(metadata or {})
        content_hash = self._hash_text(normalized_content)
        chunks = self._chunk_text(normalized_content)
        if not chunks:
            raise ValueError("content produced no chunks")

        existing_payload = self._find_active_document_by_content(normalized_content)
        if existing_payload is not None and not replace_existing:
            return self._ingest_result_from_document(existing_payload)

        embedding_vectors = self._try_embed_chunks(
            title=normalized_title,
            source_type=normalized_source_type,
            tags=normalized_tags,
            chunks=chunks,
        )

        def _write(session):
            existing = session.execute(
                select(RagDocument).where(
                    RagDocument.content_hash == content_hash,
                    RagDocument.status == "active",
                ).limit(1)
            ).scalar_one_or_none()
            if existing is not None and not replace_existing:
                return self._ingest_result_from_document(
                    self._document_to_dict(existing)
                )

            if existing is not None and replace_existing:
                self._delete_document_rows(session, existing.id)

            document = RagDocument(
                title=normalized_title,
                source_type=normalized_source_type,
                source_uri=str(source_uri or "").strip()[:1000],
                author=str(author or "").strip()[:128],
                published_at=self._parse_datetime(published_at),
                tags=",".join(normalized_tags),
                metadata_json=self._serialize_json(normalized_metadata),
                content_hash=content_hash,
                status="active",
                chunk_count=len(chunks),
            )
            session.add(document)
            session.flush()

            for index, chunk in enumerate(chunks):
                row = RagChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=chunk,
                    content_hash=self._hash_text(chunk),
                    char_count=len(chunk),
                    token_estimate=max(1, len(chunk) // 2),
                    embedding_model=(
                        self.embedding_service.model if embedding_vectors else None
                    ),
                    embedding_dimensions=(
                        len(embedding_vectors[index]) if embedding_vectors else None
                    ),
                    embedding_json=(
                        json.dumps(embedding_vectors[index], separators=(",", ":"))
                        if embedding_vectors
                        else None
                    ),
                    metadata_json=self._serialize_json({"overlap_chars": self.chunk_overlap}),
                )
                session.add(row)
                session.flush()
                self._insert_fts_row(session, row, document)

            return RagIngestResult(
                document_id=document.id,
                title=document.title,
                chunk_count=len(chunks),
                duplicate=False,
                summary=str(normalized_metadata.get("summary") or ""),
                source_type=normalized_source_type,
                tags=tuple(normalized_tags),
                enrichment_method=str(normalized_metadata.get("enrichment_method") or ""),
                parser=str(normalized_metadata.get("parser") or ""),
            )

        return self.db._run_write_transaction("rag_ingest_document", _write)

    def _ingest_result_from_document(
        self,
        document: Dict[str, Any],
    ) -> RagIngestResult:
        metadata = document.get("metadata") or {}
        return RagIngestResult(
            document_id=int(document["id"]),
            title=str(document["title"]),
            chunk_count=int(document["chunk_count"]),
            duplicate=True,
            summary=str(metadata.get("summary") or ""),
            source_type=str(document.get("source_type") or "other"),
            tags=tuple(document.get("tags") or []),
            enrichment_method=str(metadata.get("enrichment_method") or ""),
            parser=str(metadata.get("parser") or ""),
        )

    @staticmethod
    def _embedding_input(
        *,
        title: str,
        source_type: str,
        tags: Sequence[str],
        content: str,
    ) -> str:
        context = [
            f"标题：{title}",
            f"类型：{source_type}",
        ]
        if tags:
            context.append(f"标签：{', '.join(tags)}")
        context.append(f"正文：{content}")
        return "\n".join(context)

    def _try_embed_chunks(
        self,
        *,
        title: str,
        source_type: str,
        tags: Sequence[str],
        chunks: Sequence[str],
    ) -> List[List[float]]:
        if not self.embedding_service.is_available:
            return []
        inputs = [
            self._embedding_input(
                title=title,
                source_type=source_type,
                tags=tags,
                content=chunk,
            )
            for chunk in chunks
        ]
        try:
            return self.embedding_service.embed_texts(inputs)
        except RagEmbeddingError as exc:
            logger.warning(
                "RAG embedding generation failed; document will use lexical "
                "retrieval until embeddings are rebuilt: %s",
                exc,
            )
            return []

    def ingest_file(
        self,
        *,
        data: bytes,
        filename: str,
        content_type: str = "",
        llm_adapter: Optional[Any] = None,
        replace_existing: bool = False,
    ) -> RagIngestResult:
        """Parse, enrich and ingest a document without user-supplied metadata."""
        parsed: ParsedDocument = parse_uploaded_document(
            data,
            filename=filename,
            content_type=content_type,
        )
        existing = self._find_active_document_by_content(parsed.content)
        if existing is not None and not replace_existing:
            existing_metadata = existing.get("metadata") or {}
            return RagIngestResult(
                document_id=int(existing["id"]),
                title=str(existing["title"]),
                chunk_count=int(existing["chunk_count"]),
                duplicate=True,
                summary=str(existing_metadata.get("summary") or ""),
                source_type=str(existing.get("source_type") or "other"),
                tags=tuple(existing.get("tags") or []),
                enrichment_method=str(existing_metadata.get("enrichment_method") or ""),
                parser=str(existing_metadata.get("parser") or ""),
            )

        enrichment: RagEnrichment = enrich_rag_document(
            title=parsed.title,
            content=parsed.content,
            filename=filename,
            llm_adapter=llm_adapter,
        )
        metadata = {
            **parsed.metadata,
            "summary": enrichment.summary,
            "auto_classified": True,
            "enrichment_method": enrichment.method,
            "enrichment_model": enrichment.model,
        }
        result = self.ingest_document(
            title=parsed.title,
            content=parsed.content,
            source_type=enrichment.source_type,
            source_uri=f"upload://{parsed.metadata.get('file_name', filename)}",
            author=parsed.author,
            published_at=parsed.published_at,
            tags=enrichment.tags,
            metadata=metadata,
            replace_existing=replace_existing,
        )

        if result.duplicate:
            existing = self.get_document(result.document_id)
            if existing is not None:
                existing_metadata = existing.get("metadata") or {}
                return RagIngestResult(
                    document_id=result.document_id,
                    title=result.title,
                    chunk_count=result.chunk_count,
                    duplicate=True,
                    summary=str(existing_metadata.get("summary") or ""),
                    source_type=str(existing.get("source_type") or "other"),
                    tags=tuple(existing.get("tags") or []),
                    enrichment_method=str(existing_metadata.get("enrichment_method") or ""),
                    parser=str(existing_metadata.get("parser") or ""),
                )

        return RagIngestResult(
            document_id=result.document_id,
            title=result.title,
            chunk_count=result.chunk_count,
            duplicate=result.duplicate,
            summary=enrichment.summary,
            source_type=enrichment.source_type,
            tags=tuple(enrichment.tags),
            enrichment_method=enrichment.method,
            parser=parsed.parser,
        )

    def _find_active_document_by_content(self, content: str) -> Optional[Dict[str, Any]]:
        normalized_content = self._normalize_text(content)
        if not normalized_content:
            return None
        content_hash = self._hash_text(normalized_content)
        with self.db.get_session() as session:
            document = session.execute(
                select(RagDocument).where(
                    RagDocument.content_hash == content_hash,
                    RagDocument.status == "active",
                ).limit(1)
            ).scalar_one_or_none()
            return self._document_to_dict(document) if document is not None else None

    def _insert_fts_row(self, session, chunk: RagChunk, document: RagDocument) -> None:
        if not self._fts_available:
            return
        session.execute(
            text(
                """
                INSERT INTO rag_chunks_fts(chunk_id, document_id, title, tags, content)
                VALUES (:chunk_id, :document_id, :title, :tags, :content)
                """
            ),
            {
                "chunk_id": chunk.id,
                "document_id": document.id,
                "title": document.title,
                "tags": document.tags or "",
                "content": chunk.content,
            },
        )

    def _delete_document_rows(self, session, document_id: int) -> None:
        chunk_ids = [
            row[0]
            for row in session.execute(
                select(RagChunk.id).where(RagChunk.document_id == document_id)
            ).all()
        ]
        if self._fts_available:
            for chunk_id in chunk_ids:
                session.execute(text("DELETE FROM rag_chunks_fts WHERE chunk_id = :chunk_id"), {"chunk_id": chunk_id})
        session.execute(delete(RagChunk).where(RagChunk.document_id == document_id))
        session.execute(delete(RagDocument).where(RagDocument.id == document_id))

    def delete_document(self, document_id: int) -> bool:
        def _write(session):
            exists = session.get(RagDocument, document_id)
            if exists is None:
                return False
            self._delete_document_rows(session, document_id)
            return True

        return self.db._run_write_transaction("rag_delete_document", _write)

    def list_documents(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        source_type: str = "",
        query: str = "",
    ) -> Dict[str, Any]:
        page = max(1, int(page or 1))
        page_size = max(1, min(100, int(page_size or 20)))
        with self.db.get_session() as session:
            stmt = select(RagDocument).where(RagDocument.status == "active")
            count_stmt = select(func.count(RagDocument.id)).where(RagDocument.status == "active")
            if source_type:
                stmt = stmt.where(RagDocument.source_type == source_type)
                count_stmt = count_stmt.where(RagDocument.source_type == source_type)
            if query:
                like_value = f"%{query.strip()}%"
                condition = or_(RagDocument.title.like(like_value), RagDocument.tags.like(like_value), RagDocument.source_uri.like(like_value))
                stmt = stmt.where(condition)
                count_stmt = count_stmt.where(condition)
            total = int(session.execute(count_stmt).scalar() or 0)
            rows = session.execute(
                stmt.order_by(RagDocument.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            ).scalars().all()
            return {
                "items": [self._document_to_dict(row) for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    def get_document(self, document_id: int, *, include_chunks: bool = False) -> Optional[Dict[str, Any]]:
        with self.db.get_session() as session:
            document = session.get(RagDocument, document_id)
            if document is None or document.status != "active":
                return None
            payload = self._document_to_dict(document)
            if include_chunks:
                chunks = session.execute(
                    select(RagChunk)
                    .where(RagChunk.document_id == document_id)
                    .order_by(RagChunk.chunk_index.asc())
                ).scalars().all()
                payload["chunks"] = [self._chunk_to_dict(chunk, document) for chunk in chunks]
            return payload

    def stats(self) -> Dict[str, Any]:
        with self.db.get_session() as session:
            document_count = int(session.execute(select(func.count(RagDocument.id)).where(RagDocument.status == "active")).scalar() or 0)
            chunk_count = int(session.execute(select(func.count(RagChunk.id))).scalar() or 0)
            by_type_rows = session.execute(
                select(RagDocument.source_type, func.count(RagDocument.id))
                .where(RagDocument.status == "active")
                .group_by(RagDocument.source_type)
            ).all()
            embedded_chunk_count = int(
                session.execute(
                    select(func.count(RagChunk.id))
                    .join(RagDocument, RagChunk.document_id == RagDocument.id)
                    .where(
                        RagDocument.status == "active",
                        RagChunk.embedding_model == self.embedding_service.model,
                        RagChunk.embedding_json.is_not(None),
                    )
                ).scalar()
                or 0
            ) if self.embedding_service.is_available else 0
            embedding_coverage = (
                round(embedded_chunk_count * 100.0 / chunk_count, 2)
                if chunk_count
                else 0.0
            )
            return {
                "document_count": document_count,
                "chunk_count": chunk_count,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "retrieval_mode": self._stats_retrieval_mode(),
                "by_source_type": {row[0]: int(row[1]) for row in by_type_rows},
                "supported_extensions": list(SUPPORTED_EXTENSIONS),
                "max_upload_mb": self.max_upload_bytes // (1024 * 1024),
                "auto_enrichment": True,
                "semantic_enabled": self.embedding_service.is_available,
                "embedding_model": self.embedding_service.model,
                "embedded_chunk_count": embedded_chunk_count,
                "embedding_coverage_pct": embedding_coverage,
            }

    def search(self, query: str, *, top_k: Optional[int] = None, tags: Optional[Sequence[str] | str] = None) -> Dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("query is required")
        effective_top_k = max(1, min(30, int(top_k or self.default_top_k)))
        normalized_tags = self._normalize_tags(tags)

        candidate_k = min(90, effective_top_k * 3)
        semantic_results, semantic_status = self._search_semantic(
            normalized_query,
            candidate_k,
            normalized_tags,
        )
        fts_results = self._search_fts(normalized_query, candidate_k, normalized_tags)
        lexical_results = self._search_lexical(
            normalized_query,
            candidate_k,
            normalized_tags,
        )
        merged = self._merge_results(
            semantic_results,
            fts_results,
            lexical_results,
            top_k=effective_top_k,
        )
        return {
            "query": normalized_query,
            "top_k": effective_top_k,
            "results": merged,
            "retrieval_mode": self._search_retrieval_mode(semantic_status),
        }

    def _stats_retrieval_mode(self) -> str:
        base = "fts5_bm25_lexical" if self._fts_available else "lexical"
        if self.embedding_service.is_available:
            return f"hybrid_semantic_{base}"
        return f"sqlite_{base}" if self._fts_available else base

    def _search_retrieval_mode(self, semantic_status: str) -> str:
        base = "hybrid_fts_lexical" if self._fts_available else "lexical"
        if semantic_status == "active":
            return "hybrid_semantic_fts_lexical"
        if self.embedding_service.is_available:
            return f"{base}_semantic_fallback"
        return base

    def _search_semantic(
        self,
        query: str,
        top_k: int,
        tags: List[str],
    ) -> Tuple[List[Dict[str, Any]], str]:
        if not self.embedding_service.is_available:
            return [], "disabled"

        with self.db.get_session() as session:
            rows = session.execute(
                select(RagChunk, RagDocument)
                .join(RagDocument, RagChunk.document_id == RagDocument.id)
                .where(
                    RagDocument.status == "active",
                    RagChunk.embedding_model == self.embedding_service.model,
                    RagChunk.embedding_json.is_not(None),
                )
                .order_by(RagChunk.id.desc())
                .limit(self.semantic_scan_limit)
            ).all()

        candidates = [
            (chunk, document)
            for chunk, document in rows
            if not tags or self._document_matches_tags(document, tags)
        ]
        if not candidates:
            return [], "no_index"

        try:
            query_vector = self.embedding_service.embed_texts([query])[0]
        except RagEmbeddingError as exc:
            logger.warning("RAG semantic query embedding failed: %s", exc)
            return [], "error"

        scored = []
        for chunk, document in candidates:
            vector = self._parse_embedding_vector(
                chunk.embedding_json,
                expected_dimensions=len(query_vector),
            )
            if not vector:
                continue
            score = self._cosine_similarity(query_vector, vector)
            scored.append((score, chunk, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            self._chunk_to_result(
                chunk,
                document,
                score=score,
                retrieval="semantic",
            )
            for score, chunk, document in scored[:top_k]
        ], "active" if scored else "no_index"

    @staticmethod
    def _parse_embedding_vector(
        value: Optional[str],
        *,
        expected_dimensions: int,
    ) -> List[float]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
            vector = [float(item) for item in parsed]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if len(vector) != expected_dimensions:
            return []
        if any(not math.isfinite(item) for item in vector):
            return []
        return vector

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        dot_product = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return dot_product / (left_norm * right_norm)

    def _search_fts(self, query: str, top_k: int, tags: List[str]) -> List[Dict[str, Any]]:
        if not self._fts_available:
            return []
        match_query = self._build_fts_query(query)
        if not match_query:
            return []
        with self.db.get_session() as session:
            try:
                rows = session.execute(
                    text(
                        """
                        SELECT chunk_id, bm25(rag_chunks_fts) AS score
                        FROM rag_chunks_fts
                        WHERE rag_chunks_fts MATCH :query
                        ORDER BY score ASC
                        LIMIT :limit
                        """
                    ),
                    {"query": match_query, "limit": top_k * 3},
                ).all()
            except Exception:
                return []
            chunk_ids = [int(row.chunk_id) for row in rows]
            if not chunk_ids:
                return []
            score_by_id = {
                int(row.chunk_id): 1.0 / (1.0 + abs(float(row.score or 0.0)))
                for row in rows
            }
            return self._hydrate_chunks(session, chunk_ids, score_by_id, "fts", tags)[:top_k]

    @staticmethod
    def _build_fts_query(query: str) -> str:
        terms = [term for term in _TOKEN_RE.findall(query) if term.strip()]
        if not terms:
            return ""
        compact_terms = []
        for term in terms[:12]:
            escaped = term.replace('"', '""')
            if re.fullmatch(r"[A-Za-z0-9_.$%-]+", escaped):
                compact_terms.append(f'"{escaped}"*')
            else:
                compact_terms.append(f'"{escaped}"')
        return " OR ".join(compact_terms)

    def _search_lexical(self, query: str, top_k: int, tags: List[str]) -> List[Dict[str, Any]]:
        query_terms = set(self._lexical_terms(query))
        if not query_terms:
            return []
        with self.db.get_session() as session:
            rows = session.execute(
                select(RagChunk, RagDocument)
                .join(RagDocument, RagChunk.document_id == RagDocument.id)
                .where(RagDocument.status == "active")
                .order_by(RagDocument.created_at.desc())
                .limit(2000)
            ).all()
            scored = []
            for chunk, document in rows:
                if tags and not self._document_matches_tags(document, tags):
                    continue
                haystack = f"{document.title}\n{document.tags or ''}\n{chunk.content}"
                content_terms = set(self._lexical_terms(haystack))
                overlap = query_terms & content_terms
                if not overlap and query not in haystack:
                    continue
                score = float(len(overlap))
                if query in haystack:
                    score += 3.0
                if document.source_type == "preference":
                    score += 0.5
                scored.append((score, chunk, document))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [
                self._chunk_to_result(chunk, document, score=score, retrieval="lexical")
                for score, chunk, document in scored[:top_k]
            ]

    @staticmethod
    def _lexical_terms(value: str) -> List[str]:
        raw_terms = [term.lower() for term in _TOKEN_RE.findall(value or "") if term.strip()]
        chinese_chars = [term for term in raw_terms if re.fullmatch(r"[\u4e00-\u9fff]", term)]
        bigrams = [f"{chinese_chars[i]}{chinese_chars[i + 1]}" for i in range(len(chinese_chars) - 1)]
        return raw_terms + bigrams

    def _hydrate_chunks(self, session, chunk_ids: List[int], score_by_id: Dict[int, float], retrieval: str, tags: List[str]) -> List[Dict[str, Any]]:
        rows = session.execute(
            select(RagChunk, RagDocument)
            .join(RagDocument, RagChunk.document_id == RagDocument.id)
            .where(RagChunk.id.in_(chunk_ids), RagDocument.status == "active")
        ).all()
        by_id = {chunk.id: (chunk, document) for chunk, document in rows}
        hydrated = []
        for chunk_id in chunk_ids:
            pair = by_id.get(chunk_id)
            if pair is None:
                continue
            chunk, document = pair
            if tags and not self._document_matches_tags(document, tags):
                continue
            hydrated.append(self._chunk_to_result(chunk, document, score=score_by_id.get(chunk_id, 0.0), retrieval=retrieval))
        return hydrated

    def _merge_results(self, *groups: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        merged: Dict[int, Dict[str, Any]] = {}
        weights = {"semantic": 1.6, "fts": 0.8, "lexical": 0.4}
        for group in groups:
            for rank, result in enumerate(group, start=1):
                chunk_id = int(result["chunk_id"])
                retrieval = str(result["retrieval"])
                rrf_score = weights.get(retrieval, 1.0) / (60.0 + rank)
                existing = merged.get(chunk_id)
                if existing is None:
                    merged[chunk_id] = {
                        **result,
                        "score": rrf_score,
                        "retrieval": retrieval,
                        "score_components": {
                            retrieval: float(result["score"]),
                        },
                    }
                    continue
                existing["retrieval"] = f"{existing['retrieval']}+{retrieval}"
                existing["score"] = float(existing["score"]) + rrf_score
                existing["score_components"][retrieval] = float(result["score"])
        return sorted(merged.values(), key=lambda item: float(item["score"]), reverse=True)[:top_k]

    def rebuild_embeddings(
        self,
        *,
        document_id: Optional[int] = None,
        force: bool = False,
    ) -> RagEmbeddingRebuildResult:
        if not self.embedding_service.is_available:
            raise ValueError("RAG_EMBEDDING_MODEL is not configured")

        with self.db.get_session() as session:
            stmt = (
                select(RagChunk, RagDocument)
                .join(RagDocument, RagChunk.document_id == RagDocument.id)
                .where(RagDocument.status == "active")
                .order_by(RagChunk.id.asc())
            )
            if document_id is not None:
                stmt = stmt.where(RagDocument.id == document_id)
            rows = session.execute(stmt).all()

        targets = []
        skipped = 0
        configured_dimensions = int(
            getattr(self.embedding_service, "dimensions", 0) or 0
        )
        for chunk, document in rows:
            is_current = (
                chunk.embedding_model == self.embedding_service.model
                and bool(chunk.embedding_json)
                and (
                    configured_dimensions == 0
                    or chunk.embedding_dimensions == configured_dimensions
                )
            )
            if is_current and not force:
                skipped += 1
                continue
            targets.append((chunk.id, chunk.content, document))

        updated = 0
        failed = 0
        last_error = ""
        batch_size = self.embedding_service.batch_size
        for start in range(0, len(targets), batch_size):
            batch = targets[start:start + batch_size]
            inputs = [
                self._embedding_input(
                    title=document.title,
                    source_type=document.source_type,
                    tags=self._normalize_tags(document.tags),
                    content=content,
                )
                for _, content, document in batch
            ]
            try:
                vectors = self.embedding_service.embed_texts(inputs)
            except RagEmbeddingError as exc:
                failed += len(batch)
                last_error = str(exc)
                logger.error("RAG embedding rebuild batch failed: %s", exc)
                continue

            def _write(session):
                batch_updated = 0
                for (chunk_id, _, _), vector in zip(batch, vectors):
                    chunk = session.get(RagChunk, chunk_id)
                    if chunk is None:
                        continue
                    chunk.embedding_model = self.embedding_service.model
                    chunk.embedding_dimensions = len(vector)
                    chunk.embedding_json = json.dumps(vector, separators=(",", ":"))
                    batch_updated += 1
                return batch_updated

            updated += self.db._run_write_transaction(
                "rag_rebuild_embeddings",
                _write,
            )

        return RagEmbeddingRebuildResult(
            enabled=True,
            embedding_model=self.embedding_service.model,
            updated_chunks=updated,
            skipped_chunks=skipped,
            failed_chunks=failed,
            error=last_error,
        )

    @staticmethod
    def _document_matches_tags(document: RagDocument, tags: List[str]) -> bool:
        doc_tags = {item.strip() for item in (document.tags or "").split(",") if item.strip()}
        return all(tag in doc_tags for tag in tags)

    def _document_to_dict(self, document: RagDocument) -> Dict[str, Any]:
        metadata = self._parse_json(document.metadata_json)
        return {
            "id": document.id,
            "title": document.title,
            "source_type": document.source_type,
            "source_uri": document.source_uri or "",
            "author": document.author or "",
            "published_at": document.published_at.isoformat() if document.published_at else None,
            "tags": self._normalize_tags(document.tags),
            "summary": str(metadata.get("summary") or ""),
            "metadata": metadata,
            "content_hash": document.content_hash,
            "status": document.status,
            "chunk_count": document.chunk_count,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        }

    def _chunk_to_dict(self, chunk: RagChunk, document: RagDocument) -> Dict[str, Any]:
        return {
            "id": chunk.id,
            "document_id": document.id,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "char_count": chunk.char_count,
            "token_estimate": chunk.token_estimate,
            "metadata": self._parse_json(chunk.metadata_json),
        }

    def _chunk_to_result(self, chunk: RagChunk, document: RagDocument, *, score: float, retrieval: str) -> Dict[str, Any]:
        return {
            "chunk_id": chunk.id,
            "document_id": document.id,
            "chunk_index": chunk.chunk_index,
            "title": document.title,
            "source_type": document.source_type,
            "source_uri": document.source_uri or "",
            "tags": self._normalize_tags(document.tags),
            "content": chunk.content,
            "score": score,
            "retrieval": retrieval,
            "created_at": document.created_at.isoformat() if document.created_at else None,
        }


def get_rag_service() -> RagService:
    return RagService()
