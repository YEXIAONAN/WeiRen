from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from weiren.models import Memory, Preference, Quote, TimelineEvent, Trait


# Entity type constants — use these instead of raw strings throughout the codebase
ENTITY_TRAIT = "trait"
ENTITY_PREFERENCE = "preference"
ENTITY_MEMORY = "memory"
ENTITY_QUOTE = "quote"
ENTITY_TIMELINE = "timeline"
ENTITY_MESSAGE = "message"


@dataclass(frozen=True, slots=True)
class EntityMeta:
    entity_type: str
    model: type[Any]
    label: str
    title_field: str
    content_field: str
    date_field: Optional[str] = None


ENTITY_REGISTRY: dict[str, EntityMeta] = {
    ENTITY_TRAIT: EntityMeta(ENTITY_TRAIT, Trait, "人物特征", "trait", "evidence", None),
    ENTITY_PREFERENCE: EntityMeta(ENTITY_PREFERENCE, Preference, "偏好厌恶", "item", "evidence", "occurred_at"),
    ENTITY_MEMORY: EntityMeta(ENTITY_MEMORY, Memory, "共同记忆", "title", "content", "event_time"),
    ENTITY_QUOTE: EntityMeta(ENTITY_QUOTE, Quote, "典型原话", "speaker", "content", "occurred_at"),
    ENTITY_TIMELINE: EntityMeta(ENTITY_TIMELINE, TimelineEvent, "时间线事件", "title", "content", "event_date"),
}


REVIEWABLE_ENTITY_TYPES = [ENTITY_TRAIT, ENTITY_PREFERENCE, ENTITY_MEMORY, ENTITY_QUOTE, ENTITY_TIMELINE]
DEDUPE_ENTITY_TYPES = [ENTITY_MEMORY, ENTITY_QUOTE, ENTITY_TIMELINE]


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
