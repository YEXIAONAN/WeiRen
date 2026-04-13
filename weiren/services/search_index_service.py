from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Optional

from sqlmodel import Session, select

from weiren.models import SearchDocument
from weiren.utils.entity_registry import entity_content, entity_date, entity_title


class SearchIndexService:
    def upsert_entity(self, session: Session, entity_type: str, record: Any) -> None:
        if getattr(record, "id", None) is None:
            return
        existing = session.exec(
            select(SearchDocument).where(SearchDocument.entity_type == entity_type, SearchDocument.entity_id == record.id)
        ).first()
        occurred_at = self._normalize_datetime(entity_date(record, entity_type) or getattr(record, "occurred_at", None))
        if existing is None:
            session.add(
                SearchDocument(
                    entity_type=entity_type,
                    entity_id=record.id,
                    source_id=record.source_id,
                    person_name=getattr(record, "person_name", "未命名对象"),
                    title=entity_title(record, entity_type),
                    content=entity_content(record, entity_type),
                    occurred_at=occurred_at,
                )
            )
            return
        existing.source_id = record.source_id
        existing.person_name = getattr(record, "person_name", "未命名对象")
        existing.title = entity_title(record, entity_type)
        existing.content = entity_content(record, entity_type)
        existing.occurred_at = occurred_at
        existing.updated_at = datetime.utcnow()
        session.add(existing)

    def delete_entity(self, session: Session, entity_type: str, entity_id: int) -> None:
        docs = session.exec(
            select(SearchDocument).where(SearchDocument.entity_type == entity_type, SearchDocument.entity_id == entity_id)
        ).all()
        for document in docs:
            session.delete(document)

    @staticmethod
    def _normalize_datetime(value: object) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min)
        return None
