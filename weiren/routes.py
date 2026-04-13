from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from urllib.parse import urlencode
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from weiren.config import settings
from weiren.db import get_session
from weiren.models import (
    ChatSession,
    DedupeCandidate,
    ExportRecord,
    Memory,
    Message,
    Preference,
    QARecord,
    Quote,
    Source,
    TimelineEvent,
    Trait,
)
from weiren.services.chat_service import ChatService
from weiren.services.dedupe_service import DedupeService
from weiren.services.evidence_service import EvidenceService
from weiren.services.export_service import ExportService
from weiren.services.import_service import ImportService
from weiren.services.qa_service import QAService
from weiren.services.review_service import ReviewService
from weiren.services.search_service import SearchService
from weiren.services.settings_service import SettingsService
from weiren.utils.datetime_utils import format_date, format_datetime, parse_date_input
from weiren.utils.entity_registry import DEDUPE_ENTITY_TYPES, REVIEWABLE_ENTITY_TYPES, entity_content, entity_meta, entity_title
from weiren.utils.privacy import build_masked_text
from weiren.utils.text import dumps_json, loads_json

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.template_dir))
import_service = ImportService()
search_service = SearchService()
qa_service = QAService()
settings_service = SettingsService()
evidence_service = EvidenceService()
review_service = ReviewService()
dedupe_service = DedupeService()
export_service = ExportService()
chat_service = ChatService()


@dataclass(slots=True)
class DedupeCandidateView:
    candidate: DedupeCandidate
    left_record: Any
    right_record: Any
    left_title: str
    right_title: str
    left_content: str
    right_content: str


def render(request: Request, template_name: str, context: dict, session: Session) -> object:
    ui_settings = settings_service.get(session)

    def display_text(text: str, masked_text: str | None = None) -> str:
        if ui_settings.demo_mode:
            return masked_text or build_masked_text(text, ui_settings, summary_only=True)
        return text

    def build_search_url(
        raw_query: str = "",
        similar_query: str = "",
        source_id: int | None = None,
        start_date: object | None = None,
        end_date: object | None = None,
    ) -> str:
        params: dict[str, str | int] = {"q": raw_query or "", "similar": similar_query or ""}
        if source_id:
            params["source_id"] = source_id
        if start_date:
            params["start_date"] = str(start_date)
        if end_date:
            params["end_date"] = str(end_date)
        return f"/search?{urlencode(params)}"

    base_context = {
        "request": request,
        "app_title": settings.app_title,
        "now": datetime.now(),
        "format_date": format_date,
        "format_datetime": format_datetime,
        "ui_settings": ui_settings,
        "display_text": display_text,
        "build_search_url": build_search_url,
        "loads_json": loads_json,
    }
    base_context.update(context)
    return templates.TemplateResponse(template_name, base_context)


def subject_names(session: Session) -> list[str]:
    return [name for name in session.exec(select(Source.subject_name).distinct()).all() if name]


