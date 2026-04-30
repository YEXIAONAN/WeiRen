from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Iterable, Optional, Sequence

from sqlalchemy import text
from sqlmodel import Session, select

from weiren.models import Message, Preference, Quote, Source, TimelineEvent, Trait
from weiren.services.question_intent_rules import QuestionIntent, QuestionIntentClassifier
from weiren.utils.fuzzy_utils import FuzzyMatch, best_similarity, rank_similar_texts
from weiren.services.llm_service import LLMService
from weiren.utils.text import extract_keywords


INSUFFICIENT_ANSWER = "现有资料不足以确认。"
NEGATIVE_HINTS = ("不喜欢", "讨厌", "受不了", "不高兴", "生气", "烦", "吵架", "冷战")


@dataclass(slots=True)
class QAEvidence:
    entity_type: str
    source_id: int
    source_filename: str
    title: str
    content: str
    occurred_at: Optional[datetime] = None
    score: float = 0.0

    @property
    def display(self) -> str:
        time_label = self.occurred_at.strftime("%Y-%m-%d") if self.occurred_at else "时间未知"
        title = self.title or self.entity_type
        return f"[{self.source_filename}｜{title}｜{time_label}] {self.content}"


@dataclass(slots=True)
class QAResponse:
    question: str
    intent: str
    answer: str
    evidence: list[str] = field(default_factory=list)
    evidence_sources: list[QAEvidence] = field(default_factory=list)


