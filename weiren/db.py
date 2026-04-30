from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Iterable

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from weiren import models  # noqa: F401
from weiren.config import settings
from weiren.utils.entity_registry import ENTITY_MEMORY, ENTITY_PREFERENCE, ENTITY_QUOTE, ENTITY_TIMELINE, ENTITY_TRAIT
from weiren.models import (
    AppSetting,
    EvidenceLink,
    Memory,
    Message,
    Preference,
    Quote,
    SearchHistory,
    SearchPreset,
    SearchDocument,
    Source,
    TimelineEvent,
    Trait,
)
from weiren.utils.privacy import build_masked_text
from weiren.utils.text import dumps_json, extract_keywords


DATABASE_URL = f"sqlite:///{settings.database_path}"
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


@event.listens_for(Engine, "connect")
def _enable_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        for ddl in _migration_ddls():
            conn.execute(text(ddl))
        _rebuild_search_fts(conn)
    _ensure_default_settings()
    _backfill_masked_content_and_state()
    _backfill_evidence_links()
    _cleanup_old_files(settings.upload_dir, max_age_days=7)
    _cleanup_old_files(settings.data_dir / "exports", max_age_days=7)


def _cleanup_old_files(directory: Path, max_age_days: int) -> None:
    if not directory.exists():
        return
    cutoff = datetime.utcnow().timestamp() - max_age_days * 86400
    removed = 0
    for entry in directory.iterdir():
        if entry.is_file() and entry.stat().st_mtime < cutoff:
            entry.unlink()
            removed += 1
    if removed:
        import logging
        logging.getLogger("weiren.db").info("Cleaned %d old files from %s", removed, directory.name)


def _migration_ddls() -> list[str]:
    statements: list[str] = []
    statements.extend(_ensure_columns("sources", [
        ("updated_at", "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'"),
    ]))
    for table_name in ("messages", "memories", "preferences", "traits", "quotes", "timeline_events"):
        statements.extend(
            _ensure_columns(
                table_name,
                [
                    ("masked_content", "TEXT"),
                    ("is_confirmed", "INTEGER NOT NULL DEFAULT 0"),
                    ("is_low_confidence", "INTEGER NOT NULL DEFAULT 0"),
                    ("merge_group_id", "TEXT"),
                    ("updated_at", "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'"),
                ],
            )
        )
    statements.extend(_ensure_columns("memories", [("event_time", "DATETIME")]))
    statements.extend(_ensure_columns("preferences", [("category", "TEXT NOT NULL DEFAULT 'general'")]))
    statements.extend(_ensure_columns("quotes", [("tags_json", "TEXT NOT NULL DEFAULT '[]'")]))
    statements.extend(_ensure_columns("search_documents", [("updated_at", "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'")]))
    return statements


def _ensure_columns(table_name: str, columns: Iterable[tuple[str, str]]) -> list[str]:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)} if inspector.has_table(table_name) else set()
    statements: list[str] = []
    for column_name, column_def in columns:
        if column_name not in existing_columns:
            statements.append(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def};")
    return statements


