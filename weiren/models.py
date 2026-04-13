from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel


class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str = Field(index=True, max_length=255)
    source_type: str = Field(index=True, max_length=32)
    file_path: Optional[str] = Field(default=None, max_length=500)
    file_hash: str = Field(index=True, unique=True, max_length=64)
    subject_name: str = Field(default="未命名对象", index=True, max_length=100)
    summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    meta_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    imported_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime, nullable=False, index=True),
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    speaker: Optional[str] = Field(default=None, index=True, max_length=100)
    content: str = Field(sa_column=Column(Text, nullable=False))
    masked_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    occurred_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, index=True))
    paragraph_index: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    keywords_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    people_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    is_confirmed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    is_low_confidence: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    merge_group_id: Optional[str] = Field(default=None, index=True, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class Memory(SQLModel, table=True):
    __tablename__ = "memories"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    person_name: str = Field(index=True, max_length=100)
    title: str = Field(max_length=200)
    content: str = Field(sa_column=Column(Text, nullable=False))
    masked_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    occurred_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, index=True))
    event_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, index=True))
    confidence: float = Field(default=0.5, sa_column=Column(Float, nullable=False))
    is_confirmed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    is_low_confidence: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    merge_group_id: Optional[str] = Field(default=None, index=True, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class Preference(SQLModel, table=True):
    __tablename__ = "preferences"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    person_name: str = Field(index=True, max_length=100)
    category: str = Field(default="general", max_length=50)
    item: str = Field(max_length=200)
    polarity: str = Field(index=True, max_length=16)
    evidence: str = Field(sa_column=Column(Text, nullable=False))
    masked_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    occurred_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, index=True))
    is_confirmed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    is_low_confidence: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    merge_group_id: Optional[str] = Field(default=None, index=True, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class Trait(SQLModel, table=True):
    __tablename__ = "traits"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    person_name: str = Field(index=True, max_length=100)
    trait: str = Field(max_length=200)
    evidence: str = Field(sa_column=Column(Text, nullable=False))
    masked_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    weight: float = Field(default=1.0, sa_column=Column(Float, nullable=False))
    is_confirmed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    is_low_confidence: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    merge_group_id: Optional[str] = Field(default=None, index=True, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class Quote(SQLModel, table=True):
    __tablename__ = "quotes"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    person_name: str = Field(index=True, max_length=100)
    speaker: Optional[str] = Field(default=None, index=True, max_length=100)
    content: str = Field(sa_column=Column(Text, nullable=False))
    masked_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    tags_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    occurred_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, index=True))
    is_confirmed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    is_low_confidence: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    merge_group_id: Optional[str] = Field(default=None, index=True, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class TimelineEvent(SQLModel, table=True):
    __tablename__ = "timeline_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    person_name: str = Field(index=True, max_length=100)
    event_date: Optional[date] = Field(default=None, sa_column=Column(Date, index=True))
    title: str = Field(max_length=200)
    content: str = Field(sa_column=Column(Text, nullable=False))
    evidence: str = Field(sa_column=Column(Text, nullable=False))
    masked_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    is_confirmed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    is_low_confidence: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    merge_group_id: Optional[str] = Field(default=None, index=True, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class SearchDocument(SQLModel, table=True):
    __tablename__ = "search_documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True, max_length=32)
    entity_id: int = Field(index=True)
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    person_name: str = Field(index=True, max_length=100)
    title: Optional[str] = Field(default=None, max_length=200)
    content: str = Field(sa_column=Column(Text, nullable=False))
    occurred_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, index=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class EvidenceLink(SQLModel, table=True):
    __tablename__ = "evidence_links"

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True, max_length=32)
    entity_id: int = Field(index=True)
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    message_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True),
    )
    raw_text: str = Field(sa_column=Column(Text, nullable=False))
    masked_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    keyword_hits_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    similarity_score: Optional[float] = Field(default=None, sa_column=Column(Float))
    related_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, index=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class ChangeLog(SQLModel, table=True):
    __tablename__ = "change_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True, max_length=32)
    entity_id: int = Field(index=True)
    action: str = Field(index=True, max_length=32)
    before_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    after_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    note: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, index=True))


class ExportRecord(SQLModel, table=True):
    __tablename__ = "export_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    export_type: str = Field(index=True, max_length=32)
    subject_name: str = Field(index=True, max_length=100)
    include_evidence: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    masked: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    confirmed_only: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    output_path: str = Field(max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, index=True))


class DedupeCandidate(SQLModel, table=True):
    __tablename__ = "dedupe_candidates"

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True, max_length=32)
    left_entity_id: int = Field(index=True)
    right_entity_id: int = Field(index=True)
    similarity_score: float = Field(sa_column=Column(Float, nullable=False))
    status: str = Field(default="pending", index=True, max_length=32)
    merge_note: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class QARecord(SQLModel, table=True):
    __tablename__ = "qa_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    subject_name: str = Field(index=True, max_length=100)
    question: str = Field(sa_column=Column(Text, nullable=False))
    intent: str = Field(index=True, max_length=64)
    answer: str = Field(sa_column=Column(Text, nullable=False))
    evidence_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, index=True))


class SearchPreset(SQLModel, table=True):
    __tablename__ = "search_presets"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=120)
    raw_query: str = Field(default="", sa_column=Column(Text, nullable=False))
    similar_query: str = Field(default="", sa_column=Column(Text, nullable=False))
    source_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True),
    )
    start_date: Optional[date] = Field(default=None, sa_column=Column(Date, index=True))
    end_date: Optional[date] = Field(default=None, sa_column=Column(Date, index=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, index=True))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))


class SearchHistory(SQLModel, table=True):
    __tablename__ = "search_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    raw_query: str = Field(default="", sa_column=Column(Text, nullable=False))
    similar_query: str = Field(default="", sa_column=Column(Text, nullable=False))
    source_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True),
    )
    start_date: Optional[date] = Field(default=None, sa_column=Column(Date, index=True))
    end_date: Optional[date] = Field(default=None, sa_column=Column(Date, index=True))
    result_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, index=True))


class ChatSession(SQLModel, table=True):
    __tablename__ = "chat_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    subject_name: str = Field(default="她", index=True, max_length=100)
    title: str = Field(default="新对话", max_length=160)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, index=True))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, index=True))


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(
        sa_column=Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    role: str = Field(index=True, max_length=16)
    content: str = Field(sa_column=Column(Text, nullable=False))
    intent: Optional[str] = Field(default=None, index=True, max_length=64)
    confidence: Optional[str] = Field(default=None, max_length=16)
    evidence_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, index=True))


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    demo_mode: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    mask_real_name: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    mask_phone: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    mask_location: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    mask_social: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False))
