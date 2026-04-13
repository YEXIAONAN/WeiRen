from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

try:
    from weiren.utils.datetime_utils import parse_date_input
except ImportError:  # pragma: no cover - compatibility shim
    from app.utils.datetime_utils import parse_date_input


@dataclass(slots=True)
class QuestionIntent:
    intent: str
    confidence: float
    subject_name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    retrieval_terms: list[str] = field(default_factory=list)
    fuzzy_queries: list[str] = field(default_factory=list)
    entity_types: list[str] = field(default_factory=lambda: ["message", "memory", "quote"])


@dataclass(slots=True)
class IntentRule:
    intent: str
    keywords: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]
    retrieval_terms: tuple[str, ...]
    fuzzy_queries: tuple[str, ...]
    confidence: float
    entity_types: tuple[str, ...] = ("message", "memory", "quote")


DATE_RANGE_PATTERN = re.compile(
    r"(?P<start>20\d{2}-\d{2}-\d{2})(?:\s*(?:到|至|~|—|-|之间到)\s*)(?P<end>20\d{2}-\d{2}-\d{2})"
)
SINGLE_DATE_PATTERN = re.compile(r"20\d{2}-\d{2}-\d{2}")
SUBJECT_PATTERN = re.compile(r"([\u4e00-\u9fa5]{2,4})(?:喜欢|不喜欢|讨厌|说话|称呼|说过|发生|不高兴)")

INTENT_RULES: list[IntentRule] = [
    IntentRule(
        intent="appellation_me",
        keywords=("怎么称呼我", "怎么叫我", "怎么喊我", "如何称呼我"),
        patterns=(re.compile(r"称呼我"), re.compile(r"叫我"), re.compile(r"喊我")),
        retrieval_terms=("你", "名字", "称呼", "叫"),
        fuzzy_queries=("你怎么称呼我", "你一般怎么叫我", "你会怎么喊我"),
        confidence=0.98,
    ),
    IntentRule(
        intent="speech_style",
        keywords=("说话是什么感觉", "说话风格", "说话方式", "说话像什么感觉", "表达风格"),
        patterns=(re.compile(r"说话.*感觉"), re.compile(r"说话.*风格"), re.compile(r"表达.*风格")),
        retrieval_terms=("说", "直接", "别", "为什么", "重点"),
        fuzzy_queries=("她平时说话是什么感觉", "她说话是什么风格", "她说话通常是什么样"),
        confidence=0.95,
    ),
    IntentRule(
        intent="signature_quotes",
        keywords=("哪些最像她风格的话", "像她风格的话", "说过哪些", "原话", "最像她的话"),
        patterns=(re.compile(r"最像.*话"), re.compile(r"说过哪些"), re.compile(r"原话")),
        retrieval_terms=("说", "别", "直接", "明天"),
        fuzzy_queries=("她说过哪些最像她风格的话", "她最像她自己的原话", "最像她的表达"),
        confidence=0.96,
        entity_types=("quote", "message"),
    ),
    IntentRule(
        intent="preference_dislike",
        keywords=("不喜欢什么", "讨厌什么", "厌恶什么", "受不了什么"),
        patterns=(re.compile(r"不喜欢什么"), re.compile(r"讨厌什么"), re.compile(r"受不了什么")),
        retrieval_terms=("不喜欢", "讨厌", "厌恶", "受不了"),
        fuzzy_queries=("她不喜欢什么", "她讨厌什么", "她受不了什么"),
        confidence=0.94,
    ),
    IntentRule(
        intent="preference_like",
        keywords=("喜欢吃什么", "喜欢什么", "爱吃什么", "偏爱什么", "爱喝什么"),
        patterns=(re.compile(r"喜欢.*吃什么"), re.compile(r"爱吃什么"), re.compile(r"(?<!不)喜欢什么")),
        retrieval_terms=("喜欢", "爱吃", "偏爱", "想吃", "爱喝"),
        fuzzy_queries=("她喜欢吃什么", "她爱吃什么", "她喜欢什么东西"),
        confidence=0.94,
    ),
    IntentRule(
        intent="displeasure_trigger",
        keywords=("因为什么不高兴", "为什么不高兴", "通常会因为什么生气", "通常会因为什么烦"),
        patterns=(re.compile(r"因为什么.*不高兴"), re.compile(r"因为什么.*生气"), re.compile(r"因为什么.*烦")),
        retrieval_terms=("不高兴", "生气", "烦", "讨厌", "受不了", "吵架"),
        fuzzy_queries=("她通常会因为什么不高兴", "她一般会因为什么生气", "什么事情容易让她烦"),
        confidence=0.93,
    ),
    IntentRule(
        intent="timeline",
        keywords=("发生过什么", "那段时间发生了什么", "某段时间", "时间里发生了什么", "时间线"),
        patterns=(re.compile(r"发生过什么"), re.compile(r"那段时间"), re.compile(r"时间线")),
        retrieval_terms=("一起", "后来", "那次", "发生", "时间"),
        fuzzy_queries=("我们在某段时间发生过什么", "那段时间发生了什么", "这段时间有什么记录"),
        confidence=0.90,
        entity_types=("memory", "timeline", "message", "quote"),
    ),
    IntentRule(
        intent="persona_profile",
        keywords=("是什么样的人", "是什么样", "性格", "人设", "特点"),
        patterns=(re.compile(r"什么样的人"), re.compile(r"性格"), re.compile(r"人设")),
        retrieval_terms=("很", "总是", "其实", "安静", "直接"),
        fuzzy_queries=("她是什么样的人", "她大概是什么性格", "她平时是什么感觉"),
        confidence=0.86,
    ),
]