def _rebuild_search_fts(conn) -> None:  # type: ignore[no-untyped-def]
    conn.execute(text("DROP TRIGGER IF EXISTS search_documents_ai;"))
    conn.execute(text("DROP TRIGGER IF EXISTS search_documents_ad;"))
    conn.execute(text("DROP TRIGGER IF EXISTS search_documents_au;"))
    conn.execute(text("DROP TABLE IF EXISTS search_documents_fts;"))
    conn.execute(
        text(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts USING fts5(
                title,
                content,
                person_name,
                content='search_documents',
                content_rowid='id',
                tokenize='trigram'
            );
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TRIGGER IF NOT EXISTS search_documents_ai AFTER INSERT ON search_documents BEGIN
                INSERT INTO search_documents_fts(rowid, title, content, person_name)
                VALUES (new.id, coalesce(new.title, ''), new.content, coalesce(new.person_name, ''));
            END;
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TRIGGER IF NOT EXISTS search_documents_ad AFTER DELETE ON search_documents BEGIN
                INSERT INTO search_documents_fts(search_documents_fts, rowid, title, content, person_name)
                VALUES('delete', old.id, coalesce(old.title, ''), old.content, coalesce(old.person_name, ''));
            END;
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TRIGGER IF NOT EXISTS search_documents_au AFTER UPDATE ON search_documents BEGIN
                INSERT INTO search_documents_fts(search_documents_fts, rowid, title, content, person_name)
                VALUES('delete', old.id, coalesce(old.title, ''), old.content, coalesce(old.person_name, ''));
                INSERT INTO search_documents_fts(rowid, title, content, person_name)
                VALUES (new.id, coalesce(new.title, ''), new.content, coalesce(new.person_name, ''));
            END;
            """
        )
    )
    conn.execute(text("INSERT INTO search_documents_fts(search_documents_fts) VALUES ('rebuild');"))


def _ensure_default_settings() -> None:
    with Session(engine) as session:
        existing = session.exec(select(AppSetting)).first()
        if existing is None:
            session.add(AppSetting(id=1))
            session.commit()


def _backfill_masked_content_and_state() -> None:
    with Session(engine) as session:
        changed = False
        content_entities = [
            (Message, "content"),
            (Memory, "content"),
            (Preference, "evidence"),
            (Trait, "evidence"),
            (Quote, "content"),
            (TimelineEvent, "content"),
        ]
        for model, field_name in content_entities:
            for record in session.exec(
                select(model).where(
                    getattr(model, "masked_content").is_(None) | (getattr(model, "masked_content") == "")
                )
            ).all():
                original = getattr(record, field_name, "")
                if original:
                    record.masked_content = build_masked_text(original, summary_only=False)
                    record.updated_at = datetime.utcnow()
                    changed = True
                if hasattr(record, "event_time") and getattr(record, "event_time") is None and getattr(record, "occurred_at", None):
                    record.event_time = getattr(record, "occurred_at")
                    record.updated_at = datetime.utcnow()
                    changed = True
        if changed:
            session.commit()


def _backfill_evidence_links() -> None:
    with Session(engine) as session:
        messages_by_source: dict[int, list[Message]] = {}
        for message in session.exec(select(Message)).all():
            messages_by_source.setdefault(message.source_id, []).append(message)

        entities = [
            (Trait, ENTITY_TRAIT, lambda item: item.evidence),
            (Preference, ENTITY_PREFERENCE, lambda item: item.evidence),
            (Memory, ENTITY_MEMORY, lambda item: item.content),
            (Quote, ENTITY_QUOTE, lambda item: item.content),
            (TimelineEvent, ENTITY_TIMELINE, lambda item: item.content),
        ]
        existing_links: dict[str, set[int]] = {}
        for link in session.exec(select(EvidenceLink)).all():
            existing_links.setdefault(link.entity_type, set()).add(link.entity_id)

        changed = False
        for model, entity_type, text_getter in entities:
            existing_ids = existing_links.get(entity_type, set())
            for record in session.exec(select(model)).all():
                if record.id is None or record.id in existing_ids:
                    continue
                raw_text = text_getter(record)
                candidates = messages_by_source.get(record.source_id, [])
                matched = False
                for message in candidates:
                    if not raw_text:
                        continue
                    if raw_text in message.content or message.content in raw_text or message.content[:24] in raw_text:
                        session.add(
                            EvidenceLink(
                                entity_type=entity_type,
                                entity_id=record.id,
                                source_id=record.source_id,
                                message_id=message.id,
                                raw_text=message.content,
                                masked_content=message.masked_content or build_masked_text(message.content),
                                keyword_hits_json=dumps_json(extract_keywords(raw_text, limit=5)),
                                similarity_score=100.0,
                                related_date=message.occurred_at,
                            )
                        )
                        matched = True
                        changed = True
                if matched:
                    continue
                source = session.get(Source, record.source_id)
                session.add(
                    EvidenceLink(
                        entity_type=entity_type,
                        entity_id=record.id,
                        source_id=record.source_id,
                        message_id=None,
                        raw_text=raw_text,
                        masked_content=build_masked_text(raw_text),
                        keyword_hits_json=dumps_json(extract_keywords(raw_text, limit=5)),
                        similarity_score=None,
                        related_date=getattr(record, "occurred_at", None),
                    )
                )
                changed = True
        if changed:
            session.commit()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
