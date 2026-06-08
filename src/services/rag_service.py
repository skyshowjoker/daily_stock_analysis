# -*- coding: utf-8 -*-
"""Local RAG knowledge base for investment knowledge and preferences."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import delete, func, or_, select, text

from src.storage import DatabaseManager, RagChunk, RagDocument

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 1200
_DEFAULT_CHUNK_OVERLAP = 180
_DEFAULT_TOP_K = 8
_MAX_CONTENT_CHARS = 1_000_000
_SOURCE_TYPES = {"article", "news", "book", "note", "preference", "url", "other"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_.$%-]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class RagIngestResult:
    document_id: int
    title: str
    chunk_count: int
    duplicate: bool = False


class RagService:
    """RAG document ingestion and retrieval service.

    The first implementation deliberately keeps retrieval local and
    deterministic: SQLite FTS5/BM25 plus a lexical fallback for Chinese text.
    Embedding/vector backends can be added later without changing the document
    and chunk contract.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()
        self.chunk_size = self._read_int_env("RAG_CHUNK_SIZE", _DEFAULT_CHUNK_SIZE, 300, 4000)
        self.chunk_overlap = self._read_int_env("RAG_CHUNK_OVERLAP", _DEFAULT_CHUNK_OVERLAP, 0, self.chunk_size // 2)
        self.default_top_k = self._read_int_env("RAG_DEFAULT_TOP_K", _DEFAULT_TOP_K, 1, 30)
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
        content_hash = self._hash_text(normalized_content)
        chunks = self._chunk_text(normalized_content)
        if not chunks:
            raise ValueError("content produced no chunks")

        def _write(session):
            existing = session.execute(
                select(RagDocument).where(
                    RagDocument.content_hash == content_hash,
                    RagDocument.status == "active",
                ).limit(1)
            ).scalar_one_or_none()
            if existing is not None and not replace_existing:
                return RagIngestResult(
                    document_id=existing.id,
                    title=existing.title,
                    chunk_count=existing.chunk_count,
                    duplicate=True,
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
                metadata_json=self._serialize_json(metadata),
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
            )

        return self.db._run_write_transaction("rag_ingest_document", _write)

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
            return {
                "document_count": document_count,
                "chunk_count": chunk_count,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "retrieval_mode": "sqlite_fts5_bm25_lexical" if self._fts_available else "lexical",
                "by_source_type": {row[0]: int(row[1]) for row in by_type_rows},
            }

    def search(self, query: str, *, top_k: Optional[int] = None, tags: Optional[Sequence[str] | str] = None) -> Dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("query is required")
        effective_top_k = max(1, min(30, int(top_k or self.default_top_k)))
        normalized_tags = self._normalize_tags(tags)

        fts_results = self._search_fts(normalized_query, effective_top_k, normalized_tags)
        lexical_results = self._search_lexical(normalized_query, effective_top_k, normalized_tags)
        merged = self._merge_results(fts_results, lexical_results, top_k=effective_top_k)
        return {
            "query": normalized_query,
            "top_k": effective_top_k,
            "results": merged,
            "retrieval_mode": "hybrid_fts_lexical" if self._fts_available else "lexical",
        }

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
        for group in groups:
            for result in group:
                chunk_id = int(result["chunk_id"])
                existing = merged.get(chunk_id)
                if existing is None:
                    merged[chunk_id] = result
                    continue
                existing["retrieval"] = f"{existing['retrieval']}+{result['retrieval']}"
                existing["score"] = max(float(existing["score"]), float(result["score"]))
        return sorted(merged.values(), key=lambda item: float(item["score"]), reverse=True)[:top_k]

    @staticmethod
    def _document_matches_tags(document: RagDocument, tags: List[str]) -> bool:
        doc_tags = {item.strip() for item in (document.tags or "").split(",") if item.strip()}
        return all(tag in doc_tags for tag in tags)

    def _document_to_dict(self, document: RagDocument) -> Dict[str, Any]:
        return {
            "id": document.id,
            "title": document.title,
            "source_type": document.source_type,
            "source_uri": document.source_uri or "",
            "author": document.author or "",
            "published_at": document.published_at.isoformat() if document.published_at else None,
            "tags": self._normalize_tags(document.tags),
            "metadata": self._parse_json(document.metadata_json),
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
