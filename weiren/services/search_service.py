from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

import jieba
from sqlalchemy import text
from sqlmodel import Session, select

from weiren.models import Preference, Quote, SearchDocument, SearchHistory, SearchPreset, Source
from weiren.utils.fuzzy_utils import composite_similarity
from weiren.utils.text import extract_keywords, highlight_terms, loads_json

TOKEN_PATTERN = re.compile(r'"[^"]+"|\S+')
DATE_TOKEN_PATTERN = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")
TAG_ALIASES = {
    "food": ["food", "eat", "吃", "喝", "饮食", "咖啡", "面", "餐厅", "香菜", "甜", "奶油"],
    "emotion": ["emotion", "情绪", "生气", "难过", "不高兴", "失眠", "烦", "冷战"],
    "relationship": ["relationship", "关系", "吵架", "和好", "冷战", "陪", "一起"],
    "travel": ["travel", "出行", "车站", "江边", "看海", "走路", "站", "路"],
}


@dataclass(slots=True)
class ParsedSearchQuery:
    raw_query: str
    text_terms: list[str] = field(default_factory=list)
    entity_types: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    date_token: Optional[str] = None
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None

    @property
    def display_terms(self) -> list[str]:
        return self.text_terms + self.entity_types + self.source_types + self.tags + ([self.date_token] if self.date_token else [])


@dataclass(slots=True)
class RelatedFragment:
    document_id: int
    entity_type: str
    entity_id: int
    title: str
    snippet: str
    score: float


@dataclass(slots=True)
class SearchResult:
    document_id: int
    entity_type: str
    entity_id: int
    source_id: int
    source_filename: str
    source_type: str
    person_name: str
    title: str
    content: str
    occurred_at: Optional[datetime]
    highlight: str
    tags: list[str] = field(default_factory=list)
    related_fragments: list[RelatedFragment] = field(default_factory=list)


@dataclass(slots=True)
class SimilarSentence:
    document_id: int
    entity_type: str
    entity_id: int
    source_id: int
    source_filename: str
    source_type: str
    title: str
    content: str
    score: float
    highlight: str


@dataclass(slots=True)
class SearchBundle:
    parsed_query: ParsedSearchQuery
    results: list[SearchResult]


