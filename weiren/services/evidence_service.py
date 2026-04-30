from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional, Sequence

from sqlmodel import Session, SQLModel, select

from weiren.models import EvidenceLink, Message, Source
from weiren.utils.entity_registry import entity_content, entity_date, entity_meta, entity_title
from weiren.utils.privacy import build_masked_text
from weiren.utils.text import dumps_json, extract_keywords, loads_json


@dataclass(slots=True)
class EvidenceView:
    source_id: int
    source_filename: str
    source_type: str
    raw_text: str
    masked_content: str
    imported_at: datetime
    keyword_hits: list[str]
    similarity_score: Optional[float]
    related_date: Optional[datetime]
    message_id: Optional[int]


class EvidenceService:
    def ensure_entity_links(self, session: Session, entity_type: str, record: SQLModel) -> list[EvidenceLink]:
        if getattr(record, "id", None) is None:
            return []
        existing = session.exec(
            select(EvidenceLink).where(EvidenceLink.entity_type == entity_type, EvidenceLink.entity_id == record.id)
        ).all()
        if existing:
            return existing

        text_value = entity_content(record, entity_type)
        title_value = entity_title(record, entity_type)
        related = self._normalize_datetime(entity_date(record, entity_type) or getattr(record, "occurred_at", None))
        candidates = session.exec(select(Message).where(Message.source_id == record.source_id)).all()
        created: list[EvidenceLink] = []
        match_terms = [item for item in [title_value, text_value] if item]
        keyword_hits = extract_keywords(text_value or title_value, limit=5)

        for message in candidates:
            if not self._matches_message(message.content, match_terms):
                continue
            link = EvidenceLink(
                entity_type=entity_type,
                entity_id=record.id,
                source_id=record.source_id,
                message_id=message.id,
                raw_text=message.content,
                masked_content=message.masked_content or build_masked_text(message.content),
                keyword_hits_json=dumps_json(keyword_hits),
                similarity_score=100.0 if text_value and text_value in message.content else None,
                related_date=message.occurred_at or related,
            )
            session.add(link)
            created.append(link)

        if not created:
            link = EvidenceLink(
                entity_type=entity_type,
                entity_id=record.id,
                source_id=record.source_id,
                raw_text=text_value or title_value,
                masked_content=build_masked_text(text_value or title_value),
                keyword_hits_json=dumps_json(keyword_hits),
                similarity_score=None,
                related_date=related,
            )
            session.add(link)
            created.append(link)
        return created

    def list_evidence(self, session: Session, entity_type: str, entity_id: int, demo_mode: bool = False) -> list[EvidenceView]:
        links = session.exec(
            select(EvidenceLink).where(EvidenceLink.entity_type == entity_type, EvidenceLink.entity_id == entity_id)
        ).all()
        source_ids = {link.source_id for link in links}
        sources = {source.id: source for source in session.exec(select(Source).where(Source.id.in_(source_ids))).all() if source.id is not None}
        result: list[EvidenceView] = []
        for link in links:
            source = sources.get(link.source_id)
            if source is None:
                continue
            masked = link.masked_content or build_masked_text(link.raw_text, summary_only=demo_mode)
            content = masked if demo_mode else link.raw_text
            result.append(
                EvidenceView(
                    source_id=source.id or 0,
                    source_filename=source.filename,
                    source_type=source.source_type,
                    raw_text=content,
                    masked_content=masked,
                    imported_at=source.imported_at,
                    keyword_hits=list(loads_json(link.keyword_hits_json, [])),
                    similarity_score=link.similarity_score,
                    related_date=link.related_date,
                    message_id=link.message_id,
                )
            )
        return result

    def merge_links(self, session: Session, entity_type: str, from_entity_id: int, to_entity_id: int) -> None:
        links = session.exec(
            select(EvidenceLink).where(EvidenceLink.entity_type == entity_type, EvidenceLink.entity_id == from_entity_id)
        ).all()
        for link in links:
            link.entity_id = to_entity_id
            session.add(link)

    @staticmethod
    def _matches_message(content: str, match_terms: Sequence[str]) -> bool:
        cleaned_terms = [term for term in match_terms if term]
        if not cleaned_terms:
            return False
        return any(term in content or content in term for term in cleaned_terms)

    @staticmethod
    def _normalize_datetime(value: object) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min)
        return None

    def fetch_entity(self, session: Session, entity_type: str, entity_id: int) -> SQLModel | None:
        meta = entity_meta(entity_type)
        return session.get(meta.model, entity_id)
