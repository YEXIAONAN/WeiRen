from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, SQLModel, func, select

from weiren.models import ChangeLog, EvidenceLink, Preference, QARecord
from weiren.services.evidence_service import EvidenceService
from weiren.services.search_index_service import SearchIndexService
from weiren.utils.entity_registry import REVIEWABLE_ENTITY_TYPES, entity_meta, serialize_record
from weiren.utils.privacy import build_masked_text
from weiren.utils.text import dumps_json


class ReviewService:
    def __init__(self) -> None:
        self.evidence_service = EvidenceService()
        self.search_index_service = SearchIndexService()

    def list_records(
        self, session: Session, entity_type: str, person_name: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[SQLModel], int]:
        meta = entity_meta(entity_type)
        filters = []
        if person_name and hasattr(meta.model, "person_name"):
            filters.append(meta.model.person_name == person_name)
        total = session.exec(select(func.count()).where(*filters)).one()
        statement = (
            select(meta.model)
            .where(*filters)
            .order_by(meta.model.updated_at.desc(), meta.model.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return session.exec(statement).all(), total

    def update_record(self, session: Session, entity_type: str, entity_id: int, payload: dict[str, str | bool]) -> SQLModel:
        meta = entity_meta(entity_type)
        record = session.get(meta.model, entity_id)
        if record is None:
            raise ValueError("记录不存在")
        before = serialize_record(record, entity_type)

        for field_name, raw_value in payload.items():
            if not hasattr(record, field_name):
                continue
            value = self._coerce_value(field_name, raw_value)
            setattr(record, field_name, value)

        if hasattr(record, "masked_content"):
            base_text = getattr(record, meta.content_field, "")
            record.masked_content = build_masked_text(str(base_text))
        record.updated_at = datetime.utcnow()
        session.add(record)
        self.evidence_service.ensure_entity_links(session, entity_type, record)
        self.search_index_service.upsert_entity(session, entity_type, record)
        session.add(
            ChangeLog(
                entity_type=entity_type,
                entity_id=entity_id,
                action="update",
                before_json=dumps_json(before),
                after_json=dumps_json(serialize_record(record, entity_type)),
                note="手工校正",
            )
        )
        session.commit()
        session.refresh(record)
        return record

    def delete_record(self, session: Session, entity_type: str, entity_id: int) -> None:
        meta = entity_meta(entity_type)
        record = session.get(meta.model, entity_id)
        if record is None:
            return
        before = serialize_record(record, entity_type)
        self.search_index_service.delete_entity(session, entity_type, entity_id)
        links = session.exec(
            select(EvidenceLink).where(EvidenceLink.entity_type == entity_type, EvidenceLink.entity_id == entity_id)
        ).all()
        for link in links:
            session.delete(link)
        session.delete(record)
        session.add(
            ChangeLog(
                entity_type=entity_type,
                entity_id=entity_id,
                action="delete",
                before_json=dumps_json(before),
                after_json="{}",
                note="手工删除",
            )
        )
        session.commit()

    @staticmethod
    def _coerce_value(field_name: str, raw_value: str | bool) -> Any:
        if field_name in {"is_confirmed", "is_low_confidence"}:
            return bool(raw_value)
        if field_name in {"occurred_at", "event_time"}:
            if not raw_value:
                return None
            return datetime.fromisoformat(str(raw_value))
        if field_name == "event_date":
            if not raw_value:
                return None
            return datetime.fromisoformat(str(raw_value)).date() if "T" in str(raw_value) else datetime.strptime(str(raw_value), "%Y-%m-%d").date()
        if field_name == "tags_json":
            return dumps_json([item.strip() for item in str(raw_value).split(",") if item.strip()])
        return raw_value