def top_distinct(items: list[Any], key_func, limit: int = 8) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in items:
        key = key_func(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


@router.get("/")
def index(request: Request, session: Session = Depends(get_session)) -> object:
    stats = {
        "sources": session.exec(select(func.count()).select_from(Source)).one(),
        "messages": session.exec(select(func.count()).select_from(Message)).one(),
        "memories": session.exec(select(func.count()).select_from(Memory)).one(),
        "quotes": session.exec(select(func.count()).select_from(Quote)).one(),
    }
    recent_sources = session.exec(select(Source).order_by(Source.imported_at.desc()).limit(4)).all()
    recent_events = session.exec(select(TimelineEvent).order_by(TimelineEvent.event_date.desc(), TimelineEvent.id.desc()).limit(4)).all()
    return render(request, "index.html", {"stats": stats, "recent_sources": recent_sources, "recent_events": recent_events}, session)


@router.get("/import")
def import_page(request: Request, session: Session = Depends(get_session)) -> object:
    sources = session.exec(select(Source).order_by(Source.imported_at.desc())).all()
    return render(request, "import.html", {"sources": sources, "result_messages": []}, session)


@router.post("/import")
async def import_submit(
    request: Request,
    subject_name: str = Form("未命名对象"),
    manual_title: str = Form("补充记录"),
    manual_text: str = Form(""),
    manual_description: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
) -> object:
    result_messages: list[str] = []
    if files:
        results = await import_service.import_uploads(session, files, subject_name=subject_name, manual_description=manual_description)
        for result in results:
            if result.skipped:
                result_messages.append(f"{result.source.filename}: {result.reason}")
            else:
                result_messages.append(f"{result.source.filename}: 导入完成")
    if manual_text.strip():
        result = import_service.import_manual_text(session, manual_text, subject_name=subject_name, title=manual_title)
        if result.skipped:
            result_messages.append(f"{result.source.filename}: {result.reason}")
        else:
            result_messages.append(f"{result.source.filename}: 手工记录已写入")
    sources = session.exec(select(Source).order_by(Source.imported_at.desc())).all()
    return render(request, "import.html", {"sources": sources, "result_messages": result_messages}, session)


@router.post("/import/delete/{source_id}")
def delete_source(source_id: int, session: Session = Depends(get_session)) -> object:
    import_service.delete_source(session, source_id)
    return RedirectResponse(url="/import", status_code=303)


@router.get("/profile")
def profile_page(request: Request, person: Optional[str] = None, session: Session = Depends(get_session)) -> object:
    names = subject_names(session)
    active_person = person or (names[0] if names else "未命名对象")
    preferences = session.exec(select(Preference).where(Preference.person_name == active_person).order_by(Preference.updated_at.desc())).all()
    traits = session.exec(select(Trait).where(Trait.person_name == active_person).order_by(Trait.updated_at.desc())).all()
    quotes = session.exec(select(Quote).where(Quote.person_name == active_person).order_by(Quote.occurred_at.desc(), Quote.id.desc()).limit(8)).all()
    memories = session.exec(select(Memory).where(Memory.person_name == active_person).order_by(Memory.event_time.desc(), Memory.id.desc()).limit(8)).all()
    timeline = session.exec(
        select(TimelineEvent).where(TimelineEvent.person_name == active_person).order_by(TimelineEvent.event_date.desc(), TimelineEvent.id.desc()).limit(8)
    ).all()
    like_items = top_distinct([item for item in preferences if item.polarity == "like"], lambda item: item.item, limit=6)
    dislike_items = top_distinct([item for item in preferences if item.polarity == "dislike"], lambda item: item.item, limit=6)
    trait_items = top_distinct(traits, lambda item: item.trait, limit=8)
    return render(
        request,
        "profile.html",
        {
            "subject_names": names,
            "active_person": active_person,
            "like_items": like_items,
            "dislike_items": dislike_items,
            "trait_items": trait_items,
            "quotes": quotes,
            "memories": memories,
            "timeline": timeline,
            "trait_counts": Counter(item.trait for item in traits),
        },
        session,
    )


@router.get("/timeline")
def timeline_page(
    request: Request,
    person: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session),
) -> object:
    names = subject_names(session)
    active_person = person or (names[0] if names else "未命名对象")
    statement = select(TimelineEvent).where(TimelineEvent.person_name == active_person)
    start = parse_date_input(start_date)
    end = parse_date_input(end_date)
    if start:
        statement = statement.where(TimelineEvent.event_date >= start)
    if end:
        statement = statement.where(TimelineEvent.event_date <= end)
    events = session.exec(statement.order_by(TimelineEvent.event_date.desc(), TimelineEvent.id.desc())).all()
    return render(
        request,
        "timeline.html",
        {
            "subject_names": names,
            "active_person": active_person,
            "events": events,
            "start_date": start_date or "",
            "end_date": end_date or "",
        },
        session,
    )


