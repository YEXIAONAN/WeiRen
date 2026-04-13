from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def parse_date_input(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_datetime(value: Optional[datetime]) -> str:
    if not value:
        return "未标注时间"
    return value.strftime("%Y-%m-%d %H:%M")


def format_date(value: Optional[date]) -> str:
    if not value:
        return "时间未知"
    return value.strftime("%Y-%m-%d")