class QuestionIntentClassifier:
    def classify(self, question: str, default_subject: Optional[str] = None) -> QuestionIntent:
        content = (question or "").strip()
        if not content:
            return QuestionIntent(intent="unknown", confidence=0.0, subject_name=default_subject)

        subject_name = self._extract_subject(content) or default_subject
        start_date, end_date = self._extract_date_range(content)

        for rule in INTENT_RULES:
            if self._match_rule(content, rule):
                terms = self._merge_terms(rule.retrieval_terms, self._extract_question_terms(content))
                return QuestionIntent(
                    intent=rule.intent,
                    confidence=rule.confidence,
                    subject_name=subject_name,
                    start_date=start_date,
                    end_date=end_date,
                    retrieval_terms=terms,
                    fuzzy_queries=list(rule.fuzzy_queries),
                    entity_types=list(rule.entity_types),
                )

        fallback_terms = self._extract_question_terms(content)
        return QuestionIntent(
            intent="timeline",
            confidence=0.45,
            subject_name=subject_name,
            start_date=start_date,
            end_date=end_date,
            retrieval_terms=fallback_terms or ["发生", "记录"],
            fuzzy_queries=[content],
            entity_types=["memory", "timeline", "message", "quote"],
        )

    @staticmethod
    def _match_rule(question: str, rule: IntentRule) -> bool:
        if any(keyword in question for keyword in rule.keywords):
            return True
        return any(pattern.search(question) for pattern in rule.patterns)

    @staticmethod
    def _extract_subject(question: str) -> Optional[str]:
        match = SUBJECT_PATTERN.search(question)
        if match:
            candidate = match.group(1)
            if candidate.startswith(("她", "他", "我", "你")):
                return None
            if candidate in {"我们", "平时", "某段", "那段", "因为什么", "发生过", "说过哪些", "经常怎么", "通常会"}:
                return None
            if candidate.endswith("什么"):
                return None
            return candidate
        return None

    @staticmethod
    def _extract_date_range(question: str) -> tuple[Optional[date], Optional[date]]:
        match = DATE_RANGE_PATTERN.search(question)
        if match:
            return parse_date_input(match.group("start")), parse_date_input(match.group("end"))
        singles = SINGLE_DATE_PATTERN.findall(question)
        if len(singles) == 1:
            single = parse_date_input(singles[0])
            return single, single
        return None, None

    @staticmethod
    def _extract_question_terms(question: str) -> list[str]:
        tokens = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", question)
        stopwords = {"她", "我们", "什么", "怎么", "哪些", "通常", "平时", "某段时间", "发生", "感觉"}
        return [token for token in tokens if token not in stopwords][:8]

    @staticmethod
    def _merge_terms(base_terms: tuple[str, ...], extra_terms: list[str]) -> list[str]:
        merged: list[str] = []
        for term in list(base_terms) + extra_terms:
            clean = term.strip()
            if clean and clean not in merged:
                merged.append(clean)
        return merged
