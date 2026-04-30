from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlmodel import Session, select

from weiren.models import ChangeLog, DedupeCandidate
from weiren.services.evidence_service import EvidenceService
from weiren.services.review_service import ReviewService
from weiren.services.search_index_service import SearchIndexService
from weiren.utils.entity_registry import DEDUPE_ENTITY_TYPES, entity_content, entity_meta, entity_title, serialize_record
from weiren.utils.fuzzy_utils import composite_similarity
from weiren.utils.privacy import build_masked_text
from weiren.utils.text import dumps_json


class DedupeService:
    def __init__(self) -> None:
        self.evidence_service = EvidenceService()
        self.search_index_service = SearchIndexService()
        self.review_service = ReviewService()
        self.thresholds = {"memory": 82.0, "quote": 88.0, "timeline": 84.0}

    def scan(self, session: Session) -> list[DedupeCandidate]:
        existing = {
            (candidate.entity_type, min(candidate.left_entity_id, candidate.right_entity_id), max(candidate.left_entity_id, candidate.right_entity_id)): candidate
            for candidate in session.exec(select(DedupeCandidate)).all()
        }
        created: list[DedupeCandidate] = []
        for entity_type in DEDUPE_ENTITY_TYPES:
            meta = entity_meta(entity_type)
            records = [item for item in session.exec(select(meta.model)).all() if getattr(item, "id", None) is not None]
            for index, left in enumerate(records):
                for right in records[index + 1 :]:
                    if getattr(left, "person_name", None) != getattr(right, "person_name", None):
                        continue
                    score = composite_similarity(entity_content(left, entity_type), entity_content(right, entity_type))
                    if score < self.thresholds[entity_type]:
                        continue
                    key = (entity_type, min(left.id, right.id), max(left.id, right.id))
                    current = existing.get(key)
                    if current is None:
                        candidate = DedupeCandidate(
                            entity_type=entity_type,
                            left_entity_id=left.id,
                            right_entity_id=right.id,
                            similarity_score=score,
                            status="pending",
                        )
                        session.add(candidate)
                        created.append(candidate)
                        existing[key] = candidate
                    elif current.status == "pending" and abs(current.similarity_score - score) > 0.01:
                        current.similarity_score = score
                        current.updated_at = datetime.utcnow()
                        session.add(current)
        session.commit()
        return session.exec(select(DedupeCandidate).where(DedupeCandidate.status == "pending").order_by(DedupeCandidate.similarity_score.desc())).all()

    def list_candidates(self, session: Session) -> list[DedupeCandidate]:
        return session.exec(
            select(DedupeCandidate).where(DedupeCandidate.status == "pending").order_by(DedupeCandidate.similarity_score.desc())
        ).all()

    def resolve_keep(self, session: Session, candidate_id: int, keep_side: str) -> None:
        candidate = session.get(DedupeCandidate, candidate_id)
        if candidate is None:
            raise ValueError("候选项不存在")
        keep_id = candidate.left_entity_id if keep_side == "left" else candidate.right_entity_id
        drop_id = candidate.right_entity_id if keep_side == "left" else candidate.left_entity_id
        self._merge_entities(session, candidate.entity_type, keep_id, drop_id, None)
        candidate.status = "merged"
        candidate.merge_note = f"保留 {keep_id}，删除 {drop_id}"
        candidate.updated_at = datetime.utcnow()
        session.add(candidate)
        session.commit()

    def resolve_merge(self, session: Session, candidate_id: int, merged_title: str, merged_content: str) -> None:
        candidate = session.get(DedupeCandidate, candidate_id)
        if candidate is None:
            raise ValueError("候选项不存在")
        self._merge_entities(session, candidate.entity_type, candidate.left_entity_id, candidate.right_entity_id, {
            "title": merged_title,
            "content": merged_content,
        })
        candidate.status = "merged"
        candidate.merge_note = "手工合并内容"
        candidate.updated_at = datetime.utcnow()
        session.add(candidate)
        session.commit()

    def ignore(self, session: Session, candidate_id: int) -> None:
        candidate = session.get(DedupeCandidate, candidate_id)
        if candidate is None:
            return
        candidate.status = "ignored"
        candidate.updated_at = datetime.utcnow()
        session.add(candidate)
        session.commit()

    def _merge_entities(self, session: Session, entity_type: str, keep_id: int, drop_id: int, merged_payload: dict[str, str] | None) -> None:
        meta = entity_meta(entity_type)
        keep_record = session.get(meta.model, keep_id)
        drop_record = session.get(meta.model, drop_id)
        if keep_record is None or drop_record is None:
            raise ValueError("待合并记录不存在")
        before_keep = serialize_record(keep_record, entity_type)
        before_drop = serialize_record(drop_record, entity_type)
        merge_group_id = getattr(keep_record, "merge_group_id", None) or f"merge-{uuid4().hex[:12]}"
        setattr(keep_record, "merge_group_id", merge_group_id)
        if merged_payload:
            if hasattr(keep_record, "title") and merged_payload.get("title"):
                keep_record.title = merged_payload["title"]
            if hasattr(keep_record, "content") and merged_payload.get("content"):
                keep_record.content = merged_payload["content"]
                if hasattr(keep_record, "masked_content"):
                    keep_record.masked_content = build_masked_text(keep_record.content)
        keep_record.updated_at = datetime.utcnow()
        self.evidence_service.merge_links(session, entity_type, drop_id, keep_id)
        self.search_index_service.upsert_entity(session, entity_type, keep_record)
        self.search_index_service.delete_entity(session, entity_type, drop_id)
        session.add(
            ChangeLog(
                entity_type=entity_type,
                entity_id=keep_id,
                action="merge",
                before_json=dumps_json(before_keep),
                after_json=dumps_json(serialize_record(keep_record, entity_type)),
                note=f"合并自 {drop_id}",
            )
        )
        session.add(
            ChangeLog(
                entity_type=entity_type,
                entity_id=drop_id,
                action="delete",
                before_json=dumps_json(before_drop),
                after_json="{}",
                note=f"已并入 {keep_id}",
            )
        )
        session.delete(drop_record)
        session.add(keep_record)