@router.get("/search")
def search_page(
    request: Request,
    q: str = "",
    similar: str = "",
    source_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session),
) -> object:
    start = parse_date_input(start_date)
    end = parse_date_input(end_date)
    start_dt = datetime.combine(start, time.min) if start else None
    end_dt = datetime.combine(end, time.max) if end else None
    search_bundle = search_service.search(session, q, source_id=source_id, start_at=start_dt, end_at=end_dt) if q.strip() else None
    similar_results = search_service.similar_sentences(session, similar, source_id=source_id) if similar.strip() else []
    if q.strip() or similar.strip():
        search_service.record_history(
            session,
            raw_query=q,
            similar_query=similar,
            source_id=source_id,
            start_date=start,
            end_date=end,
            result_count=len(search_bundle.results if search_bundle else []) + len(similar_results),
        )
    sources = session.exec(select(Source).order_by(Source.imported_at.desc())).all()
    return render(
        request,
        "search.html",
        {
            "q": q,
            "similar": similar,
            "source_id": source_id,
            "sources": sources,
            "results": search_bundle.results if search_bundle else [],
            "similar_results": similar_results,
            "start_date": start_date or "",
            "end_date": end_date or "",
            "parsed_query": search_bundle.parsed_query if search_bundle else search_service.parse_query(""),
            "saved_presets": search_service.list_presets(session),
            "search_history": search_service.list_history(session),
        },
        session,
    )


@router.post("/search/save")
async def search_save(request: Request, session: Session = Depends(get_session)) -> object:
    form = await request.form()
    q = str(form.get("q") or "")
    similar = str(form.get("similar") or "")
    source_raw = str(form.get("source_id") or "").strip()
    source_id = int(source_raw) if source_raw.isdigit() else None
    start_date = parse_date_input(str(form.get("start_date") or ""))
    end_date = parse_date_input(str(form.get("end_date") or ""))
    preset_name = str(form.get("preset_name") or "").strip() or "未命名搜索"
    search_service.save_preset(
        session,
        name=preset_name,
        raw_query=q,
        similar_query=similar,
        source_id=source_id,
        start_date=start_date,
        end_date=end_date,
    )
    params: dict[str, str | int] = {"q": q, "similar": similar}
    if source_id:
        params["source_id"] = source_id
    if start_date:
        params["start_date"] = start_date.isoformat()
    if end_date:
        params["end_date"] = end_date.isoformat()
    return RedirectResponse(url=f"/search?{urlencode(params)}", status_code=303)


@router.get("/chat")
def chat_page(
    request: Request,
    session_id: Optional[int] = None,
    new: int = 0,
    subject_name: Optional[str] = None,
    session: Session = Depends(get_session),
) -> object:
    if new or session_id is None:
        chat_session = chat_service.ensure_session(session, subject_name=subject_name)
        return RedirectResponse(url=f"/chat?session_id={chat_session.id}", status_code=303)

    chat_session = chat_service.ensure_session(session, session_id=session_id, subject_name=subject_name)
    if chat_session.id != session_id:
        return RedirectResponse(url=f"/chat?session_id={chat_session.id}", status_code=303)

    messages = chat_service.list_messages(session, chat_session.id or 0)
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "app_title": settings.app_title,
            "subject_name": chat_session.subject_name,
            "chat_session": chat_session,
            "messages": messages,
            "loads_json": loads_json,
            "suggested_questions": [
                "她喜欢吃什么？",
                "她最常说的话有哪些？",
                "我们在某段时间发生了什么？",
                "她平时是什么样的人？",
            ],
        },
    )