class QAService:
    def __init__(self) -> None:
        self.classifier = QuestionIntentClassifier()
        self.llm = LLMService()

    def answer(self, session: Session, question: str, default_subject: str, llm_enabled: bool = False) -> QAResponse:
        intent = self.classifier.classify(question, default_subject=default_subject)
        subject_name = intent.subject_name or default_subject
        handler = getattr(self, f"_handle_{intent.intent}", self._handle_unknown)
        answer, evidence_sources = handler(session, question, subject_name, intent)
        if not evidence_sources and answer != INSUFFICIENT_ANSWER:
            answer = INSUFFICIENT_ANSWER

        if llm_enabled and evidence_sources:
            llm_answer = self._llm_answer(question, evidence_sources)
            if llm_answer:
                answer = llm_answer

        return QAResponse(
            question=question,
            intent=intent.intent,
            answer=answer,
            evidence=[item.display for item in evidence_sources],
            evidence_sources=evidence_sources,
        )

    def _llm_answer(self, question: str, evidence_sources: list[QAEvidence]) -> Optional[str]:
        evidence_lines = []
        for item in evidence_sources[:6]:
            time_tag = item.occurred_at.strftime("%Y-%m-%d") if item.occurred_at else ""
            source_info = f"[{item.source_filename}"
            if time_tag:
                source_info += f" | {time_tag}"
            source_info += "]"
            evidence_lines.append(f"{source_info} {item.content}")
        return self.llm.answer_from_evidence(question, "\n".join(evidence_lines))

    def _handle_unknown(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        del session, question, subject_name, intent
        return INSUFFICIENT_ANSWER, []

    def _handle_preference_like(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        records = session.exec(
            select(Preference).where(Preference.person_name == subject_name, Preference.polarity == "like")
        ).all()
        records = [record for record in records if not self._contains_negative_cue(record.evidence)]
        evidence = [
            self._make_evidence_from_record(session, record.source_id, "preference", record.item, record.evidence, record.occurred_at)
            for record in records
        ]
        evidence = [item for item in evidence if item]
        if not evidence:
            evidence = self._retrieve_text_evidence(session, question, subject_name, intent, minimum_score=32.0)
        items = [record.item for record in records if record.item]
        if not items and not evidence:
            return INSUFFICIENT_ANSWER, []
        if not items:
            items = self._extract_preference_items_from_evidence(evidence, positive=True)
        if not items:
            return INSUFFICIENT_ANSWER, evidence[:4]
        answer = f"现有记录里，她偏喜欢：{'、'.join(self._top_unique(items, 5))}。"
        return answer, evidence[:5]

    def _handle_preference_dislike(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        records = session.exec(
            select(Preference).where(Preference.person_name == subject_name, Preference.polarity == "dislike")
        ).all()
        records = [record for record in records if self._contains_negative_cue(record.evidence)]
        evidence = [
            self._make_evidence_from_record(session, record.source_id, "preference", record.item, record.evidence, record.occurred_at)
            for record in records
        ]
        evidence = [item for item in evidence if item]
        if not evidence:
            evidence = self._retrieve_text_evidence(session, question, subject_name, intent, minimum_score=32.0)
        items = [record.item for record in records if record.item]
        if not items:
            items = self._extract_preference_items_from_evidence(evidence, positive=False)
        if not items:
            return INSUFFICIENT_ANSWER, evidence[:4]
        answer = f"现有记录里，她明确表示不喜欢：{'、'.join(self._top_unique(items, 5))}。"
        return answer, evidence[:5]

    def _handle_speech_style(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        quotes = self._quotes_for_subject(session, subject_name)
        evidence = [
            self._make_evidence_from_record(session, quote.source_id, "quote", quote.speaker or "原话", quote.content, quote.occurred_at)
            for quote in quotes
        ]
        evidence = [item for item in evidence if item and self._is_meaningful_text(item.content)]
        if len(evidence) < 2:
            evidence.extend(self._retrieve_text_evidence(session, question, subject_name, intent, minimum_score=38.0))
            evidence = self._deduplicate_evidence(evidence)
        if not evidence:
            return INSUFFICIENT_ANSWER, []

        tone_tags = self._infer_speech_tone([item.content for item in evidence])
        if not tone_tags:
            return INSUFFICIENT_ANSWER, evidence[:4]
        answer = f"从现有原话看，她说话通常给人的感觉是{'、'.join(tone_tags)}。"
        return answer, evidence[:5]

    def _handle_appellation_me(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        messages = session.exec(select(Message).where(Message.speaker == subject_name).order_by(Message.occurred_at.desc())).all()
        appellations: list[str] = []
        evidence: list[QAEvidence] = []
        for message in messages:
            hits = self._extract_appellations(message.content)
            if not hits:
                continue
            appellations.extend(hits)
            item = self._make_evidence_from_record(session, message.source_id, "message", message.speaker or "消息", message.content, message.occurred_at)
            if item:
                evidence.append(item)
        if not evidence:
            evidence = self._retrieve_text_evidence(session, question, subject_name, intent, minimum_score=42.0)
            for item in evidence:
                appellations.extend(self._extract_appellations(item.content))
        if not appellations:
            return INSUFFICIENT_ANSWER, evidence[:4]
        counts = Counter(appellations)
        names = [name for name, _count in counts.most_common(4)]
        answer = f"现有资料里，她更常这样称呼你：{'、'.join(names)}。"
        return answer, self._deduplicate_evidence(evidence)[:5]

    def _handle_signature_quotes(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        quotes = self._quotes_for_subject(session, subject_name)
        evidence = [
            self._make_evidence_from_record(session, quote.source_id, "quote", quote.speaker or "原话", quote.content, quote.occurred_at)
            for quote in quotes
        ]
        evidence = [item for item in evidence if item and self._is_meaningful_text(item.content)]
        if evidence:
            ranked = rank_similar_texts(
                query=question,
                entries=[(item.content, item) for item in evidence],
                extra_queries=intent.fuzzy_queries,
                limit=5,
                threshold=25.0,
            )
            selected = [match.payload for match in ranked if isinstance(match.payload, QAEvidence)]
            evidence = self._deduplicate_evidence(selected) or evidence[:5]
        else:
            evidence = self._retrieve_text_evidence(session, question, subject_name, intent, minimum_score=40.0)
        if not evidence:
            return INSUFFICIENT_ANSWER, []
        answer = "现有记录里，最能体现她说话风格的原话有：" + "；".join(item.content for item in evidence[:3])
        return answer, evidence[:5]

    def _handle_timeline(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        statement = select(TimelineEvent).where(TimelineEvent.person_name == subject_name)
        if intent.start_date:
            statement = statement.where(TimelineEvent.event_date >= intent.start_date)
        if intent.end_date:
            statement = statement.where(TimelineEvent.event_date <= intent.end_date)
        events = session.exec(statement.order_by(TimelineEvent.event_date.desc(), TimelineEvent.id.desc())).all()
        evidence = [
            self._make_evidence_from_record(
                session,
                event.source_id,
                "timeline",
                event.title,
                event.content,
                datetime.combine(event.event_date, time.min) if event.event_date else None,
            )
            for event in events
        ]
        evidence = [item for item in evidence if item and self._is_meaningful_text(item.content)]
        if not evidence:
            evidence = self._retrieve_text_evidence(session, question, subject_name, intent, minimum_score=34.0)
        if not evidence:
            return INSUFFICIENT_ANSWER, []
        summary = []
        for item in evidence[:4]:
            prefix = item.occurred_at.strftime("%Y-%m-%d") if item.occurred_at else "时间未知"
            summary_text = item.content.strip().replace("\n", " ")
            if len(summary_text) > 24:
                summary_text = summary_text[:24] + "..."
            summary.append(f"{prefix} {summary_text}")
        answer = "现有记录显示，这段时间主要发生过：" + "；".join(summary)
        return answer, evidence[:6]

    def _handle_persona_profile(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        traits = session.exec(select(Trait).where(Trait.person_name == subject_name)).all()
        evidence = [
            self._make_evidence_from_record(session, trait.source_id, "trait", trait.trait, trait.evidence, None)
            for trait in traits
        ]
        evidence = [item for item in evidence if item]
        if len(evidence) < 2:
            evidence.extend(self._retrieve_text_evidence(session, question, subject_name, intent, minimum_score=30.0))
            evidence = self._deduplicate_evidence(evidence)
        if not evidence:
            return INSUFFICIENT_ANSWER, []
        traits_counter = Counter(trait.trait for trait in traits if trait.trait)
        if not traits_counter:
            traits_counter.update(self._extract_profile_tags([item.content for item in evidence]))
        if not traits_counter:
            return INSUFFICIENT_ANSWER, evidence[:4]
        answer = f"根据现有资料，她更常呈现出{'、'.join(name for name, _count in traits_counter.most_common(4))}这些特征。"
        return answer, evidence[:5]

    def _handle_displeasure_trigger(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
    ) -> tuple[str, list[QAEvidence]]:
        records = session.exec(
            select(Preference).where(Preference.person_name == subject_name, Preference.polarity == "dislike")
        ).all()
        records = [record for record in records if self._contains_negative_cue(record.evidence)]
        evidence = [
            self._make_evidence_from_record(session, record.source_id, "preference", record.item, record.evidence, record.occurred_at)
            for record in records
        ]
        evidence = [item for item in evidence if item]
        negative_quotes = [
            self._make_evidence_from_record(session, quote.source_id, "quote", quote.speaker or "原话", quote.content, quote.occurred_at)
            for quote in self._quotes_for_subject(session, subject_name)
            if self._contains_negative_cue(quote.content)
        ]
        evidence.extend([item for item in negative_quotes if item and self._is_meaningful_text(item.content)])
        evidence.extend(self._retrieve_text_evidence(session, question, subject_name, intent, minimum_score=34.0))
        evidence = self._deduplicate_evidence(evidence)
        reasons = self._extract_negative_reasons(evidence)
        if not reasons:
            return INSUFFICIENT_ANSWER, evidence[:4]
        answer = f"现有记录里，她通常会因为{'、'.join(self._top_unique(reasons, 5))}而不高兴。"
        return answer, evidence[:5]

    def _retrieve_text_evidence(
        self,
        session: Session,
        question: str,
        subject_name: str,
        intent: QuestionIntent,
        minimum_score: float,
    ) -> list[QAEvidence]:
        fulltext_hits = self._fts_search(
            session=session,
            subject_name=subject_name,
            retrieval_terms=intent.retrieval_terms,
            entity_types=intent.entity_types,
            start_date=intent.start_date,
            end_date=intent.end_date,
            limit=16,
        )
        if not fulltext_hits:
            return []
        ranked = rank_similar_texts(
            query=question,
            entries=[(item.content, item) for item in fulltext_hits],
            extra_queries=intent.fuzzy_queries,
            limit=8,
            threshold=minimum_score,
        )
        if ranked:
            return self._deduplicate_evidence([match.payload for match in ranked if isinstance(match.payload, QAEvidence)])

        for item in fulltext_hits:
            item.score = best_similarity(item.content, [question, *intent.fuzzy_queries])
        fulltext_hits.sort(key=lambda evidence: evidence.score, reverse=True)
        return [item for item in fulltext_hits if item.score >= minimum_score][:6]

    def _fts_search(
        self,
        session: Session,
        subject_name: str,
        retrieval_terms: Sequence[str],
        entity_types: Sequence[str],
        start_date: Optional[date],
        end_date: Optional[date],
        limit: int,
    ) -> list[QAEvidence]:
        terms = [term.strip().replace('"', ' ') for term in retrieval_terms if term and term.strip()]
        if not terms:
            return []
        source_map = self._source_map(session)
        match_query = " AND ".join(terms[:6])
        params: dict[str, object] = {
            "match_query": match_query,
            "person_name": subject_name,
            "limit": limit,
        }
        entity_placeholders = ", ".join(f":entity_{index}" for index, _item in enumerate(entity_types))
        for index, entity_type in enumerate(entity_types):
            params[f"entity_{index}"] = entity_type

        filters = [
            "sd.person_name = :person_name",
            f"sd.entity_type IN ({entity_placeholders})",
            "search_documents_fts MATCH :match_query",
        ]
        if start_date:
            params["start_at"] = datetime.combine(start_date, time.min)
            filters.append("(sd.occurred_at IS NOT NULL AND sd.occurred_at >= :start_at)")
        if end_date:
            params["end_at"] = datetime.combine(end_date, time.max)
            filters.append("(sd.occurred_at IS NOT NULL AND sd.occurred_at <= :end_at)")

        sql = f"""
            SELECT
                sd.entity_type,
                sd.source_id,
                COALESCE(sd.title, '') AS title,
                sd.content,
                sd.occurred_at,
                bm25(search_documents_fts) AS rank_value
            FROM search_documents_fts
            JOIN search_documents sd ON sd.id = search_documents_fts.rowid
            WHERE {' AND '.join(filters)}
            ORDER BY rank_value, COALESCE(sd.occurred_at, sd.created_at) DESC
            LIMIT :limit
        """
        rows = session.connection().execute(text(sql), params).mappings().all()
        evidence: list[QAEvidence] = []
        for row in rows:
            source_id = int(row["source_id"])
            content = str(row["content"])
            if not self._is_meaningful_text(content):
                continue
            evidence.append(
                QAEvidence(
                    entity_type=str(row["entity_type"]),
                    source_id=source_id,
                    source_filename=source_map.get(source_id, f"source-{source_id}"),
                    title=str(row["title"] or row["entity_type"]),
                    content=content,
                    occurred_at=self._to_datetime(row["occurred_at"]),
                    score=0.0,
                )
            )
        return evidence

    def _source_map(self, session: Session) -> dict[int, str]:
        return {source.id: source.filename for source in session.exec(select(Source)).all() if source.id is not None}

    @staticmethod
    def _make_evidence_from_record(
        session: Session,
        source_id: int,
        entity_type: str,
        title: str,
        content: str,
        occurred_at: Optional[datetime],
    ) -> Optional[QAEvidence]:
        source = session.get(Source, source_id)
        if source is None:
            return None
        return QAEvidence(
            entity_type=entity_type,
            source_id=source_id,
            source_filename=source.filename,
            title=title or entity_type,
            content=content,
            occurred_at=occurred_at,
            score=0.0,
        )

    @staticmethod
    def _to_datetime(value: object) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _top_unique(items: Iterable[str], limit: int) -> list[str]:
        unique: list[str] = []
        for item in items:
            clean = (item or "").strip(" ，。；;!！?？")
            if clean and clean not in unique:
                unique.append(clean)
            if len(unique) >= limit:
                break
        return unique

    @staticmethod
    def _deduplicate_evidence(items: Iterable[QAEvidence]) -> list[QAEvidence]:
        unique: list[QAEvidence] = []
        seen: set[tuple[str, str, int]] = set()
        for item in items:
            if not QAService._is_meaningful_text(item.content):
                continue
            key = (item.entity_type, item.content, item.source_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    @staticmethod
    def _contains_negative_cue(content: str) -> bool:
        return any(cue in (content or "") for cue in NEGATIVE_HINTS)

    @staticmethod
    def _is_meaningful_text(content: str) -> bool:
        text_value = (content or "").strip()
        if not text_value:
            return False
        chinese_count = sum(1 for char in text_value if "\u4e00" <= char <= "\u9fff")
        symbol_count = sum(1 for char in text_value if char in {"·", ".", "…"})
        if chinese_count == 0 and symbol_count >= 3:
            return False
        return chinese_count >= 4 or len(text_value) >= 8

    @staticmethod
    def _quotes_for_subject(session: Session, subject_name: str) -> list[Quote]:
        return session.exec(
            select(Quote)
            .where((Quote.person_name == subject_name) | (Quote.speaker == subject_name))
            .order_by(Quote.occurred_at.desc(), Quote.id.desc())
        ).all()

    @staticmethod
    def _extract_preference_items_from_evidence(evidence: Sequence[QAEvidence], positive: bool) -> list[str]:
        patterns = (
            [r"(?:喜欢|爱吃|偏爱|爱喝)([\u4e00-\u9fa5A-Za-z0-9、，,]{1,18})"]
            if positive
            else [r"(?:不喜欢|讨厌|受不了|厌恶)([\u4e00-\u9fa5A-Za-z0-9、，,]{1,18})"]
        )
        items: list[str] = []

        for entry in evidence:
            for pattern in patterns:
                for match in re.findall(pattern, entry.content):
                    value = re.split(r"[，,。；;！!？?]", match)[0].strip()
                    if value:
                        items.append(value)
        return items

    @staticmethod
    def _infer_speech_tone(lines: Sequence[str]) -> list[str]:
        joined = "\n".join(lines)
        tags: list[str] = []
        if any(word in joined for word in ["直接说", "重点", "别兜圈子", "说清"]):
            tags.append("直接")
        if any(word in joined for word in ["别", "不要", "别追着问"]):
            tags.append("边界感强")
        if any(word in joined for word in ["为什么", "吗", "？", "?"]):
            tags.append("会追问")
        if any(word in joined for word in ["安静", "明天", "以后", "一个人"]):
            tags.append("偏克制")
        if any(word in joined for word in ["清醒", "说清", "直接"]):
            tags.append("结论先行")
        return tags[:4]

    @staticmethod
    def _extract_appellations(content: str) -> list[str]:
        candidates: list[str] = []
        patterns = [
            r"^([\u4e00-\u9fa5A-Za-z]{1,6})[，,:：]",
            r"([阿小老][\u4e00-\u9fa5]{1,2})[，,:：]",
            r"叫你([\u4e00-\u9fa5A-Za-z]{1,6})",
            r"喊你([\u4e00-\u9fa5A-Za-z]{1,6})",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, content.strip()):
                value = match.strip()
                if 1 < len(value) <= 6 and value not in {"我们", "自己", "直接说"}:
                    candidates.append(value)
        return candidates

    @staticmethod
    def _extract_profile_tags(lines: Sequence[str]) -> Counter[str]:
        counter: Counter[str] = Counter()
        trait_keywords = {
            "安静": ["安静", "沉默", "不吵"],
            "直接": ["直接", "重点", "说清"],
            "克制": ["克制", "冷静", "一个人"],
            "念旧": ["念旧", "旧照片", "以前"],
            "敏感": ["失眠", "睡不着", "别追着问"],
        }
        for line in lines:
            for tag, words in trait_keywords.items():
                if any(word in line for word in words):
                    counter[tag] += 1
        return counter

    @staticmethod
    def _extract_negative_reasons(evidence: Sequence[QAEvidence]) -> list[str]:
        reasons: list[str] = []
        patterns = [
            r"(?:不喜欢|讨厌|受不了|厌恶)([\u4e00-\u9fa5A-Za-z0-9、，,]{1,18})",
            r"因为([\u4e00-\u9fa5A-Za-z0-9、，,]{1,18})(?:吵架|生气|不高兴)",
            r"(回消息太晚)",
            r"(太闹的餐厅)",
            r"(太甜的东西)",
            r"(奶油味)",
            r"(别追着问)",
        ]
        for item in evidence:
            if not any(hint in item.content for hint in NEGATIVE_HINTS):
                continue
            for pattern in patterns:
                for match in re.findall(pattern, item.content):
                    value = re.split(r"[，,。；;！!？?]", match)[0].strip()
                    if value:
                        reasons.append(value)
            if not reasons:
                keywords = extract_keywords(item.content, limit=3)
                reasons.extend(keywords)
        return reasons
