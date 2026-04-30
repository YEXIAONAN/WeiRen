from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from fastapi import UploadFile
from sqlmodel import Session, select

from weiren.config import settings
from weiren.models import (
    Memory,
    Message,
    Preference,
    Quote,
    SearchDocument,
    Source,
    TimelineEvent,
    Trait,
)
from weiren.services.evidence_service import EvidenceService
from weiren.services.extraction import ExtractionBundle, RuleBasedExtractor
from weiren.services.parsers import ParsedSource, SourceParser
from weiren.utils.entity_registry import ENTITY_MEMORY, ENTITY_MESSAGE, ENTITY_PREFERENCE, ENTITY_QUOTE, ENTITY_TIMELINE, ENTITY_TRAIT
from weiren.utils.privacy import build_masked_text
from weiren.utils.text import dumps_json, extract_keywords, extract_people


@dataclass(slots=True)
class ImportResult:
    source: Source
    skipped: bool = False
    reason: Optional[str] = None


class ImportService:
    def __init__(self) -> None:
        self.parser = SourceParser()
        self.extractor = RuleBasedExtractor()
        self.evidence_service = EvidenceService()

    async def import_uploads(
        self,
        session: Session,
        files: Sequence[UploadFile],
        subject_name: str,
        manual_description: str = "",
    ) -> list[ImportResult]:
        results: list[ImportResult] = []
        for upload in files:
            if not upload.filename:
                continue

            payload = await upload.read()
            if len(payload) > settings.max_upload_size:
                results.append(
                    ImportResult(source=Source(filename=upload.filename, source_type="unknown", file_hash=""), skipped=True, reason="文件超过大小限制")
                )
                continue

            ext = Path(upload.filename).suffix.lower().lstrip(".")
            if ext in {"jpg", "jpeg", "png"} and not _is_valid_image(payload):
                results.append(
                    ImportResult(source=Source(filename=upload.filename, source_type="image", file_hash=""), skipped=True, reason="图片文件格式无效")
                )
                continue
            if ext == "pdf" and not _is_valid_pdf(payload):
                results.append(
                    ImportResult(source=Source(filename=upload.filename, source_type="pdf", file_hash=""), skipped=True, reason="PDF 文件格式无效")
                )
                continue

            file_hash = hashlib.sha256(payload).hexdigest()
            existing = session.exec(select(Source).where(Source.file_hash == file_hash)).first()
            if existing:
                results.append(ImportResult(source=existing, skipped=True, reason="文件已导入"))
                continue
            saved_path = settings.upload_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{upload.filename}"
            with saved_path.open("wb") as handle:
                handle.write(payload)
            parsed = self.parser.parse_file(saved_path, subject_name=subject_name, manual_description=manual_description)
            results.append(self._persist_parsed_source(session, parsed))
        session.commit()
        return results

    def import_manual_text(self, session: Session, text: str, subject_name: str, title: str) -> ImportResult:
        parsed = self.parser.parse_manual_text(text=text, subject_name=subject_name, title=title)
        existing = session.exec(select(Source).where(Source.file_hash == parsed.file_hash)).first()
        if existing:
            return ImportResult(source=existing, skipped=True, reason="同内容手工记录已存在")
        result = self._persist_parsed_source(session, parsed)
        session.commit()
        return result

    def delete_source(self, session: Session, source_id: int) -> bool:
        source = session.get(Source, source_id)
        if source is None:
            return False
        if source.file_path:
            path = Path(source.file_path)
            if path.exists() and settings.upload_dir in path.parents:
                path.unlink(missing_ok=True)
        session.delete(source)
        session.commit()
        return True

    def _persist_parsed_source(self, session: Session, parsed: ParsedSource) -> ImportResult:
        source = Source(
            filename=parsed.filename,
            source_type=parsed.source_type,
            file_path=parsed.file_path,
            file_hash=parsed.file_hash,
            subject_name=parsed.subject_name,
            summary=parsed.summary,
            meta_json=dumps_json(parsed.meta),
            updated_at=datetime.utcnow(),
        )
        session.add(source)
        session.flush()

        for index, item in enumerate(parsed.messages):
            keywords = extract_keywords(item.content)
            people = extract_people(item.content, parsed.subject_name)
            message = Message(
                source_id=source.id,
                speaker=item.speaker,
                content=item.content,
                masked_content=build_masked_text(item.content),
                occurred_at=item.occurred_at,
                paragraph_index=index,
                keywords_json=dumps_json(keywords),
                people_json=dumps_json(people),
                updated_at=datetime.utcnow(),
            )
            session.add(message)
            session.flush()
            session.add(
                SearchDocument(
                    entity_type=ENTITY_MESSAGE,
                    entity_id=message.id,
                    source_id=source.id,
                    person_name=parsed.subject_name,
                    title=item.speaker or parsed.filename,
                    content=item.content,
                    occurred_at=item.occurred_at,
                )
            )

        bundle = self.extractor.extract(source.id, parsed)
        self._persist_bundle(session, source, bundle)
        session.flush()
        return ImportResult(source=source)

    def _persist_bundle(self, session: Session, source: Source, bundle: ExtractionBundle) -> None:
        for trait in bundle.traits:
            trait.masked_content = build_masked_text(trait.evidence)
            trait.updated_at = datetime.utcnow()
            session.add(trait)
            session.flush()
            self._add_search_doc(session, source.subject_name, source.id, ENTITY_TRAIT, trait.id, trait.trait, trait.evidence, None)
            self.evidence_service.ensure_entity_links(session, ENTITY_TRAIT, trait)

        for preference in bundle.preferences:
            preference.masked_content = build_masked_text(preference.evidence)
            preference.updated_at = datetime.utcnow()
            session.add(preference)
            session.flush()
            content = f"{preference.item} {preference.polarity} {preference.evidence}"
            self._add_search_doc(session, source.subject_name, source.id, ENTITY_PREFERENCE, preference.id, preference.item, content, preference.occurred_at)
            self.evidence_service.ensure_entity_links(session, ENTITY_PREFERENCE, preference)

        for quote in bundle.quotes:
            quote.masked_content = build_masked_text(quote.content)
            quote.updated_at = datetime.utcnow()
            session.add(quote)
            session.flush()
            self._add_search_doc(session, quote.person_name, source.id, ENTITY_QUOTE, quote.id, quote.speaker or "原话", quote.content, quote.occurred_at)
            self.evidence_service.ensure_entity_links(session, ENTITY_QUOTE, quote)

        for memory in bundle.memories:
            memory.masked_content = build_masked_text(memory.content)
            memory.event_time = memory.occurred_at
            memory.updated_at = datetime.utcnow()
            session.add(memory)
            session.flush()
            self._add_search_doc(session, memory.person_name, source.id, ENTITY_MEMORY, memory.id, memory.title, memory.content, memory.occurred_at)
            self.evidence_service.ensure_entity_links(session, ENTITY_MEMORY, memory)

        for event in bundle.timeline_events:
            event.masked_content = build_masked_text(event.content)
            event.updated_at = datetime.utcnow()
            session.add(event)
            session.flush()
            occurred_at = datetime.combine(event.event_date, datetime.min.time()) if event.event_date else None
            self._add_search_doc(session, event.person_name, source.id, ENTITY_TIMELINE, event.id, event.title, event.content, occurred_at)
            self.evidence_service.ensure_entity_links(session, ENTITY_TIMELINE, event)

    @staticmethod
    def _add_search_doc(
        session: Session,
        person_name: str,
        source_id: int,
        entity_type: str,
        entity_id: Optional[int],
        title: Optional[str],
        content: str,
        occurred_at: Optional[datetime],
    ) -> None:
        if entity_id is None:
            return
        session.add(
            SearchDocument(
                entity_type=entity_type,
                entity_id=entity_id,
                source_id=source_id,
                person_name=person_name,
                title=title,
                content=content,
                occurred_at=occurred_at,
            )
        )


def _is_valid_image(data: bytes) -> bool:
    """Validate image via magic bytes (JPEG: FF D8 FF, PNG: 89 50 4E 47)."""
    if len(data) < 8:
        return False
    if data[0:3] == b"\xff\xd8\xff":
        return True
    if data[0:8] == b"\x89PNG\r\n\x1a\n":
        return True
    return False


def _is_valid_pdf(data: bytes) -> bool:
    """Validate PDF via magic bytes (%PDF)."""
    return data.startswith(b"%PDF")