@router.post("/api/chat")
async def chat_api(request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    payload = await request.json()
    question = str(payload.get("question") or "").strip()
    subject_name = str(payload.get("subject_name") or "").strip() or chat_service.default_subject_name(session)
    raw_session_id = payload.get("session_id")
    session_id = int(raw_session_id) if raw_session_id not in {None, ""} else None
    chat_session = chat_service.ensure_session(session, session_id=session_id, subject_name=subject_name)

    if not question:
        return JSONResponse({"error": "问题不能为空。"}, status_code=400)

    reply = chat_service.answer(session, question=question, subject_name=chat_session.subject_name)
    chat_service.append_exchange(session, chat_session, question=question, reply=reply)

    return JSONResponse(
        {
            "session_id": chat_session.id,
            "answer": reply.answer,
            "intent": reply.intent,
            "confidence": reply.confidence,
            "evidence": [
                {
                    "source_name": item.source_name,
                    "source_type": item.source_type,
                    "snippet": item.snippet,
                    "date": item.date,
                    "similarity": item.similarity,
                    "keywords": item.keywords,
                }
                for item in reply.evidence
            ],
        }
    )


@router.post("/api/chat/clear")
async def chat_clear_api(request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    payload = await request.json()
    raw_session_id = payload.get("session_id")
    session_id = int(raw_session_id) if raw_session_id not in {None, ""} else None
    if session_id is None:
        return JSONResponse({"error": "缺少 session_id。"}, status_code=400)
    chat_service.clear_session(session, session_id)
    return JSONResponse({"ok": True, "session_id": session_id})


@router.get("/qa")
def qa_page(request: Request, session: Session = Depends(get_session)) -> object:
    names = subject_names(session)
    default_subject = names[0] if names else "她"
    recent_qa = session.exec(select(QARecord).order_by(QARecord.created_at.desc()).limit(6)).all()
    return render(
        request,
        "qa.html",
        {"response": None, "subject_names": names, "default_subject": default_subject, "recent_qa": recent_qa},
        session,
    )


@router.post("/qa")
def qa_submit(
    request: Request,
    question: str = Form(...),
    subject_name: str = Form("她"),
    session: Session = Depends(get_session),
) -> object:
    names = subject_names(session)
    response = qa_service.answer(session, question, default_subject=subject_name)
    session.add(
        QARecord(
            subject_name=subject_name,
            question=question,
            intent=response.intent,
            answer=response.answer,
            evidence_json=dumps_json([asdict(item) for item in response.evidence_sources]),
        )
    )
    session.commit()
    recent_qa = session.exec(select(QARecord).order_by(QARecord.created_at.desc()).limit(6)).all()
    return render(
        request,
        "qa.html",
        {
            "response": response,
            "subject_names": names,
            "default_subject": subject_name,
            "question": question,
            "recent_qa": recent_qa,
        },
        session,
    )


@router.get("/evidence/{entity_type}/{entity_id}")
def evidence_detail(entity_type: str, entity_id: int, request: Request, session: Session = Depends(get_session)) -> object:
    record = evidence_service.fetch_entity(session, entity_type, entity_id)
    if record is None:
        return RedirectResponse(url="/", status_code=303)
    evidence_service.ensure_entity_links(session, entity_type, record)
    session.commit()
    evidence_items = evidence_service.list_evidence(session, entity_type, entity_id, demo_mode=settings_service.get(session).demo_mode)
    return render(
        request,
        "evidence.html",
        {
            "entity_type": entity_type,
            "entity_label": entity_meta(entity_type).label,
            "record": record,
            "record_title": entity_title(record, entity_type),
            "record_content": entity_content(record, entity_type),
            "evidence_items": evidence_items,
        },
        session,
    )


@router.get("/review")
def review_page(
    request: Request,
    entity_type: str = "trait",
    person: Optional[str] = None,
    session: Session = Depends(get_session),
) -> object:
    if entity_type not in REVIEWABLE_ENTITY_TYPES:
        entity_type = "trait"
    records = review_service.list_records(session, entity_type, person_name=person)
    return render(
        request,
        "review.html",
        {
            "entity_types": REVIEWABLE_ENTITY_TYPES,
            "active_entity_type": entity_type,
            "subject_names": subject_names(session),
            "active_person": person or "",
            "records": records,
        },
        session,
    )


@router.post("/review/update/{entity_type}/{entity_id}")
async def review_update(entity_type: str, entity_id: int, request: Request, session: Session = Depends(get_session)) -> object:
    form = await request.form()
    payload = {key: value for key, value in form.items() if key not in {"redirect_person", "redirect_entity_type"}}
    payload["is_confirmed"] = "is_confirmed" in form
    payload["is_low_confidence"] = "is_low_confidence" in form
    review_service.update_record(session, entity_type, entity_id, payload)
    redirect_entity_type = str(form.get("redirect_entity_type") or entity_type)
    redirect_person = str(form.get("redirect_person") or "")
    suffix = f"?entity_type={redirect_entity_type}"
    if redirect_person:
        suffix += f"&person={redirect_person}"
    return RedirectResponse(url=f"/review{suffix}", status_code=303)


@router.post("/review/delete/{entity_type}/{entity_id}")
async def review_delete(entity_type: str, entity_id: int, request: Request, session: Session = Depends(get_session)) -> object:
    form = await request.form()
    review_service.delete_record(session, entity_type, entity_id)
    redirect_entity_type = str(form.get("redirect_entity_type") or entity_type)
    redirect_person = str(form.get("redirect_person") or "")
    suffix = f"?entity_type={redirect_entity_type}"
    if redirect_person:
        suffix += f"&person={redirect_person}"
    return RedirectResponse(url=f"/review{suffix}", status_code=303)


@router.get("/dedupe")
def dedupe_page(request: Request, refresh: int = 0, session: Session = Depends(get_session)) -> object:
    if refresh:
        dedupe_service.scan(session)
    candidates = dedupe_service.list_candidates(session)
    views: list[DedupeCandidateView] = []
    for candidate in candidates:
        meta = entity_meta(candidate.entity_type)
        left = session.get(meta.model, candidate.left_entity_id)
        right = session.get(meta.model, candidate.right_entity_id)
        if left is None or right is None:
            continue
        views.append(
            DedupeCandidateView(
                candidate=candidate,
                left_record=left,
                right_record=right,
                left_title=entity_title(left, candidate.entity_type),
                right_title=entity_title(right, candidate.entity_type),
                left_content=entity_content(left, candidate.entity_type),
                right_content=entity_content(right, candidate.entity_type),
            )
        )
    return render(request, "dedupe.html", {"candidate_views": views, "entity_types": DEDUPE_ENTITY_TYPES}, session)


@router.post("/dedupe/scan")
def dedupe_scan(session: Session = Depends(get_session)) -> object:
    dedupe_service.scan(session)
    return RedirectResponse(url="/dedupe", status_code=303)


@router.post("/dedupe/keep/{candidate_id}")
async def dedupe_keep(candidate_id: int, request: Request, session: Session = Depends(get_session)) -> object:
    form = await request.form()
    keep_side = str(form.get("keep_side") or "left")
    dedupe_service.resolve_keep(session, candidate_id, keep_side)
    return RedirectResponse(url="/dedupe", status_code=303)


@router.post("/dedupe/merge/{candidate_id}")
async def dedupe_merge(candidate_id: int, request: Request, session: Session = Depends(get_session)) -> object:
    form = await request.form()
    dedupe_service.resolve_merge(
        session,
        candidate_id,
        merged_title=str(form.get("merged_title") or "合并记录"),
        merged_content=str(form.get("merged_content") or ""),
    )
    return RedirectResponse(url="/dedupe", status_code=303)


@router.post("/dedupe/ignore/{candidate_id}")
def dedupe_ignore(candidate_id: int, session: Session = Depends(get_session)) -> object:
    dedupe_service.ignore(session, candidate_id)
    return RedirectResponse(url="/dedupe", status_code=303)


@router.get("/export")
def export_page(request: Request, session: Session = Depends(get_session)) -> object:
    names = subject_names(session)
    records = session.exec(select(ExportRecord).order_by(ExportRecord.created_at.desc()).limit(10)).all()
    return render(request, "export.html", {"subject_names": names, "export_records": records}, session)


@router.post("/export")
async def export_submit(request: Request, session: Session = Depends(get_session)) -> FileResponse:
    form = await request.form()
    subject_name = str(form.get("subject_name") or "未命名对象")
    export_type = str(form.get("export_type") or "profile")
    include_evidence = "include_evidence" in form
    masked = "masked" in form
    confirmed_only = "confirmed_only" in form
    if export_type == "profile":
        path = export_service.export_profile_markdown(session, subject_name, include_evidence, masked, confirmed_only)
    elif export_type == "timeline":
        path = export_service.export_timeline_markdown(session, subject_name, include_evidence, masked, confirmed_only)
    elif export_type == "qa":
        path = export_service.export_qa_markdown(session, subject_name, include_evidence, masked)
    else:
        path = export_service.export_archive_zip(session, subject_name, include_evidence, masked, confirmed_only)
    return FileResponse(path=path, filename=Path(path).name, media_type="application/octet-stream")


@router.get("/settings")
def settings_page(request: Request, session: Session = Depends(get_session)) -> object:
    return render(request, "settings.html", {"saved": False}, session)


@router.post("/settings")
async def settings_submit(request: Request, session: Session = Depends(get_session)) -> object:
    form = await request.form()
    settings_service.update(
        session,
        demo_mode="demo_mode" in form,
        mask_real_name="mask_real_name" in form,
        mask_phone="mask_phone" in form,
        mask_location="mask_location" in form,
        mask_social="mask_social" in form,
    )
    return render(request, "settings.html", {"saved": True}, session)
