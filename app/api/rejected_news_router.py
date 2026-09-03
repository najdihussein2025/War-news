from datetime import datetime, timedelta
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.models import MessageStatus, RawMessage


router = APIRouter(prefix="/api/rejected-news", tags=["rejected-news"])
RED_ALERT_SOURCE_NAME = "Red Alert Lebanon"


class RejectedNewsItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    khabar: str
    summary: str
    message_datetime: datetime | None
    received_at: datetime
    source_name: str | None
    source_platform: str | None
    external_message_id: str | None
    rejection_type: Literal["not_relevant", "uncertain", "duplicate", "rejected"]
    rejection_reason: str
    rejection_reason_en: str
    rejection_reason_ar: str
    duplicate_of_id: int | None


class RejectedNewsList(BaseModel):
    items: list[RejectedNewsItem]
    total: int
    limit: int
    offset: int


class RestoreRejectedResult(BaseModel):
    id: int
    status: Literal["queued"] = "queued"


def _arabic_reason(reason: str, rejection_type: str) -> str:
    normalized = reason.strip().lower()
    translations = (
        (("general multi-area alert", "no single village applies"), "التنبيه عام ويشمل عدة مناطق، لذلك لا ينطبق على بلدة واحدة."),
        (("location could not be identified reliably from the alert image",), "تعذّر تحديد المنطقة بدقة من صورة التنبيه."),
        (("no locality was specified in the red alert notice",), "لم يحدّد تنبيه Red Alert بلدة بعينها."),
        (("no canonical village matched", "no village matched", "unmatched village"), "لم يتم العثور على بلدة معتمدة مطابقة للخبر."),
        (("no canonical condition matched", "no condition matched", "unmatched condition"), "لم يتم العثور على حالة أو نوع حدث معتمد مطابق للخبر."),
        (("not related to lebanon", "not relevant to lebanon", "outside lebanon"), "الخبر غير مرتبط بلبنان."),
        (("location is unclear", "unclear location"), "موقع الحدث غير واضح."),
        (("relevance was uncertain", "uncertain relevance"), "لم يتمكن النظام من التأكد من ارتباط الخبر، ويحتاج إلى مراجعة."),
        (("classified as not relevant", "not relevant", "irrelevant"), "صُنّف الخبر على أنه غير مرتبط بنطاق الأحداث المطلوبة."),
    )
    for patterns, translation in translations:
        if any(pattern in normalized for pattern in patterns):
            return translation
    if rejection_type == "duplicate":
        return "الخبر مكرر ومطابق لخبر خام آخر."
    if rejection_type == "uncertain":
        return "سبب الرفض غير مؤكد ويحتاج الخبر إلى مراجعة إدارية."
    if rejection_type == "not_relevant":
        return "صُنّف الخبر على أنه غير مرتبط بنطاق الأحداث المطلوبة."
    # Preserve already-Arabic explanations; otherwise avoid exposing an
    # internal English diagnostic as the administrator-facing explanation.
    if any("\u0600" <= char <= "\u06ff" for char in reason):
        return reason
    return "رُفض الخبر أثناء المعالجة الآلية ويحتاج إلى مراجعة إدارية."


def _news_summary(message: RawMessage) -> str:
    text = message.raw_text or ""
    normalized = text.replace("_", " ")
    normalized = re.sub(r"https?://\S+|www\.\S+", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"__?[A-Z][A-Z0-9_]+__?", " ", normalized)
    normalized = re.sub(r"[#@]", "", normalized)
    normalized = re.sub(r"<[^>]+>", " ", normalized)
    normalized = re.sub(r"[^\w\s\u0600-\u06ff.,،:؛!?؟-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .،,:؛-")

    lowered = normalized.lower()
    is_red_alert = (
        "redalert.com.lb" in lowered
        or "redalert.com.ib" in lowered
        or "__RED_ZONE_TEXT__" in text
        or ("حيطة" in normalized and "حذر" in normalized)
    )

    # Map-card OCR contains counters, nearby labels, and random Latin text.
    # Only publish facts that can be identified reliably from the alert.
    if ("آخر تحديث" in normalized or "اخر تحديث" in normalized) and ("المسير" in normalized or "مسيرة" in normalized):
        return "تحديث: نشاط طائرات مسيّرة معادية في أجواء لبنان. يُرجى الحيطة والحذر."
    if is_red_alert and any(keyword in normalized for keyword in ("مقاتلات حربية", "طيران حربي")):
        return "رُصد طيران حربي في الأجواء اللبنانية. يُرجى الحيطة والحذر."
    if is_red_alert and any(keyword in normalized for keyword in ("مروحية", "مروحيات", "هليكوبتر", "كوتريّة")):
        return "رُصدت مروحية في الأجواء اللبنانية. يُرجى الحيطة والحذر."
    if is_red_alert:
        return "رُصدت طائرة مسيّرة. تعذّر تحديد المنطقة بدقة من الصورة."

    if "مقاتلات حربية" in normalized and "لبنان" in normalized:
        return "رُصدت مقاتلات حربية متجهة نحو لبنان."
    if "مسيرة" in normalized or "مسيّرة" in normalized:
        return "رُصدت طائرة مسيّرة، لكن تعذّر تحديد البلدة من النص."
    if "غارة" in normalized:
        return "أُفيد عن غارة، لكن تعذّر تحديد موقع الحدث بدقة من النص."
    if not normalized:
        return "تعذّر استخراج ملخص واضح من الخبر الأصلي."

    words = normalized.split()
    shortened = " ".join(words[:24]).strip()
    if len(words) > 24:
        shortened += "…"
    if shortened[-1:] not in ".!?؟":
        shortened += "."
    return shortened


