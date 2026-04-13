from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime
from typing import Iterable, Optional

import jieba
import jieba.analyse

STOPWORDS = {
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "真的",
    "就是",
    "还是",
    "已经",
    "一个",
    "没有",
    "什么",
    "时候",
    "觉得",
    "一下",
    "但是",
    "因为",
    "如果",
    "然后",
    "不是",
    "自己",
    "她",
    "他",
    "我",
}

DATE_PATTERNS = [
    re.compile(r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?"),
    re.compile(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"),
]

SPEAKER_PATTERN = re.compile(
    r"^(?:(?P<date>20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)\s*)?(?P<speaker>[\u4e00-\u9fa5A-Za-z0-9_]{1,20})[:：]\s*(?P<content>.+)$"
)

CHINESE_NAME_PATTERN = re.compile(r"(?<![\u4e00-\u9fa5])([\u4e00-\u9fa5]{2,4})(?:说|觉得|喜欢|讨厌|生气|哭|笑|答应|拒绝|陪)")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def split_paragraphs(text: str) -> list[str]:
    chunks = [normalize_text(part) for part in re.split(r"\n\s*\n+", text.replace("\r\n", "\n"))]
    return [chunk for chunk in chunks if chunk]


def parse_datetime(text: str, reference: Optional[datetime] = None) -> Optional[datetime]:
    base = reference or datetime.utcnow()
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        parts = match.groupdict()
        year = int(parts.get("year") or base.year)
        month = int(parts["month"])
        day = int(parts["day"])
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return None


def parse_speaker_line(line: str, reference: Optional[datetime] = None) -> tuple[Optional[str], str, Optional[datetime]]:
    match = SPEAKER_PATTERN.match(line.strip())
    if not match:
        return None, normalize_text(line), parse_datetime(line, reference)
    occurred_at = parse_datetime(match.group("date") or "", reference) or parse_datetime(line, reference)
    return match.group("speaker"), normalize_text(match.group("content")), occurred_at


def extract_people(text: str, subject_name: str) -> list[str]:
    names = {subject_name}
    for name in CHINESE_NAME_PATTERN.findall(text):
        if len(name) >= 2:
            names.add(name)
    if "妈妈" in text:
        names.add("妈妈")
    if "朋友" in text:
        names.add("朋友")
    return sorted(names)


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    keywords = [token for token in jieba.analyse.extract_tags(text, topK=limit * 2) if token not in STOPWORDS]
    if keywords:
        return keywords[:limit]
    tokens = [token.strip() for token in jieba.cut(text) if len(token.strip()) > 1 and token.strip() not in STOPWORDS]
    counts = Counter(tokens)
    return [item for item, _count in counts.most_common(limit)]


def highlight_terms(text: str, terms: Iterable[str]) -> str:
    highlighted = text
    for term in sorted({term for term in terms if term}, key=len, reverse=True):
        highlighted = re.sub(re.escape(term), f"<mark>{term}</mark>", highlighted, flags=re.IGNORECASE)
    return highlighted


def dumps_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=_json_default)


def loads_json(raw: str, default: object) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)
