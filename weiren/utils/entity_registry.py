from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from weiren.models import Memory, Preference, Quote, TimelineEvent, Trait


@dataclass(frozen=True, slots=True)
class EntityMeta:
    entity_type: str
    model: type[Any]
    label: str
    title_field: str
    content_field: str
    date_field: Optional[str] = None


ENTITY_REGISTRY: dict[str, EntityMeta] = {
    "trait": EntityMeta("trait", Trait, "人物特征", "trait", "evidence", None),
    "preference": EntityMeta("preference", Preference, "偏好厌恶", "item", "evidence", "occurred_at"),
    "memory": EntityMeta("memory", Memory, "共同记忆", "title", "content", "event_time"),
    "quote": EntityMeta("quote", Quote, "典型原话", "speaker", "content", "occurred_at"),
    "timeline": EntityMeta("timeline", TimelineEvent, "时间线事件", "title", "content", "event_date"),
}


REVIEWABLE_ENTITY_TYPES = ["trait", "preference", "memory", "quote", "timeline"]
DEDUPE_ENTITY_TYPES = ["memory", "quote", "timeline"]


def entity_meta(entity_type: str) -> EntityMeta:
    if entity_type not in ENTITY_REGISTRY:
        raise KeyError(f"Unsupported entity type: {entity_type}")
    return ENTITY_REGISTRY[entity_type]


def entity_title(record: Any, entity_type: str) -> str:
    meta = entity_meta(entity_type)
    value = getattr(record, meta.title_field, None)
    return str(value or meta.label)


def entity_content(record: Any, entity_type: str) -> str:
    meta = entity_meta(entity_type)
    value = getattr(record, meta.content_field, None)
    return str(value or "")


def entity_date(record: Any, entity_type: str) -> Optional[datetime | date]:
    meta = entity_meta(entity_type)
    if meta.date_field is None:
        return None
    return getattr(record, meta.date_field, None)


def serialize_record(record: Any, entity_type: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"entity_type": entity_type}
    for key, value in record.model_dump().items():
        if isinstance(value, (datetime, date)):
            payload[key] = value.isoformat()
        else:
            payload[key] = value
    return payload
