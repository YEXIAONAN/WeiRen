from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from weiren.models import Memory, Preference, Quote, TimelineEvent, Trait
from weiren.services.parsers import ParsedMessage, ParsedSource
from weiren.utils.text import extract_keywords, extract_people, normalize_text

LIKE_PATTERNS = [
    re.compile(r"(?:喜欢|爱吃|偏爱|最爱|想吃|常点)(?P<item>[\u4e00-\u9fa5A-Za-z0-9、,，]{1,20})"),
]
DISLIKE_PATTERNS = [
    re.compile(r"(?:讨厌|不喜欢|受不了|厌恶|最烦)(?P<item>[\u4e00-\u9fa5A-Za-z0-9、,，]{1,20})"),
]
TRAIT_PATTERNS = [
    re.compile(r"(?:她|他)(?:很|总是|看起来|其实|是个|有点)(?P<trait>[\u4e00-\u9fa5]{2,10})"),
    re.compile(r"(?P<trait>[\u4e00-\u9fa5]{2,10})(?:的人|性格)"),
]
QUOTE_PATTERN = re.compile(r"[“\"](?P<quote>[^”\"]{4,80})[”\"]")
CONFLICT_WORDS = {"吵架", "冷战", "争执", "闹翻", "误会", "生气"}
SHARED_WORDS = {"我们", "一起", "那次", "后来", "第一次", "每次"}


@dataclass(slots=True)
class ExtractionBundle:
    preferences: list[Preference] = field(default_factory=list)
    traits: list[Trait] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)
    memories: list[Memory] = field(default_factory=list)
    timeline_events: list[TimelineEvent] = field(default_factory=list)


class RuleBasedExtractor:
    def extract(self, source_id: int, parsed_source: ParsedSource) -> ExtractionBundle:
        bundle = ExtractionBundle()
        seen_preferences: set[tuple[str, str]] = set()
        seen_traits: set[str] = set()
        seen_quotes: set[str] = set()
        seen_memories: set[str] = set()
        seen_events: set[str] = set()

        for message in parsed_source.messages:
            content = normalize_text(message.content)
            if not content:
                continue
            occurred_at = message.occurred_at
            person_name = self._resolve_person_name(parsed_source.subject_name, message)

            for preference in self._extract_preferences(source_id, person_name, content, occurred_at):
                key = (preference.polarity, preference.item)
                if key not in seen_preferences:
                    seen_preferences.add(key)
                    bundle.preferences.append(preference)

            for trait in self._extract_traits(source_id, person_name, content):
                if trait.trait not in seen_traits:
                    seen_traits.add(trait.trait)
                    bundle.traits.append(trait)

            for quote in self._extract_quotes(source_id, person_name, message):
                if quote.content not in seen_quotes:
                    seen_quotes.add(quote.content)
                    bundle.quotes.append(quote)

            memory = self._extract_memory(source_id, person_name, content, occurred_at)
            if memory and memory.content not in seen_memories:
                seen_memories.add(memory.content)
                bundle.memories.append(memory)

            event = self._extract_timeline_event(source_id, person_name, content, occurred_at)
            if event and event.content not in seen_events:
                seen_events.add(event.content)
                bundle.timeline_events.append(event)

        return bundle

    def _resolve_person_name(self, subject_name: str, message: ParsedMessage) -> str:
        if message.speaker and message.speaker not in {"我", "自己", "补充说明", "图片元数据"}:
            return message.speaker
        people = extract_people(message.content, subject_name)
        return people[0] if people else subject_name

    def _extract_preferences(
        self,
        source_id: int,
        person_name: str,
        content: str,
        occurred_at: Optional[datetime],
    ) -> Iterable[Preference]:
        for pattern in LIKE_PATTERNS:
            for match in pattern.finditer(content):
                item = self._clean_entity(match.group("item"))
                if item:
                    yield Preference(
                        source_id=source_id,
                        person_name=person_name,
                        item=item,
                        polarity="like",
                        evidence=content,
                        occurred_at=occurred_at,
                    )
        for pattern in DISLIKE_PATTERNS:
            for match in pattern.finditer(content):
                item = self._clean_entity(match.group("item"))
                if item:
                    yield Preference(
                        source_id=source_id,
                        person_name=person_name,
                        item=item,
                        polarity="dislike",
                        evidence=content,
                        occurred_at=occurred_at,
                    )

    def _extract_traits(self, source_id: int, person_name: str, content: str) -> Iterable[Trait]:
        for pattern in TRAIT_PATTERNS:
            for match in pattern.finditer(content):
                trait = self._clean_entity(match.group("trait"))
                if trait:
                    yield Trait(source_id=source_id, person_name=person_name, trait=trait, evidence=content)

    def _extract_quotes(self, source_id: int, person_name: str, message: ParsedMessage) -> Iterable[Quote]:
        if message.speaker and message.speaker not in {"我", "补充说明", "图片元数据"}:
            yield Quote(
                source_id=source_id,
                person_name=person_name,
                speaker=message.speaker,
                content=message.content,
                occurred_at=message.occurred_at,
            )
        for match in QUOTE_PATTERN.finditer(message.content):
            quote = self._clean_quote(match.group("quote"))
            if quote:
                yield Quote(
                    source_id=source_id,
                    person_name=person_name,
                    speaker=message.speaker,
                    content=quote,
                    occurred_at=message.occurred_at,
                )

    def _extract_memory(
        self,
        source_id: int,
        person_name: str,
        content: str,
        occurred_at: Optional[datetime],
    ) -> Optional[Memory]:
        if not any(word in content for word in SHARED_WORDS):
            return None
        keywords = extract_keywords(content, limit=3)
        title = " / ".join(keywords[:2]) if keywords else content[:18]
        confidence = 0.9 if any(word in content for word in CONFLICT_WORDS) else 0.7
        return Memory(
            source_id=source_id,
            person_name=person_name,
            title=title[:200],
            content=content,
            occurred_at=occurred_at,
            confidence=confidence,
        )

    def _extract_timeline_event(
        self,
        source_id: int,
        person_name: str,
        content: str,
        occurred_at: Optional[datetime],
    ) -> Optional[TimelineEvent]:
        if occurred_at is None and not any(word in content for word in SHARED_WORDS.union(CONFLICT_WORDS)):
            return None
        keywords = extract_keywords(content, limit=4)
        title = " / ".join(keywords[:2]) if keywords else content[:18]
        event_date = occurred_at.date() if occurred_at else None
        return TimelineEvent(
            source_id=source_id,
            person_name=person_name,
            event_date=event_date,
            title=title[:200],
            content=content,
            evidence=content,
        )

    @staticmethod
    def _clean_entity(value: str) -> str:
        cleaned = re.split(r"[，。；！!？?]", value)[0]
        cleaned = re.split(r"(?:和|跟|但|却|而且)", cleaned)[0]
        return cleaned.strip(" ：:,.，。；;!！?？\"“”")[:50]

    @staticmethod
    def _clean_quote(value: str) -> str:
        return value.strip("\"“” ")[:120]
