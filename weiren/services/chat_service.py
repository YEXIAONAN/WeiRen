from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from weiren.models import AppSetting, ChatMessage, ChatSession, Source
from weiren.services.qa_service import INSUFFICIENT_ANSWER, QAService, QAEvidence
from weiren.services.search_service import SearchService
from weiren.utils.text import extract_keywords


@dataclass(slots=True)
class ChatEvidence:
    source_name: str
    source_type: str
    snippet: str
    date: Optional[str] = None
    similarity: Optional[float] = None
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ChatReply:
    answer: str
    intent: str
    confidence: str
    evidence: list[ChatEvidence] = field(default_factory=list)


class ChatService:
    def __init__(self) -> None:
        self.qa_service = QAService()
        self.search_service = SearchService()

    def ensure_session(self, session: Session, session_id: Optional[int] = None, subject_name: Optional[str] = None) -> ChatSession:
        if session_id:
            chat_session = session.get(ChatSession, session_id)
            if chat_session is not None:
                if subject_name and subject_name != chat_session.subject_name:
                    chat_session.subject_name = subject_name
                    chat_session.updated_at = datetime.utcnow()
                    session.add(chat_session)
                    session.commit()
                    session.refresh(chat_session)
                return chat_session
        chat_session = ChatSession(subject_name=subject_name or self.default_subject_name(session))
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)
        return chat_session

    def clear_session(self, session: Session, session_id: int) -> None:
        records = session.exec(select(ChatMessage).where(ChatMessage.session_id == session_id)).all()
        for record in records:
            session.delete(record)
        chat_session = session.get(ChatSession, session_id)
        if chat_session is not None:
            chat_session.title = "新对话"
            chat_session.updated_at = datetime.utcnow()
            session.add(chat_session)
        session.commit()

    def list_messages(self, session: Session, session_id: int) -> list[ChatMessage]:
        return session.exec(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        ).all()

    def answer(self, session: Session, question: str, subject_name: str) -> ChatReply:
        setting = session.exec(select(AppSetting)).first()
        llm_enabled = setting.llm_enabled if setting else False
        qa_response = self.qa_service.answer(session, question=question, default_subject=subject_name, llm_enabled=llm_enabled)
        if qa_response.answer != INSUFFICIENT_ANSWER and qa_response.evidence_sources:
            evidence = self._build_qa_evidence(session, qa_response.evidence_sources)
            confidence = self._qa_confidence(qa_response.evidence_sources)
            return ChatReply(
                answer=qa_response.answer,
                intent=qa_response.intent,
                confidence=confidence,
                evidence=evidence,
            )

        search_bundle = self.search_service.search(session, query=question, limit=4)
        if search_bundle.results:
            top_results = search_bundle.results[:3]
            fragments: list[str] = []
            evidence: list[ChatEvidence] = []
            for item in top_results:
                summary = item.content.strip().replace("\n", " ")
                if len(summary) > 44:
                    summary = summary[:44].rstrip() + "..."
                fragments.append(summary)
                evidence.append(
                    ChatEvidence(
                        source_name=item.source_filename,
                        source_type=item.source_type,
                        snippet=item.content,
                        date=item.occurred_at.isoformat(sep=" ", timespec="seconds") if item.occurred_at else None,
                        similarity=None,
                        keywords=extract_keywords(item.content, limit=4),
                    )
                )
            answer = "检索到一些相关资料：" + "；".join(fragments) + "。"
            confidence = "medium" if len(top_results) >= 2 else "low"
            return ChatReply(answer=answer, intent="search_summary", confidence=confidence, evidence=evidence)

        return ChatReply(answer=INSUFFICIENT_ANSWER, intent=qa_response.intent or "unknown", confidence="low", evidence=[])

    def append_exchange(
        self,
        session: Session,
        chat_session: ChatSession,
        question: str,
        reply: ChatReply,
    ) -> list[ChatMessage]:
        user_message = ChatMessage(session_id=chat_session.id or 0, role="user", content=question)
        system_message = ChatMessage(
            session_id=chat_session.id or 0,
            role="system",
            content=reply.answer,
            intent=reply.intent,
            confidence=reply.confidence,
            evidence_json=self._serialize_evidence(reply.evidence),
        )
        session.add(user_message)
        session.add(system_message)
        if chat_session.title == "新对话":
            chat_session.title = question[:24].strip() or "新对话"
        chat_session.updated_at = datetime.utcnow()
        session.add(chat_session)
        session.commit()
        session.refresh(user_message)
        session.refresh(system_message)
        return [user_message, system_message]

    def default_subject_name(self, session: Session) -> str:
        source = session.exec(select(Source).order_by(Source.imported_at.desc())).first()
        return source.subject_name if source is not None else "她"

    @staticmethod
    def _qa_confidence(evidence_sources: list[QAEvidence]) -> str:
        if len(evidence_sources) >= 3:
            return "high"
        if len(evidence_sources) == 2:
            return "medium"
        if len(evidence_sources) == 1:
            return "medium" if (evidence_sources[0].score or 0) >= 60 else "low"
        return "low"

    @staticmethod
    def _build_qa_evidence(session: Session, evidence_sources: list[QAEvidence]) -> list[ChatEvidence]:
        evidence: list[ChatEvidence] = []
        for item in evidence_sources:
            source = session.get(Source, item.source_id)
            evidence.append(
                ChatEvidence(
                    source_name=item.source_filename,
                    source_type=source.source_type if source is not None else "unknown",
                    snippet=item.content,
                    date=item.occurred_at.isoformat(sep=" ", timespec="seconds") if item.occurred_at else None,
                    similarity=item.score if item.score else None,
                    keywords=extract_keywords(item.content, limit=4),
                )
            )
        return evidence

    @staticmethod
    def _serialize_evidence(items: list[ChatEvidence]) -> str:
        from weiren.utils.text import dumps_json

        return dumps_json([
            {
                "source_name": item.source_name,
                "source_type": item.source_type,
                "snippet": item.snippet,
                "date": item.date,
                "similarity": item.similarity,
                "keywords": item.keywords,
            }
            for item in items
        ])