def _reason_details(message: RawMessage) -> tuple[str, str, str]:
    if message.status == MessageStatus.duplicate:
        target = f" {message.duplicate_of_id}" if message.duplicate_of_id else ""
        english = f"Duplicate of raw message{target}."
        arabic = f"الخبر مكرر ومطابق للخبر الخام{target}."
        return "duplicate", english, arabic

    result = message.filter_result or {}
    classification = message.cnrs_classification or {}
    verdict = str(result.get("verdict") or result.get("classification") or "").lower()
    reason = (
        result.get("reasoning")
        or result.get("reason")
        or classification.get("reason")
        or message.error_message
    )
    if str(reason or "").strip().lower() == "no canonical village matched" and getattr(message, "source_name", None) == "Red Alert Lebanon":
        text = (getattr(message, "raw_text", None) or "").casefold()
        if ("آخر تحديث" in text or "اخر تحديث" in text) and "لبنان" in text:
            reason = "General multi-area alert; no single village applies"
        elif (getattr(message, "raw_payload", None) or {}).get("ocr_text"):
            reason = "Location could not be identified reliably from the alert image"
        else:
            reason = "No locality was specified in the Red Alert notice"
    if verdict in {"uncertain", "needs_review"} or message.low_confidence_relevance:
        text = str(reason or "Relevance was uncertain and requires review.")
        return "uncertain", text, _arabic_reason(text, "uncertain")
    if verdict in {"not_relevant", "irrelevant", "reject"}:
        text = str(reason or "The report was classified as not relevant.")
        return "not_relevant", text, _arabic_reason(text, "not_relevant")
    text = str(reason or "The pipeline rejected this report.")
    return "rejected", text, _arabic_reason(text, "rejected")


def _reason(message: RawMessage) -> tuple[str, str]:
    rejection_type, _english, arabic = _reason_details(message)
    return rejection_type, arabic


def _item(message: RawMessage) -> RejectedNewsItem:
    rejection_type, rejection_reason_en, rejection_reason_ar = _reason_details(message)
    return RejectedNewsItem(
        id=message.id,
        khabar=message.raw_text or "",
        summary=_news_summary(message),
        message_datetime=message.message_datetime,
        received_at=message.received_at,
        source_name=message.source_name,
        source_platform=message.source_platform,
        external_message_id=message.external_message_id,
        rejection_type=rejection_type,  # type: ignore[arg-type]
        rejection_reason=rejection_reason_ar,
        rejection_reason_en=rejection_reason_en,
        rejection_reason_ar=rejection_reason_ar,
        duplicate_of_id=message.duplicate_of_id,
    )


@router.get("", response_model=RejectedNewsList)
def list_rejected_news(
    limit: int = Query(100, ge=1, le=150),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    _current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RejectedNewsList:
    cutoff = datetime.now().astimezone() - timedelta(days=7)
    filters = [
        RawMessage.status.in_([MessageStatus.rejected, MessageStatus.duplicate]),
        func.coalesce(RawMessage.message_datetime, RawMessage.received_at) >= cutoff,
        or_(
            RawMessage.source_name.is_(None),
            RawMessage.source_name != RED_ALERT_SOURCE_NAME,
        ),
    ]
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(or_(RawMessage.raw_text.ilike(pattern), RawMessage.source_name.ilike(pattern)))
    statement = (
        select(RawMessage)
        .where(*filters)
        .order_by(func.coalesce(RawMessage.message_datetime, RawMessage.received_at).desc(), RawMessage.id.desc())
        .limit(limit)
        .offset(offset)
    )
    messages = list(db.scalars(statement).all())
    total = db.scalar(select(func.count(RawMessage.id)).where(*filters)) or 0
    return RejectedNewsList(items=[_item(message) for message in messages], total=int(total), limit=limit, offset=offset)


@router.get("/{raw_message_id}", response_model=RejectedNewsItem)
def get_rejected_news(
    raw_message_id: int,
    _current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RejectedNewsItem:
    message = db.get(RawMessage, raw_message_id)
    if message is None or message.status not in {MessageStatus.rejected, MessageStatus.duplicate}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rejected news was not found.")
    return _item(message)


@router.post("/{raw_message_id}/restore", response_model=RestoreRejectedResult)
def restore_rejected_news(
    raw_message_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RestoreRejectedResult:
    message = db.scalar(select(RawMessage).where(RawMessage.id == raw_message_id).with_for_update())
    if message is None or message.status not in {MessageStatus.rejected, MessageStatus.duplicate}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rejected news is missing or already restored.")
    payload = dict(message.raw_payload or {})
    payload["manual_rejection_override"] = {
        "restored_by": str(current_user.id),
        "restored_at": datetime.now().astimezone().isoformat(),
        "previous_status": message.status.value,
        "reason": _reason(message)[1],
    }
    message.raw_payload = payload
    message.status = MessageStatus.parsed
    message.duplicate_of_id = None
    message.error_message = None
    message.extraction_retry_count = 0
    message.match_retry_count = 0
    message.processing_claim_stage = None
    message.processing_claimed_at = None
    message.processing_claimed_by = None
    db.add(message)
    db.commit()
    return RestoreRejectedResult(id=message.id)