class SearchService:
    def search(
        self,
        session: Session,
        query: str,
        source_id: Optional[int] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        limit: int = 18,
    ) -> SearchBundle:
        parsed = self.parse_query(query)
        effective_start = self._later_of(start_at, parsed.date_start)
        effective_end = self._earlier_of(end_at, parsed.date_end)
        rows = self._fetch_documents(session, parsed, source_id, effective_start, effective_end, limit * 6)
        results = self._build_results(session, rows, parsed, limit)
        return SearchBundle(parsed_query=parsed, results=results)

    def similar_sentences(
        self,
        session: Session,
        sentence: str,
        source_id: Optional[int] = None,
        limit: int = 10,
    ) -> list[SimilarSentence]:
        statement = select(SearchDocument, Source).join(Source, Source.id == SearchDocument.source_id)
        if source_id:
            statement = statement.where(SearchDocument.source_id == source_id)
        documents = session.exec(statement).all()
        scored: list[SimilarSentence] = []
        terms = self._plain_terms(sentence)
        for document, source in documents:
            score = composite_similarity(sentence, document.content)
            if score < 45:
                continue
            scored.append(
                SimilarSentence(
                    document_id=document.id or 0,
                    entity_type=document.entity_type,
                    entity_id=document.entity_id,
                    source_id=document.source_id,
                    source_filename=source.filename,
                    source_type=source.source_type,
                    title=document.title or document.entity_type,
                    content=document.content,
                    score=score,
                    highlight=highlight_terms(document.content[:220], terms),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]

    def list_presets(self, session: Session, limit: int = 12) -> list[SearchPreset]:
        return session.exec(select(SearchPreset).order_by(SearchPreset.updated_at.desc(), SearchPreset.id.desc()).limit(limit)).all()

    def save_preset(
        self,
        session: Session,
        name: str,
        raw_query: str,
        similar_query: str,
        source_id: Optional[int],
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> SearchPreset:
        preset = SearchPreset(
            name=name.strip() or "未命名搜索",
            raw_query=raw_query.strip(),
            similar_query=similar_query.strip(),
            source_id=source_id,
            start_date=start_date,
            end_date=end_date,
        )
        session.add(preset)
        session.commit()
        session.refresh(preset)
        return preset

    def list_history(self, session: Session, limit: int = 12) -> list[SearchHistory]:
        return session.exec(select(SearchHistory).order_by(SearchHistory.created_at.desc()).limit(limit)).all()

    def record_history(
        self,
        session: Session,
        raw_query: str,
        similar_query: str,
        source_id: Optional[int],
        start_date: Optional[date],
        end_date: Optional[date],
        result_count: int,
    ) -> None:
        if not raw_query.strip() and not similar_query.strip():
            return
        session.add(
            SearchHistory(
                raw_query=raw_query.strip(),
                similar_query=similar_query.strip(),
                source_id=source_id,
                start_date=start_date,
                end_date=end_date,
                result_count=result_count,
            )
        )
        session.commit()

    def parse_query(self, query: str) -> ParsedSearchQuery:
        parsed = ParsedSearchQuery(raw_query=(query or "").strip())
        for raw_token in TOKEN_PATTERN.findall(parsed.raw_query):
            token = raw_token.strip().strip('"')
            lowered = token.lower()
            if lowered.startswith("type:"):
                entity_type = lowered.split(":", 1)[1].strip()
                if entity_type and entity_type not in parsed.entity_types:
                    parsed.entity_types.append(entity_type)
                continue
            if lowered.startswith("source:"):
                source_type = lowered.split(":", 1)[1].strip()
                if source_type and source_type not in parsed.source_types:
                    parsed.source_types.append(source_type)
                continue
            if lowered.startswith("tag:"):
                tag = lowered.split(":", 1)[1].strip()
                if tag and tag not in parsed.tags:
                    parsed.tags.append(tag)
                continue
            if lowered.startswith("date:"):
                date_token = lowered.split(":", 1)[1].strip()
                parsed.date_token = date_token or None
                parsed.date_start, parsed.date_end = self._parse_date_token(date_token)
                continue
            if token:
                parsed.text_terms.append(token)
        return parsed

    def _fetch_documents(
        self,
        session: Session,
        parsed: ParsedSearchQuery,
        source_id: Optional[int],
        start_at: Optional[datetime],
        end_at: Optional[datetime],
        limit: int,
    ) -> list[dict[str, object]]:
        if parsed.text_terms:
            rows = self._fts_rows(session, parsed, source_id, start_at, end_at, limit)
            if rows:
                return rows
        fallback_limit = limit * 3 if parsed.tags else limit
        return self._filtered_rows(session, parsed, source_id, start_at, end_at, fallback_limit)

    def _fts_rows(
        self,
        session: Session,
        parsed: ParsedSearchQuery,
        source_id: Optional[int],
        start_at: Optional[datetime],
        end_at: Optional[datetime],
        limit: int,
    ) -> list[dict[str, object]]:
        match_query = self._build_fts_query(parsed.text_terms)
        if not match_query:
            return []
        params: dict[str, object] = {"match_query": match_query, "limit": limit}
        filters = ["search_documents_fts MATCH :match_query"]
        filters.extend(self._sql_filters(params, parsed, source_id, start_at, end_at))
        sql = f"""
            SELECT
                sd.id,
                sd.entity_type,
                sd.entity_id,
                sd.source_id,
                sd.person_name,
                COALESCE(sd.title, '') AS title,
                sd.content,
                sd.occurred_at,
                s.filename AS source_filename,
                s.source_type,
                snippet(search_documents_fts, 1, '<mark>', '</mark>', ' ... ', 18) AS snippet_text
            FROM search_documents_fts
            JOIN search_documents sd ON sd.id = search_documents_fts.rowid
            JOIN sources s ON s.id = sd.source_id
            WHERE {' AND '.join(filters)}
            ORDER BY bm25(search_documents_fts), COALESCE(sd.occurred_at, sd.created_at) DESC
            LIMIT :limit
        """
        return [dict(row) for row in session.connection().execute(text(sql), params).mappings().all()]

    def _filtered_rows(
        self,
        session: Session,
        parsed: ParsedSearchQuery,
        source_id: Optional[int],
        start_at: Optional[datetime],
        end_at: Optional[datetime],
        limit: int,
    ) -> list[dict[str, object]]:
        params: dict[str, object] = {"limit": limit}
        filters = ["1=1"]
        filters.extend(self._sql_filters(params, parsed, source_id, start_at, end_at))
        sql = f"""
            SELECT
                sd.id,
                sd.entity_type,
                sd.entity_id,
                sd.source_id,
                sd.person_name,
                COALESCE(sd.title, '') AS title,
                sd.content,
                sd.occurred_at,
                s.filename AS source_filename,
                s.source_type,
                '' AS snippet_text
            FROM search_documents sd
            JOIN sources s ON s.id = sd.source_id
            WHERE {' AND '.join(filters)}
            ORDER BY COALESCE(sd.occurred_at, sd.created_at) DESC, sd.id DESC
            LIMIT :limit
        """
        return [dict(row) for row in session.connection().execute(text(sql), params).mappings().all()]

    def _sql_filters(
        self,
        params: dict[str, object],
        parsed: ParsedSearchQuery,
        source_id: Optional[int],
        start_at: Optional[datetime],
        end_at: Optional[datetime],
    ) -> list[str]:
        filters: list[str] = []
        if source_id:
            filters.append("sd.source_id = :source_id")
            params["source_id"] = source_id
        if parsed.entity_types:
            placeholders = []
            for index, value in enumerate(parsed.entity_types):
                key = f"entity_type_{index}"
                params[key] = value
                placeholders.append(f":{key}")
            filters.append(f"sd.entity_type IN ({', '.join(placeholders)})")
        if parsed.source_types:
            placeholders = []
            for index, value in enumerate(parsed.source_types):
                key = f"source_type_{index}"
                params[key] = value
                placeholders.append(f":{key}")
            filters.append(f"s.source_type IN ({', '.join(placeholders)})")
        if start_at:
            filters.append("(sd.occurred_at IS NOT NULL AND sd.occurred_at >= :start_at)")
            params["start_at"] = start_at.isoformat(sep=" ")
        if end_at:
            filters.append("(sd.occurred_at IS NOT NULL AND sd.occurred_at <= :end_at)")
            params["end_at"] = end_at.isoformat(sep=" ")
        return filters

    def _build_results(self, session: Session, rows: list[dict[str, object]], parsed: ParsedSearchQuery, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        display_terms = self._plain_terms(" ".join(parsed.text_terms)) if parsed.text_terms else parsed.display_terms
        tag_cache: dict[tuple[str, int], list[str]] = {}
        for row in rows:
            entity_type = str(row["entity_type"])
            entity_id = int(row["entity_id"])
            tags = self._document_tags(session, entity_type, entity_id, str(row["content"]), tag_cache)
            if parsed.tags and not self._match_tag_filters(parsed.tags, tags, str(row["content"])):
                continue
            content = str(row["content"])
            result = SearchResult(
                document_id=int(row["id"]),
                entity_type=entity_type,
                entity_id=entity_id,
                source_id=int(row["source_id"]),
                source_filename=str(row["source_filename"]),
                source_type=str(row["source_type"]),
                person_name=str(row["person_name"]),
                title=str(row["title"] or entity_type),
                content=content,
                occurred_at=self._parse_db_datetime(row["occurred_at"]),
                highlight=str(row.get("snippet_text") or "") or highlight_terms(content[:220], display_terms),
                tags=tags,
            )
            results.append(result)
            if len(results) >= limit:
                break
        for result in results:
            result.related_fragments = self.related_fragments(session, result)
        return results

    def related_fragments(self, session: Session, result: SearchResult, limit: int = 3) -> list[RelatedFragment]:
        statement = (
            select(SearchDocument)
            .where(SearchDocument.id != result.document_id)
            .where((SearchDocument.source_id == result.source_id) | (SearchDocument.person_name == result.person_name))
            .order_by(SearchDocument.occurred_at.desc(), SearchDocument.id.desc())
            .limit(36)
        )
        documents = session.exec(statement).all()
        keywords = extract_keywords(result.content, limit=6)
        scored: list[RelatedFragment] = []
        for document in documents:
            overlap = [word for word in keywords if word and word in document.content]
            fuzzy_score = composite_similarity(result.content[:180], document.content[:180])
            source_bonus = 12.0 if document.source_id == result.source_id else 0.0
            score = round((len(overlap) * 18.0) + (fuzzy_score * 0.55) + source_bonus, 2)
            if score < 35:
                continue
            title = document.title or document.entity_type
            scored.append(
                RelatedFragment(
                    document_id=document.id or 0,
                    entity_type=document.entity_type,
                    entity_id=document.entity_id,
                    title=title,
                    snippet=highlight_terms(document.content[:180], overlap or keywords[:3]),
                    score=score,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        unique: list[RelatedFragment] = []
        seen: set[tuple[str, int]] = set()
        for item in scored:
            key = (item.entity_type, item.entity_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
            if len(unique) >= limit:
                break
        return unique

    def _document_tags(
        self,
        session: Session,
        entity_type: str,
        entity_id: int,
        content: str,
        cache: dict[tuple[str, int], list[str]],
    ) -> list[str]:
        key = (entity_type, entity_id)
        if key in cache:
            return cache[key]

        tags: list[str] = []
        if entity_type == "quote":
            record = session.get(Quote, entity_id)
            if record is not None:
                tags.extend(str(item).lower() for item in loads_json(record.tags_json, []))
        elif entity_type == "preference":
            record = session.get(Preference, entity_id)
            if record is not None and record.category:
                tags.append(record.category.lower())

        lowered = content.lower()
        for alias, signals in TAG_ALIASES.items():
            if alias in tags:
                continue
            if any(signal.lower() in lowered for signal in signals):
                tags.append(alias)
        cache[key] = sorted(set(tags))
        return cache[key]

    @staticmethod
    def _match_tag_filters(expected_tags: list[str], tags: list[str], content: str) -> bool:
        content_lower = content.lower()
        for tag in expected_tags:
            if tag in tags:
                continue
            signals = TAG_ALIASES.get(tag, [tag])
            if not any(signal.lower() in content_lower for signal in signals):
                return False
        return True

    @staticmethod
    def _build_fts_query(terms: list[str]) -> str:
        sanitized = []
        for term in terms:
            safe = term.replace('"', ' ').strip()
            if safe:
                sanitized.append(safe)
        return " AND ".join(sanitized)

    @staticmethod
    def _plain_terms(query: str) -> list[str]:
        raw_terms = re.split(r"\s+", query.strip())
        segmented = [token.strip() for token in jieba.cut_for_search(query) if len(token.strip()) >= 1]
        terms = [term for term in raw_terms + segmented if len(term) >= 1]
        unique: list[str] = []
        for term in terms:
            if term not in unique:
                unique.append(term)
        return unique[:12]

    @staticmethod
    def _parse_db_datetime(value: object) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_date_token(token: str) -> tuple[Optional[datetime], Optional[datetime]]:
        match = DATE_TOKEN_PATTERN.match((token or "").strip())
        if not match:
            return None, None
        year = int(match.group(1))
        month = int(match.group(2)) if match.group(2) else None
        day = int(match.group(3)) if match.group(3) else None
        if month is None:
            return datetime(year, 1, 1), datetime(year, 12, 31, 23, 59, 59)
        if day is None:
            last_day = calendar.monthrange(year, month)[1]
            return datetime(year, month, 1), datetime(year, month, last_day, 23, 59, 59)
        return datetime(year, month, day), datetime(year, month, day, 23, 59, 59)

    @staticmethod
    def _later_of(left: Optional[datetime], right: Optional[datetime]) -> Optional[datetime]:
        if left is None:
            return right
        if right is None:
            return left
        return left if left >= right else right

    @staticmethod
    def _earlier_of(left: Optional[datetime], right: Optional[datetime]) -> Optional[datetime]:
        if left is None:
            return right
        if right is None:
            return left
        return left if left <= right else right
