from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlmodel import Session, select

from weiren.config import settings
from weiren.models import ExportRecord, Memory, Preference, QARecord, Quote, TimelineEvent, Trait
from weiren.services.evidence_service import EvidenceService
from weiren.services.settings_service import SettingsService
from weiren.utils.privacy import build_masked_text
from weiren.utils.text import loads_json


class ExportService:
    def __init__(self) -> None:
        self.evidence_service = EvidenceService()
        self.settings_service = SettingsService()
        self.export_dir = settings.data_dir / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_profile_markdown(
        self,
        session: Session,
        subject_name: str,
        include_evidence: bool,
        masked: bool,
        confirmed_only: bool,
    ) -> Path:
        lines = [f"# {subject_name} 资料卡", ""]
        traits = self._filter_confirmed(session.exec(select(Trait).where(Trait.person_name == subject_name)).all(), confirmed_only)
        preferences = self._filter_confirmed(session.exec(select(Preference).where(Preference.person_name == subject_name)).all(), confirmed_only)
        quotes = self._filter_confirmed(session.exec(select(Quote).where(Quote.person_name == subject_name)).all(), confirmed_only)
        lines.append("## 人物特征")
        lines.extend([f"- {item.trait}: {self._render_text(item.evidence, item.masked_content, masked)}" for item in traits] or ["- 无"])
        lines.append("")
        lines.append("## 偏好厌恶")
        lines.extend([f"- [{item.polarity}] {item.item}: {self._render_text(item.evidence, item.masked_content, masked)}" for item in preferences] or ["- 无"])
        lines.append("")
        lines.append("## 典型原话")
        lines.extend([f"- {self._render_text(item.content, item.masked_content, masked)}" for item in quotes[:12]] or ["- 无"])
        lines.append("")
        if include_evidence:
            lines.extend(self._append_evidence_block(session, "trait", traits, masked))
            lines.extend(self._append_evidence_block(session, "preference", preferences, masked))
            lines.extend(self._append_evidence_block(session, "quote", quotes, masked))
        path = self._write_markdown(subject_name, "profile", "\n".join(lines))
        self._log_export(session, "profile", subject_name, include_evidence, masked, confirmed_only, path)
        return path

    def export_timeline_markdown(self, session: Session, subject_name: str, include_evidence: bool, masked: bool, confirmed_only: bool) -> Path:
        events = self._filter_confirmed(session.exec(select(TimelineEvent).where(TimelineEvent.person_name == subject_name).order_by(TimelineEvent.event_date.asc())).all(), confirmed_only)
        lines = [f"# {subject_name} 时间线", ""]
        lines.extend([
            f"- {item.event_date or '时间未知'} {item.title}: {self._render_text(item.content, item.masked_content, masked)}"
            for item in events
        ] or ["- 无"])
        lines.append("")
        if include_evidence:
            lines.extend(self._append_evidence_block(session, "timeline", events, masked))
        path = self._write_markdown(subject_name, "timeline", "\n".join(lines))
        self._log_export(session, "timeline", subject_name, include_evidence, masked, confirmed_only, path)
        return path

    def export_qa_markdown(self, session: Session, subject_name: str, include_evidence: bool, masked: bool) -> Path:
        records = session.exec(select(QARecord).where(QARecord.subject_name == subject_name).order_by(QARecord.created_at.desc())).all()
        lines = [f"# {subject_name} 固定问答记录", ""]
        for record in records:
            lines.append(f"## 问题：{record.question}")
            lines.append("")
            lines.append(record.answer if not masked else build_masked_text(record.answer, summary_only=False))
            lines.append("")
            if include_evidence:
                for item in loads_json(record.evidence_json, []):
                    text_value = item.get("content", "")
                    if masked:
                        text_value = build_masked_text(text_value, summary_only=False)
                    lines.append(f"- [{item.get('source_filename', '未知来源')}] {text_value}")
                lines.append("")
        if not records:
            lines.append("暂无问答记录。")
        path = self._write_markdown(subject_name, "qa", "\n".join(lines))
        self._log_export(session, "qa", subject_name, include_evidence, masked, False, path)
        return path

    def export_archive_zip(self, session: Session, subject_name: str, include_evidence: bool, masked: bool, confirmed_only: bool) -> Path:
        profile_path = self.export_profile_markdown(session, subject_name, include_evidence, masked, confirmed_only)
        timeline_path = self.export_timeline_markdown(session, subject_name, include_evidence, masked, confirmed_only)
        qa_path = self.export_qa_markdown(session, subject_name, include_evidence, masked)
        archive_path = self.export_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{subject_name}_archive.zip"
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
            archive.write(profile_path, arcname=profile_path.name)
            archive.write(timeline_path, arcname=timeline_path.name)
            archive.write(qa_path, arcname=qa_path.name)
        session.add(
            ExportRecord(
                export_type="zip",
                subject_name=subject_name,
                include_evidence=include_evidence,
                masked=masked,
                confirmed_only=confirmed_only,
                output_path=str(archive_path),
            )
        )
        session.commit()
        return archive_path

    def _append_evidence_block(self, session: Session, entity_type: str, records: list[object], masked: bool) -> list[str]:
        lines = ["", f"## {entity_type} 证据"]
        for record in records[:12]:
            evidence = self.evidence_service.list_evidence(session, entity_type, record.id, demo_mode=masked)
            lines.append(f"### {getattr(record, 'title', getattr(record, 'trait', getattr(record, 'item', '记录')))}")
            for item in evidence[:4]:
                lines.append(f"- [{item.source_filename}/{item.source_type}] {item.raw_text}")
        return lines

    def _write_markdown(self, subject_name: str, export_type: str, content: str) -> Path:
        path = self.export_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{subject_name}_{export_type}.md"
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def _log_export(
        session: Session,
        export_type: str,
        subject_name: str,
        include_evidence: bool,
        masked: bool,
        confirmed_only: bool,
        path: Path,
    ) -> None:
        session.add(
            ExportRecord(
                export_type=export_type,
                subject_name=subject_name,
                include_evidence=include_evidence,
                masked=masked,
                confirmed_only=confirmed_only,
                output_path=str(path),
            )
        )
        session.commit()

    @staticmethod
    def _render_text(text: str, masked_text: str | None, masked: bool) -> str:
        return masked_text if masked and masked_text else text

    @staticmethod
    def _filter_confirmed(records: list[object], confirmed_only: bool) -> list[object]:
        if not confirmed_only:
            return records
        return [record for record in records if getattr(record, "is_confirmed", False)]
