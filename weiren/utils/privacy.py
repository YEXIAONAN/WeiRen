from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Protocol


PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
SOCIAL_PATTERN = re.compile(r"(?:@|微信|vx|v信|qq|QQ|微博|小红书|抖音)[:：\s]*([A-Za-z0-9_\-.]{4,32})")
LOCATION_PATTERN = re.compile(
    r"([\u4e00-\u9fa5]{2,12}(?:省|市|区|县|镇|乡|村|路|街|巷|站|大厦|商场|学校|大学|医院|公园|广场))"
)
GENERIC_NAME_PATTERN = re.compile(r"(?<![\u4e00-\u9fa5])([\u4e00-\u9fa5]{2,4})(?![\u4e00-\u9fa5])")


class SettingsLike(Protocol):
    demo_mode: bool
    mask_real_name: bool
    mask_phone: bool
    mask_location: bool
    mask_social: bool


@dataclass(slots=True)
class PrivacyOptions:
    demo_mode: bool = False
    mask_real_name: bool = True
    mask_phone: bool = True
    mask_location: bool = True
    mask_social: bool = True


def options_from_settings(settings: SettingsLike | None) -> PrivacyOptions:
    if settings is None:
        return PrivacyOptions()
    return PrivacyOptions(
        demo_mode=bool(getattr(settings, "demo_mode", False)),
        mask_real_name=bool(getattr(settings, "mask_real_name", True)),
        mask_phone=bool(getattr(settings, "mask_phone", True)),
        mask_location=bool(getattr(settings, "mask_location", True)),
        mask_social=bool(getattr(settings, "mask_social", True)),
    )


def build_masked_text(
    text: str,
    settings: SettingsLike | None = None,
    *,
    summary_only: bool | None = None,
    custom_names: Iterable[str] | None = None,
) -> str:
    options = options_from_settings(settings)
    content = (text or "").strip()
    if not content:
        return ""

    masked = content
    names = [name.strip() for name in (custom_names or []) if name and name.strip()]
    if options.mask_real_name:
        for name in sorted(set(names), key=len, reverse=True):
            masked = masked.replace(name, _mask_name(name))
        masked = _mask_detected_names(masked)
    if options.mask_phone:
        masked = PHONE_PATTERN.sub("[手机号]", masked)
    if options.mask_social:
        masked = SOCIAL_PATTERN.sub(lambda match: match.group(0).replace(match.group(1), "[账号]"), masked)
    if options.mask_location:
        masked = LOCATION_PATTERN.sub("[地点]", masked)

    should_summary = options.demo_mode if summary_only is None else summary_only
    if should_summary:
        return summarize_text(masked)
    return masked


def summarize_text(text: str, max_length: int = 42) -> str:
    content = re.sub(r"\s+", " ", (text or "").strip())
    if len(content) <= max_length:
        return content
    return content[:max_length].rstrip() + "..."


def _mask_name(name: str) -> str:
    if len(name) <= 1:
        return "[姓名]"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def _mask_detected_names(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        candidate = match.group(1)
        if candidate in {"我们", "你们", "他们", "自己", "已经", "因为", "所以", "如果", "还是"}:
            return candidate
        return _mask_name(candidate)

    return GENERIC_NAME_PATTERN.sub(replace, text)
