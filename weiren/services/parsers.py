from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import fitz
from PIL import ExifTags, Image

from weiren.utils.text import parse_datetime, parse_speaker_line, split_paragraphs

SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".pdf", ".jpg", ".jpeg", ".png"}

EXIF_DATETIME_TAGS = {
    key for key, value in ExifTags.TAGS.items() if value in {"DateTime", "DateTimeOriginal", "DateTimeDigitized"}
}


@dataclass(slots=True)
class ParsedMessage:
    content: str
    speaker: Optional[str] = None
    occurred_at: Optional[datetime] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedSource:
    filename: str
    source_type: str
    file_hash: str
    file_path: Optional[str]
    summary: str
    subject_name: str
    meta: dict[str, Any]
    messages: list[ParsedMessage]


class ParserError(ValueError):
    pass


class SourceParser:
    @staticmethod
    def detect_type(path: Path) -> str:
        extension = path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ParserError(f"不支持的文件类型: {extension}")
        return extension.lstrip(".")

    @staticmethod
    def calculate_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def parse_file(self, path: Path, subject_name: str, manual_description: str = "") -> ParsedSource:
        source_type = self.detect_type(path)
        data = path.read_bytes()
        file_hash = self.calculate_hash(data)
        parser = getattr(self, f"_parse_{source_type if source_type != 'jpeg' else 'jpg'}", None)
        if parser is None:
            raise ParserError(f"未找到解析器: {source_type}")
        messages, meta = parser(path)
        if manual_description.strip():
            messages.append(ParsedMessage(content=manual_description.strip(), speaker="补充说明"))
        summary = f"{path.name} 导入 {len(messages)} 条片段"
        return ParsedSource(
            filename=path.name,
            source_type=source_type,
            file_hash=file_hash,
            file_path=str(path),
            summary=summary,
            subject_name=subject_name,
            meta=meta,
            messages=messages,
        )

    def parse_manual_text(self, text: str, subject_name: str, title: str = "手工输入") -> ParsedSource:
        payload = text.encode("utf-8")
        file_hash = self.calculate_hash(payload)
        paragraphs = split_paragraphs(text)
        messages = [ParsedMessage(content=paragraph, occurred_at=parse_datetime(paragraph)) for paragraph in paragraphs]
        if not messages:
            raise ParserError("手工输入内容为空")
        return ParsedSource(
            filename=f"{title}.txt",
            source_type="manual",
            file_hash=file_hash,
            file_path=None,
            summary=f"手工录入 {len(messages)} 条片段",
            subject_name=subject_name,
            meta={"title": title},
            messages=messages,
        )

    def _parse_txt(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        return self._parse_textlike(path)

    def _parse_md(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        return self._parse_textlike(path)

    def _parse_textlike(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        text = path.read_text(encoding="utf-8")
        paragraphs = split_paragraphs(text)
        messages: list[ParsedMessage] = []
        for paragraph in paragraphs:
            speaker, content, occurred_at = parse_speaker_line(paragraph)
            messages.append(ParsedMessage(content=content, speaker=speaker, occurred_at=occurred_at))
        return messages, {"paragraph_count": len(messages)}

    def _parse_json(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            rows = data.get("messages") or data.get("items") or []
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        messages = self._parse_chat_rows(rows)
        return messages, {"record_count": len(messages)}

    def _parse_csv(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        messages = self._parse_chat_rows(rows)
        return messages, {"record_count": len(messages)}

    def _parse_chat_rows(self, rows: list[dict[str, Any]]) -> list[ParsedMessage]:
        messages: list[ParsedMessage] = []
        for row in rows:
            content = str(row.get("content") or row.get("message") or row.get("text") or "").strip()
            if not content:
                continue
            speaker = str(row.get("speaker") or row.get("role") or row.get("name") or "").strip() or None
            raw_time = str(row.get("timestamp") or row.get("time") or row.get("date") or "")
            occurred_at = parse_datetime(raw_time)
            messages.append(ParsedMessage(content=content, speaker=speaker, occurred_at=occurred_at, extra=dict(row)))
        if not messages:
            raise ParserError("JSON/CSV 中没有可导入的聊天内容")
        return messages

    def _parse_pdf(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        messages: list[ParsedMessage] = []
        with fitz.open(path) as document:
            for page_index, page in enumerate(document):
                text = page.get_text("text")
                for paragraph in split_paragraphs(text):
                    messages.append(
                        ParsedMessage(
                            content=paragraph,
                            occurred_at=parse_datetime(paragraph),
                            extra={"page": page_index + 1},
                        )
                    )
        if not messages:
            raise ParserError("PDF 没有提取到可用文本")
        return messages, {"page_count": len(messages)}

    def _parse_jpg(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        return self._parse_image(path)

    def _parse_png(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        return self._parse_image(path)

    def _parse_image(self, path: Path) -> tuple[list[ParsedMessage], dict[str, Any]]:
        meta: dict[str, Any] = {"width": None, "height": None, "captured_at": None}
        occurred_at: Optional[datetime] = None
        with Image.open(path) as image:
            meta["width"], meta["height"] = image.size
            exif = image.getexif()
            if exif:
                for tag in EXIF_DATETIME_TAGS:
                    raw_value = exif.get(tag)
                    if raw_value:
                        raw_text = str(raw_value).replace(":", "-", 2)
                        try:
                            occurred_at = datetime.strptime(raw_text, "%Y-%m-%d %H:%M:%S")
                            meta["captured_at"] = occurred_at.isoformat()
                            break
                        except ValueError:
                            continue
        if occurred_at is None:
            occurred_at = datetime.fromtimestamp(path.stat().st_mtime)
            meta["captured_at"] = occurred_at.isoformat()
        description = f"图片 {path.name}，分辨率 {meta['width']}x{meta['height']}，记录时间 {occurred_at.strftime('%Y-%m-%d %H:%M:%S')}"
        return [ParsedMessage(content=description, occurred_at=occurred_at, speaker="图片元数据")], meta
