import re
from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import case, delete as sa_delete, func, or_, select, update as sa_update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from zoneinfo import ZoneInfo

from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.core.text_normalization import normalize_arabic_text
from app.core.cache import increment
from app.news.constants.air_violation_conditions import (
    AIR_VIOLATION_CONDITION_ID_TUPLE,
    AIR_VIOLATION_CONDITION_IDS,
    AIR_VIOLATION_DRONE_CONDITION_ID,
    AIR_VIOLATION_HELICOPTER_CONDITION_ID,
    AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
    AIR_VIOLATION_WARPLANE_CONDITION_ID,
)
from app.news.dtos import (
    AirViolationCreateDTO,
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
    AirViolationSummaryDTO,
    AirViolationWindowDTO,
    AirViolationWindowListResponse,
    AirViolationUpdateDTO,
    MatchResultDTO,
)
from app.news.interfaces import AirViolationRepositoryInterface
from app.news.models import (
    AirViolation,
    AirViolationLocation,
    Condition,
    MessageStatus,
    RawMessage,
    Village,
)
from app.news.services.air_violations.breach_counting_service import (
    AirViolationBreach,
    BreachReport,
    BreachVillage,
    compute_breaches,
    count_breaches_by_condition,
    village_key,
)
from app.news.services.air_violations.caza_alias_resolver import canonicalize_caza
from app.news.services.air_violations.air_violation_eligibility import (
    HELICOPTER_LABEL_WITHOUT_KEYWORD_REASON,
    EligibilityResult,
    evaluate_air_violation_location,
    evaluate_air_violation_text,
)
from app.news.services.air_violations.air_violation_routing import (
    record_air_violation_outcome,
)
from app.news.services.air_violations.war_month import war_month
from app.sources.models import Source, SourceType


BEIRUT_TIMEZONE = ZoneInfo("Asia/Beirut")
AIR_VIOLATION_CACHE_VERSION_KEY = "air-violations:cache-version"
AIR_VIOLATION_CAZA_ALIASES: dict[str, tuple[str, str | None]] = {
    "hermel": ("Hermel", "\u0627\u0644\u0647\u0631\u0645\u0644"),
    "baalbeck": ("Baalbek", "\u0628\u0639\u0644\u0628\u0643"),
    "baalbek": ("Baalbek", "\u0628\u0639\u0644\u0628\u0643"),
    "saida": ("Saida", "\u0635\u064a\u062f\u0627"),
    "sidon": ("Saida", "\u0635\u064a\u062f\u0627"),
    "west beqaa": ("West Bekaa", "\u0627\u0644\u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a"),
    "west bekaa": ("West Bekaa", "\u0627\u0644\u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a"),
    "\u0627\u0644\u0628\u0642\u0627\u0639": ("West Bekaa", "\u0627\u0644\u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a"),
    "\u0627\u0644\u062c\u0646\u0648\u0628": ("South Lebanon", "\u062c\u0646\u0648\u0628 \u0644\u0628\u0646\u0627\u0646"),
    "\u062c\u0646\u0648\u0628": ("South Lebanon", "\u062c\u0646\u0648\u0628 \u0644\u0628\u0646\u0627\u0646"),
    "\u062c\u0646\u0648\u0628 \u0644\u0628\u0646\u0627\u0646": ("South Lebanon", "\u062c\u0646\u0648\u0628 \u0644\u0628\u0646\u0627\u0646"),
    "\u0627\u0644\u0642\u0637\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a": ("Multiple regions", "\u0645\u0646\u0627\u0637\u0642 \u0645\u062a\u0639\u062f\u062f\u0629"),
    "\u0627\u0644\u0642\u0637\u0627\u0639 \u0627\u0644\u0634\u0631\u0642\u064a": ("Multiple regions", "\u0645\u0646\u0627\u0637\u0642 \u0645\u062a\u0639\u062f\u062f\u0629"),
    "\u0627\u0644\u0642\u0637\u0627\u0639 \u0627\u0644\u0627\u0648\u0633\u0637": ("Multiple regions", "\u0645\u0646\u0627\u0637\u0642 \u0645\u062a\u0639\u062f\u062f\u0629"),
    "\u0627\u0644\u0642\u0637\u0627\u0639 \u0627\u0644\u0623\u0648\u0633\u0637": ("Multiple regions", "\u0645\u0646\u0627\u0637\u0642 \u0645\u062a\u0639\u062f\u062f\u0629"),
}
# Ingest dedup only drops exact re-posts of the same text. Counting windows
# (10 minutes / 6 hours / daily) are applied at read time, not at ingest.
AIR_VIOLATION_DUPLICATE_WINDOW_MINUTES = 10
WINDOWED_CONDITION_IDS = frozenset({
    AIR_VIOLATION_WARPLANE_CONDITION_ID,
    AIR_VIOLATION_DRONE_CONDITION_ID,
})
PER_REPORT_CONDITION_IDS = frozenset({
    AIR_VIOLATION_HELICOPTER_CONDITION_ID,
    AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
})


def _normalize_caza_token(value: str) -> str:
    return re.sub(r"[\W_]+", " ", value.casefold()).strip()


def _normalized_village_name(value: object) -> str:
    return " ".join(normalize_arabic_text(str(value or "")).casefold().split())


def _air_violation_event_datetime(record: AirViolation) -> datetime:
    return datetime.combine(record.event_date, record.event_time or time.min)


def _normalize_duplicate_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def as_beirut_datetime(value):
    """Convert aware upstream timestamps to local Beirut time for display/storage."""
    if value.tzinfo is None:
        return value
    return value.astimezone(BEIRUT_TIMEZONE)


def air_violation_news_text(
    message: RawMessage,
    village: Village | None,
    condition: Condition | None,
    villages: list[Village] | None = None,
) -> str:
    """Return readable news text while keeping raw OCR in the source record."""
    payload = message.raw_payload or {}
    if not payload.get("ocr_text") or condition is None:
        return clean_air_violation_news(message.raw_text or "")

    matched_villages = villages or ([village] if village is not None else [])
    if not matched_villages:
        return f"{condition.action_ar} - الموقع بحاجة إلى التحقق"
    village_names = list(dict.fromkeys(
        (
            getattr(matched_village, "ref_name_ar", None)
            or getattr(matched_village, "ref_name_en", None)
            or getattr(matched_village, "acs_name", None)
            or getattr(matched_village, "cad_name", None)
        )
        for matched_village in matched_villages
        if (
            getattr(matched_village, "ref_name_ar", None)
            or getattr(matched_village, "ref_name_en", None)
            or getattr(matched_village, "acs_name", None)
            or getattr(matched_village, "cad_name", None)
        )
    ))
    primary = matched_villages[0]
    caza_pairs = {
        (matched_village.caza_en, matched_village.caza_ar)
        for matched_village in matched_villages
        if matched_village.caza_en or matched_village.caza_ar
    }
    caza_name = (
        "مناطق متعددة"
        if len(caza_pairs) > 1
        else primary.caza_ar or primary.caza_en
    )
    village_text = "، ".join(village_names)
    summary = (
        f"{condition.action_ar} فوق {village_text} في قضاء {caza_name}"
        if village_text
        else f"{condition.action_ar} في قضاء {caza_name}"
    )
    raw_text = message.raw_text or ""
    if "حيطة" in raw_text and "حذر" in raw_text:
        summary += " - حيطة وحذر"
    return clean_air_violation_news(summary)


def clean_air_violation_news(value: str) -> str:
    """Remove decorative symbols while preserving meaningful multilingual text."""
    cleaned_lines: list[str] = []
    for raw_line in strip_emoji_and_pictographs(value).splitlines():
        line = raw_line
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def air_violation_caza_labels(
    text: str,
    default_caza_en: str | None,
    default_caza_ar: str | None,
    known_cazas: list[tuple[str | None, str | None]],
) -> tuple[str | None, str | None]:
    """Label bulletins naming several cazas without choosing a false locality."""
    normalized_text = text.casefold()
    normalized_token_text = _normalize_caza_token(text)
    mentioned: set[tuple[str | None, str | None]] = set()
    known_by_english = {
        _normalize_caza_token(caza_en): (caza_en, caza_ar)
        for caza_en, caza_ar in known_cazas
        if caza_en
    }
    for caza_en, caza_ar in known_cazas:
        names = [name.casefold() for name in (caza_en, caza_ar) if name and len(name) >= 4]
        if any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", normalized_text) for name in names):
            mentioned.add((caza_en, caza_ar))
    for alias, canonical in AIR_VIOLATION_CAZA_ALIASES.items():
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized_token_text):
            mentioned.add(
                known_by_english.get(_normalize_caza_token(canonical[0]), canonical)
            )
    if len(mentioned) > 1:
        return "Multiple regions", "مناطق متعددة"
    if len(mentioned) == 1:
        return next(iter(mentioned))
    return default_caza_en, default_caza_ar


class AirViolationRepository(AirViolationRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def _with_village_labels(self, rows: list[object]) -> list[dict[str, object]]:
        data = [dict(row._mapping) for row in rows]
        village_ids: set[int] = set()
        air_violation_ids: set[int] = set()
        for item in data:
            if item.get("id") is not None:
                air_violation_ids.add(int(item["id"]))
            payload = item.pop("import_payload", None) or {}
            item["is_imported"] = payload.get("import") == "khabar"
            item["import_filename"] = payload.get("filename") if item["is_imported"] else None
            item["import_row"] = payload.get("row") if item["is_imported"] else None
            item["import_enrichment"] = payload.get("enrichment") if item["is_imported"] else None
            item["import_location_text"] = payload.get("location_text") if item["is_imported"] else None
            result = item.pop("raw_match_result", None) or {}
            matches = result.get("village_matches") or []
            raw_match_village_ids = [
                int(match["matched_village_id"])
                for match in matches
                if isinstance(match, dict) and match.get("matched_village_id") is not None
            ]
            matched_village_id = (
                matches[0].get("matched_village_id")
                if matches
                else result.get("matched_village_id")
            )
            for village_id in raw_match_village_ids:
                village_ids.add(village_id)
            if matched_village_id is not None:
                village_id = int(matched_village_id)
                item.setdefault("matched_village_id", village_id)
                village_ids.add(village_id)
            item["raw_match_village_ids"] = raw_match_village_ids
            if item.get("village_id") is not None:
                village_ids.add(int(item["village_id"]))

        location_rows = self.db.execute(
            select(AirViolationLocation.air_violation_id, AirViolationLocation.village_id)
            .where(AirViolationLocation.air_violation_id.in_(air_violation_ids))
            .order_by(AirViolationLocation.id.asc())
        ).all() if air_violation_ids else []
        location_ids_by_air: dict[int, list[int]] = {}
        for air_violation_id, village_id in location_rows:
            location_ids_by_air.setdefault(int(air_violation_id), []).append(int(village_id))
            village_ids.add(int(village_id))

        villages = {
            village.id: village
            for village in self.db.scalars(
                select(Village).where(Village.id.in_(village_ids))
            )
        } if village_ids else {}
        for item in data:
            location_ids = location_ids_by_air.get(int(item["id"]), []) if item.get("id") is not None else []
            if not location_ids:
                location_ids = [
                    village_id
                    for village_id in item.get("raw_match_village_ids", [])
                    if isinstance(village_id, int)
                ]
            location_villages = [villages[village_id] for village_id in location_ids if village_id in villages]
            primary_village_id = item.get("village_id") or item.pop("matched_village_id", None)
            village = villages.get(primary_village_id)
            if village:
                item["caza_en"] = item.get("caza_en") or village.caza_en
                item["caza_ar"] = item.get("caza_ar") or village.caza_ar
            item["village_en"] = (
                village.ref_name_en or village.acs_name or village.cad_name
                if village
                else item.get("caza_en")
            )
            item["village_ar"] = village.ref_name_ar if village else item.get("caza_ar") or item.get("import_location_text")
            village_objects = {
                location_village.id: {
                    "village_id": location_village.id,
                    "name": location_village.ref_name_en
                    or location_village.ref_name_ar
                    or location_village.acs_name
                    or location_village.cad_name,
                    "caza_en": getattr(location_village, "caza_en", None),
                    "caza_ar": getattr(location_village, "caza_ar", None),
                    "mohafaza_en": getattr(location_village, "mohafaza_en", None),
                    "mohafaza_ar": getattr(location_village, "mohafaza_ar", None),
                }
                for location_village in location_villages
                if location_village.ref_name_en
                or location_village.ref_name_ar
                or location_village.acs_name
                or location_village.cad_name
            }
            fallback_name = (
                item.get("import_location_text")
                or item.get("village_en")
                or item.get("village_ar")
            )
            item["villages"] = list(village_objects.values()) or (
                [{"village_id": None, "name": str(fallback_name).strip()}]
                if _normalized_village_name(fallback_name)
                else []
            )
            item.pop("raw_match_village_ids", None)
            item.pop("import_location_text", None)
        return data

    @staticmethod
    def _breach_report(item: dict[str, object]) -> BreachReport:
        return BreachReport(
            id=int(item["id"]),
            condition_id=int(item["condition_id"]),
            event_date=item["event_date"],
            event_time=item.get("event_time"),
            caza_en=item.get("caza_en"),
            caza_ar=item.get("caza_ar"),
            villages=tuple(
                BreachVillage(
                    village_id=village.get("village_id"),
                    name=str(village.get("name") or ""),
                    caza_en=village.get("caza_en"),
                    caza_ar=village.get("caza_ar"),
                    mohafaza_en=village.get("mohafaza_en"),
                    mohafaza_ar=village.get("mohafaza_ar"),
                )
                for village in (item.get("villages") or [])
                if isinstance(village, dict)
            ),
        )

    @classmethod
    def _visible_breaches(
        cls,
        items: list[dict[str, object]],
        context_items: list[dict[str, object]],
    ) -> list[AirViolationBreach]:
        """Breaches computed over ``context_items`` that open inside ``items``.

        A date filter can cut a window in half, so counting runs over the
        wider context and a breach belongs to the filter when the report that
        opens it (its anchor) is one of the filtered rows.
        """
        visible_ids = {int(item["id"]) for item in items}
        breaches = compute_breaches(
            cls._breach_report(item)
            for item in context_items
            if int(item["condition_id"]) in AIR_VIOLATION_CONDITION_IDS
        )
        return [
            breach
            for breach in breaches
            if breach.report_ids and breach.report_ids[0] in visible_ids
        ]

    @staticmethod
    def _breach_village_dicts(breach: AirViolationBreach) -> list[dict[str, object]]:
        return [
            {"village_id": village.village_id, "name": village.name}
            for village in breach.villages
        ]

    @classmethod
    def _window_item(
        cls,
        breach: AirViolationBreach,
        context_by_id: dict[int, dict[str, object]],
    ) -> dict[str, object]:
        reports = [
            context_by_id[report_id]
            for report_id in breach.report_ids
            if report_id in context_by_id
        ]
        unit_village_keys = {village_key(village) for village in breach.villages}
        item = dict(reports[0])
        item["window_id"] = breach.id
        item["window_start"] = breach.window_start
        item["window_end"] = breach.window_end
        item["window_violation_count"] = len(reports)
        item["window_duration_minutes"] = breach.window_minutes
        item["breach_count"] = 1
        item["unit_type"] = breach.unit_type
        item["villages"] = cls._breach_village_dicts(breach)
        if breach.unit_type == "caza" and not breach.needs_review:
            item["caza_en"] = breach.unit_en
            item["caza_ar"] = breach.unit_ar or item.get("caza_ar")
        item["window_reports"] = [
            {
                "id": int(report["id"]),
                "event_date": report["event_date"],
                "event_time": report.get("event_time"),
                "khabar": report.get("khabar") or "",
                "source_name": report.get("source_name") or "Unknown source",
                "source_link": report.get("source_link"),
                "villages": [
                    village
                    for village in (report.get("villages") or [])
                    if not unit_village_keys
                    or village_key(
                        BreachVillage(
                            village_id=village.get("village_id"),
                            name=str(village.get("name") or ""),
                        )
                    ) in unit_village_keys
                ],
            }
            for report in reports
        ]
        return item

    @classmethod
    def _build_display_items(
        cls,
        items: list[dict[str, object]],
        context_items: list[dict[str, object]],
        *,
        oldest_first: bool = False,
    ) -> list[dict[str, object]]:
        """One list entry per warplane/drone breach, one per helicopter/balloon report."""
        context_by_id = {int(item["id"]): item for item in context_items}
        breaches = cls._visible_breaches(items, context_items)
        per_report: dict[int, list[AirViolationBreach]] = {}
        display: list[tuple[datetime, int, dict[str, object]]] = []
        for breach in breaches:
            if breach.condition_id in WINDOWED_CONDITION_IDS:
                entry = cls._window_item(breach, context_by_id)
                display.append((breach.window_start, int(entry["id"]), entry))
            else:
                for report_id in breach.report_ids:
                    per_report.setdefault(report_id, []).append(breach)
        for item in items:
            condition_id = int(item["condition_id"])
            if condition_id in WINDOWED_CONDITION_IDS:
                continue
            entry = dict(item)
            entry["window_id"] = None
            entry["window_start"] = None
            entry["window_end"] = None
            entry["window_violation_count"] = None
            entry["window_duration_minutes"] = None
            entry["window_reports"] = []
            own = per_report.get(int(item["id"]), [])
            if condition_id in PER_REPORT_CONDITION_IDS and own:
                entry["breach_count"] = len(own)
                entry["unit_type"] = own[0].unit_type
            moment = datetime.combine(item["event_date"], item.get("event_time") or time.min)
            display.append((moment, int(item["id"]), entry))
        display.sort(key=lambda row: (row[0], row[1]), reverse=not oldest_first)
        return [row[2] for row in display]

    @staticmethod
    def _location_entries_from_match(result: MatchResultDTO) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        seen: set[int] = set()
        for match in result.village_matches:
            if match.matched_village_id is None or match.matched_village_id in seen:
                continue
            seen.add(match.matched_village_id)
            entries.append({
                "village_id": match.matched_village_id,
                "raw_location_text": match.raw_village_text,
                "evidence_span": match.evidence_span,
            })
        return entries

    def _sync_locations(self, record: AirViolation, entries: list[dict[str, object]]) -> None:
        record.village_id = int(entries[0]["village_id"]) if entries else None
        record.locations = [
            AirViolationLocation(
                village_id=int(entry["village_id"]),
                raw_location_text=entry.get("raw_location_text"),
                evidence_span=entry.get("evidence_span"),
            )
            for entry in entries
        ]

    def create(self, payload: AirViolationCreateDTO) -> AirViolationDTO:
        source = self.db.scalar(
            select(Source).where(Source.external_id == "manual_air_violations")
        )
        if source is None:
            source = Source(
                type=SourceType.manual,
                name="Manual Entry",
                external_id="manual_air_violations",
                config={},
            )
            self.db.add(source)
            self.db.flush()

        record = AirViolation(
            condition_id=payload.condition_id,
            source_id=source.id,
            caza_en=payload.caza_en,
            caza_ar=payload.caza_ar,
            event_month=payload.event_date.strftime("%B"),
            war_month=war_month(payload.event_date),
            event_date=payload.event_date,
            event_time=payload.event_time,
            khabar=payload.khabar,
            note_1=payload.note_1,
            note_2=payload.note_2,
            source_link=payload.source_link,
        )
        self.db.add(record)
        self.db.commit()
        increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        detail = self.get_detail(record.id)
        if detail is None:
            raise RuntimeError("Created air violation could not be loaded.")
        return detail

    def update(
        self,
        air_violation_id: int,
        payload: AirViolationUpdateDTO,
        user_id: UUID,
    ) -> AirViolationDTO | None:
        result = self.db.execute(
            sa_update(AirViolation)
            .where(
                AirViolation.id == air_violation_id,
                AirViolation.version == payload.version,
                AirViolation.locked_by_user_id == user_id,
            )
            .values(
                condition_id=payload.condition_id,
                caza_en=payload.caza_en,
                caza_ar=payload.caza_ar,
                event_month=payload.event_date.strftime("%B"),
                war_month=war_month(payload.event_date),
                event_date=payload.event_date,
                event_time=payload.event_time,
                khabar=payload.khabar,
                note_1=payload.note_1,
                note_2=payload.note_2,
                source_link=payload.source_link,
                version=AirViolation.version + 1,
                locked_by_user_id=None,
                edit_lock_expires_at=None,
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(AirViolation, air_violation_id) is None:
                return None
            raise StaleDataError("Air violation version is stale.")
        self.db.commit()
        increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        return self.get_detail(air_violation_id)

    def delete(self, air_violation_id: int, version: int, user_id: UUID) -> bool:
        violation = self.db.scalar(
            select(AirViolation).where(
                AirViolation.id == air_violation_id,
                AirViolation.version == version,
                AirViolation.locked_by_user_id == user_id,
            )
        )
        if violation is None:
            self.db.rollback()
            if self.db.get(AirViolation, air_violation_id) is None:
                return False
            raise StaleDataError("Air violation version is stale.")

        rejection = {
            "reason": "Rejected from the Air Violations review by an administrator.",
            "rejected_by": str(user_id),
            "rejected_at": datetime.now(BEIRUT_TIMEZONE).isoformat(),
            "air_violation_id": air_violation_id,
        }
        message = (
            self.db.get(RawMessage, violation.raw_message_id)
            if violation.raw_message_id is not None
            else None
        )
        if message is None:
            source = self.db.get(Source, violation.source_id)
            message = RawMessage(
                source_id=violation.source_id,
                source_platform=source.type.value if source is not None else "manual",
                source_name=source.name if source is not None else "Manual",
                raw_text=violation.khabar,
                raw_payload={"admin_air_violation_rejection": rejection},
                message_datetime=datetime.combine(
                    violation.event_date,
                    violation.event_time or time.min,
                    tzinfo=BEIRUT_TIMEZONE,
                ),
                status=MessageStatus.rejected,
                error_message=rejection["reason"],
            )
            self.db.add(message)
        else:
            payload = dict(message.raw_payload or {})
            payload["admin_air_violation_rejection"] = rejection
            message.raw_payload = payload
            message.status = MessageStatus.rejected
            message.duplicate_of_id = None
            message.error_message = rejection["reason"]
            self.db.add(message)

        result = self.db.execute(
            sa_delete(AirViolation).where(
                AirViolation.id == air_violation_id,
                AirViolation.version == version,
                AirViolation.locked_by_user_id == user_id,
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            raise StaleDataError("Air violation version is stale.")
        self.db.commit()
        increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        return True

    def acquire_edit_lock(self, air_violation_id: int, user_id: UUID) -> AirViolationDTO | None:
        now = datetime.now(BEIRUT_TIMEZONE)
        result = self.db.execute(
            sa_update(AirViolation)
            .where(
                AirViolation.id == air_violation_id,
                (
                    AirViolation.locked_by_user_id.is_(None)
                    | (AirViolation.edit_lock_expires_at <= now)
                    | (AirViolation.locked_by_user_id == user_id)
                ),
            )
            .values(
                locked_by_user_id=user_id,
                edit_lock_expires_at=now + timedelta(minutes=5),
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(AirViolation, air_violation_id) is None:
                return None
            raise StaleDataError("Air violation is being edited by another administrator.")
        self.db.commit()
        return self.get_detail(air_violation_id)

    def release_edit_lock(self, air_violation_id: int, user_id: UUID) -> bool:
        result = self.db.execute(
            sa_update(AirViolation)
            .where(
                AirViolation.id == air_violation_id,
                AirViolation.locked_by_user_id == user_id,
            )
            .values(locked_by_user_id=None, edit_lock_expires_at=None)
        )
        self.db.commit()
        return result.rowcount > 0

    @staticmethod
    def _item_query(query_filters: list[object]):
        return (
            select(
                AirViolation.id,
                AirViolation.raw_message_id,
                AirViolation.condition_id,
                AirViolation.source_id,
                AirViolation.village_id,
                AirViolation.caza_en,
                AirViolation.caza_ar,
                AirViolation.event_month,
                AirViolation.war_month,
                AirViolation.event_date,
                AirViolation.event_time,
                AirViolation.window_id,
                AirViolation.khabar,
                AirViolation.note_1,
                AirViolation.note_2,
                AirViolation.source_link,
                AirViolation.version,
                AirViolation.locked_by_user_id,
                AirViolation.edit_lock_expires_at,
                AirViolation.created_at,
                RawMessage.match_result.label("raw_match_result"),
                RawMessage.raw_payload.label("import_payload"),
                func.coalesce(Condition.action_en, "Unknown air activity").label("action_en"),
                func.coalesce(Condition.action_ar, "خرق جوي").label("action_ar"),
                case(
                    (RawMessage.raw_payload['import'].as_string() == 'khabar', func.coalesce(RawMessage.source_name, Source.name)),
                    (RawMessage.source_name == "Red Alert Lebanon", RawMessage.source_name),
                    (
                        RawMessage.id.is_not(None),
                        func.coalesce(
                            func.nullif(RawMessage.origin_account, "CNRS Webhook"),
                            func.nullif(RawMessage.source_name, "CNRS Webhook"),
                            "Unknown source",
                        ),
                    ),
                    else_=func.coalesce(Source.name, "Unknown source"),
                ).label("source_name"),
            )
            .outerjoin(Condition, Condition.id == AirViolation.condition_id)
            .outerjoin(Source, Source.id == AirViolation.source_id)
            .outerjoin(RawMessage, RawMessage.id == AirViolation.raw_message_id)
            .where(*query_filters)
        )

    def _load_items(
        self,
        params: AirViolationListParams,
        *,
        supported_only: bool,
        ordering: tuple[object, ...] | None = None,
    ) -> list[dict[str, object]]:
        query = self._item_query(self._filters(params, supported_only=supported_only))
        query = query.order_by(*(ordering or (
            AirViolation.event_date.desc(),
            AirViolation.event_time.desc().nullslast(),
            AirViolation.id.desc(),
        )))
        return self._with_village_labels(self.db.execute(query).all())

    def _context_items(
        self,
        params: AirViolationListParams,
        items: list[dict[str, object]],
        *,
        supported_only: bool,
    ) -> list[dict[str, object]]:
        """Rows around the filtered ones so a window cut by the filter stays whole."""
        if not items or (
            params.event_date_from is None
            and params.event_date_to is None
            and params.last_hours is None
        ):
            return items
        event_dates = [item["event_date"] for item in items]
        context_params = params.model_copy(update={
            "limit": 100,
            "offset": 0,
            "event_date_from": min(event_dates) - timedelta(days=1),
            "event_date_to": max(event_dates) + timedelta(days=1),
            "last_hours": None,
        })
        return self._load_items(context_params, supported_only=supported_only)

    def list_all(self, params: AirViolationListParams) -> AirViolationListResponse:
        if params.sort_order == "oldest":
            ordering = (
                AirViolation.event_date.asc(),
                AirViolation.event_time.asc().nullslast(),
                AirViolation.id.asc(),
            )
        else:
            ordering = None
        items = self._load_items(params, supported_only=False, ordering=ordering)
        context = self._context_items(params, items, supported_only=False)
        display_items = self._build_display_items(
            items, context, oldest_first=params.sort_order == "oldest"
        )
        page_items = display_items[params.offset:params.offset + params.limit]

        return AirViolationListResponse(
            items=[
                AirViolationDTO.model_validate(item)
                for item in page_items
            ],
            total=len(display_items),
            limit=params.limit,
            offset=params.offset,
        )

    def get_summary(self, params: AirViolationListParams) -> AirViolationSummaryDTO:
        """Breach counts per CNRS methodology (not row counts)."""
        items = self._load_items(params, supported_only=True)
        context = self._context_items(params, items, supported_only=True)
        counts = count_breaches_by_condition(self._visible_breaches(items, context))
        return AirViolationSummaryDTO(
            warplanes=counts[AIR_VIOLATION_WARPLANE_CONDITION_ID],
            surveillance_aircraft=counts[AIR_VIOLATION_DRONE_CONDITION_ID],
            helicopters=counts[AIR_VIOLATION_HELICOPTER_CONDITION_ID],
            spy_balloons=counts[AIR_VIOLATION_SPY_BALLOON_CONDITION_ID],
        )

    def get_detail(self, air_violation_id: int) -> AirViolationDTO | None:
        row = self.db.execute(
            select(
                AirViolation.id,
                AirViolation.raw_message_id,
                AirViolation.condition_id,
                AirViolation.source_id,
                AirViolation.village_id,
                AirViolation.caza_en,
                AirViolation.caza_ar,
                AirViolation.event_month,
                AirViolation.war_month,
                AirViolation.event_date,
                AirViolation.event_time,
                AirViolation.window_id,
                AirViolation.khabar,
                AirViolation.note_1,
                AirViolation.note_2,
                AirViolation.source_link,
                AirViolation.version,
                AirViolation.locked_by_user_id,
                AirViolation.edit_lock_expires_at,
                AirViolation.created_at,
                RawMessage.match_result.label("raw_match_result"),
                RawMessage.raw_payload.label("import_payload"),
                func.coalesce(Condition.action_en, "Unknown air activity").label("action_en"),
                func.coalesce(Condition.action_ar, "خرق جوي").label("action_ar"),
                case(
                    (RawMessage.raw_payload['import'].as_string() == 'khabar', func.coalesce(RawMessage.source_name, Source.name)),
                    (RawMessage.source_name == "Red Alert Lebanon", RawMessage.source_name),
                    (
                        RawMessage.id.is_not(None),
                        func.coalesce(
                            func.nullif(RawMessage.origin_account, "CNRS Webhook"),
                            func.nullif(RawMessage.source_name, "CNRS Webhook"),
                            "Unknown source",
                        ),
                    ),
                    else_=func.coalesce(Source.name, "Unknown source"),
                ).label("source_name"),
            )
            .outerjoin(Condition, Condition.id == AirViolation.condition_id)
            .outerjoin(Source, Source.id == AirViolation.source_id)
            .outerjoin(RawMessage, RawMessage.id == AirViolation.raw_message_id)
            .where(AirViolation.id == air_violation_id)
        ).one_or_none()
        if row is None:
            return None
        return AirViolationDTO.model_validate(self._with_village_labels([row])[0])
    def route_from_match(self, message: RawMessage, result: MatchResultDTO) -> bool:
        if result.matched_condition_id not in AIR_VIOLATION_CONDITION_IDS:
            return False
        # Import lazily: the collector depends on this repository when it
        # persists routed messages.
        from app.sources.services.red_alert_collector import (
            aircraft_term_conflict,
            classify_condition,
            has_helicopter_keyword,
        )

        # The deterministic aircraft vocabulary is authoritative over an LLM
        # label. In Lebanese Arabic, مسيّرة/مسير and محلقة mean drone/UAV and
        # therefore map to Surveillance Aircraft (36), never Helicopter (38).
        classified_condition_id = classify_condition(message.raw_text or "")
        if (
            classified_condition_id in AIR_VIOLATION_CONDITION_IDS
            and classified_condition_id != result.matched_condition_id
        ):
            result = result.model_copy(
                update={"matched_condition_id": classified_condition_id}
            )
        if (
            result.matched_condition_id == AIR_VIOLATION_HELICOPTER_CONDITION_ID
            and not has_helicopter_keyword(message.raw_text or "")
        ):
            # A helicopter breach needs the word itself. A label without it
            # (and no deterministic drone/warplane reading) is not written.
            record_air_violation_outcome(
                message,
                EligibilityResult(
                    eligible=False,
                    reason=HELICOPTER_LABEL_WITHOUT_KEYWORD_REASON,
                    matched_terms=[],
                ),
                stage="air_violation_repository",
            )
            return False
        conflict = aircraft_term_conflict(message.raw_text or "")
        if conflict:
            audit = dict(message.filter_result or {})
            audit["air_aircraft_terms"] = conflict
            message.filter_result = audit
        eligibility = evaluate_air_violation_text(message.raw_text)
        if not eligibility.eligible:
            # The last post-LLM boundary. Whatever the model chose, a rejected
            # text never becomes an air violation here, and a reject_no_incident
            # result is never handed back to the incident pipeline.
            record_air_violation_outcome(message, eligibility, stage="air_violation_repository")
            return False
        matched_village_id: int | None = next(
            (
                vm.matched_village_id
                for vm in result.village_matches
                if vm.matched_village_id is not None
            ),
            None,
        )
        existing = self.db.scalar(
            select(AirViolation).where(AirViolation.raw_message_id == message.id)
        )
        village = self.db.get(Village, matched_village_id) if matched_village_id is not None else None
        if matched_village_id is not None and village is None:
            return False
        condition = self.db.get(Condition, result.matched_condition_id)
        occurred_at = as_beirut_datetime(message.message_datetime or message.received_at)
        payload = message.raw_payload or {}
        link = next((payload.get(key) for key in ("source_link", "link", "url", "post_url") if payload.get(key)), None)
        known_cazas = list(
            self.db.execute(select(Village.caza_en, Village.caza_ar).distinct()).all()
        )
        caza_en, caza_ar = air_violation_caza_labels(
            message.raw_text or "",
            village.caza_en if village else None,
            village.caza_ar if village else None,
            known_cazas,
        )
        matched_village_ids = [
            vm.matched_village_id
            for vm in result.village_matches
            if vm.matched_village_id is not None
        ]
        matched_villages = [
            self.db.get(Village, village_id)
            for village_id in dict.fromkeys(matched_village_ids)
        ]
        matched_villages = [item for item in matched_villages if item is not None]
        matched_cazas = {
            (matched_village.caza_en, matched_village.caza_ar)
            for matched_village in matched_villages
            if matched_village.caza_en or matched_village.caza_ar
        }
        if len(matched_cazas) > 1:
            caza_en, caza_ar = "Multiple regions", "مناطق متعددة"
        elif len(matched_cazas) == 1:
            caza_en, caza_ar = next(iter(matched_cazas))
        # Rules C/D/E. An air violation needs a place: a resolved village, or
        # failing that a recognised region. "Multiple regions" earned from
        # several matched cazas is a real designation and still passes; the
        # same label earned from a bare "لبنان" is rule D and does not.
        location = evaluate_air_violation_location(
            message.raw_text,
            has_resolved_village=matched_village_id is not None,
            caza_label=caza_en or caza_ar,
            unmatched_names=tuple(
                vm.raw_village_text
                for vm in result.village_matches
                if vm.matched_village_id is None and vm.raw_village_text
            ),
        )
        if not location.eligible:
            record_air_violation_outcome(
                message, location, stage="air_violation_repository"
            )
            return False
        values = {
            "condition_id": result.matched_condition_id,
            "source_id": message.source_id,
            "caza_en": caza_en,
            "caza_ar": caza_ar,
            "event_month": occurred_at.strftime("%B"),
            "war_month": war_month(occurred_at.date()),
            "event_date": occurred_at.date(),
            "event_time": occurred_at.time().replace(tzinfo=None),
            "khabar": air_violation_news_text(message, village, condition, matched_villages),
            "note_1": payload.get("note_1") or payload.get("note"),
            "note_2": payload.get("note_2"),
            "source_link": str(link) if link else None,
        }
        if (
            existing is None
            and not self._should_bypass_recent_duplicate_check(message, result)
            and self._has_recent_air_violation(
                occurred_at,
                condition_id=result.matched_condition_id,
                khabar=values["khabar"],
            )
        ):
            return False
        if existing is None:
            existing = AirViolation(raw_message_id=message.id, **values)
            self._sync_locations(existing, self._location_entries_from_match(result))
            self.db.add(existing)
        else:
            for field, value in values.items():
                setattr(existing, field, value)
            self._sync_locations(existing, self._location_entries_from_match(result))
        self.db.commit()
        increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        return True

    @staticmethod
    def _has_strong_message_identity(message: RawMessage) -> bool:
        payload = message.raw_payload or {}
        identity = message.external_message_id or payload.get("external_message_id")
        return bool(
            identity
            and (
                message.source_platform == "telegram"
                or str(identity).startswith("telegram:")
                or payload.get("source_link")
                or payload.get("link")
                or payload.get("url")
                or payload.get("post_url")
            )
        )

    @classmethod
    def _should_bypass_recent_duplicate_check(
        cls,
        message: RawMessage,
        result: MatchResultDTO,
    ) -> bool:
        # A stable upstream message ID identifies a real report. Preserve each
        # locality-specific report so its villages and source remain available
        # inside the surveillance window details.
        return cls._has_strong_message_identity(message) and bool(result.village_matches)

    def _has_recent_air_violation(
        self,
        occurred_at: datetime,
        *,
        condition_id: int,
        khabar: str | None,
    ) -> bool:
        """True only for an exact re-post: same condition, same text, within 10 minutes.

        Counting windows live in ``breach_counting_service``; ingest never
        drops a report because a nearby one exists. Text-less reports are never
        treated as duplicates.
        """
        normalized_khabar = _normalize_duplicate_text(khabar)
        if not normalized_khabar:
            return False
        cutoff = occurred_at - timedelta(minutes=AIR_VIOLATION_DUPLICATE_WINDOW_MINUTES)
        existing_records = self.db.scalars(
            select(AirViolation).where(
                AirViolation.condition_id == condition_id,
                AirViolation.event_date >= cutoff.date(),
                AirViolation.event_date <= occurred_at.date(),
            )
        ).all()
        occurred_naive = occurred_at.replace(tzinfo=None)
        cutoff_naive = cutoff.replace(tzinfo=None)
        return any(
            cutoff_naive <= _air_violation_event_datetime(record) <= occurred_naive
            and _normalize_duplicate_text(record.khabar) == normalized_khabar
            for record in existing_records
        )

    @staticmethod
    def _filters(params: AirViolationListParams, *, supported_only: bool = True) -> list[object]:
        filters: list[object] = []
        if supported_only:
            filters.append(AirViolation.condition_id.in_(AIR_VIOLATION_CONDITION_ID_TUPLE))
        if params.imported_only:
            filters.append(AirViolation.raw_message_id.in_(
                select(RawMessage.id).where(RawMessage.raw_payload['import'].as_string() == 'khabar')
            ))
        if params.condition_id is not None:
            filters.append(AirViolation.condition_id == params.condition_id)
        if params.event_date_from is not None:
            filters.append(AirViolation.event_date >= params.event_date_from)
        if params.event_date_to is not None:
            filters.append(AirViolation.event_date <= params.event_date_to)
        if params.last_hours is not None:
            cutoff = datetime.now(BEIRUT_TIMEZONE) - timedelta(hours=params.last_hours)
            event_time = func.coalesce(AirViolation.event_time, time.min)
            filters.append(
                (AirViolation.event_date > cutoff.date())
                | (
                    (AirViolation.event_date == cutoff.date())
                    & (event_time >= cutoff.time().replace(tzinfo=None))
                )
            )
        if params.caza_en:
            caza = canonicalize_caza(params.caza_en) or params.caza_en
            filters.append(AirViolation.caza_en.ilike(f"%{caza}%"))
        if params.village:
            village_pattern = f"%{params.village}%"
            matching_locations = (
                select(AirViolationLocation.air_violation_id)
                .join(Village, Village.id == AirViolationLocation.village_id)
                .where(
                    or_(
                        Village.ref_name_en.ilike(village_pattern),
                        Village.ref_name_ar.ilike(village_pattern),
                        Village.acs_name.ilike(village_pattern),
                        Village.cad_name.ilike(village_pattern),
                    )
                )
            )
            matching_primary_villages = (
                select(Village.id).where(
                    or_(
                        Village.ref_name_en.ilike(village_pattern),
                        Village.ref_name_ar.ilike(village_pattern),
                        Village.acs_name.ilike(village_pattern),
                        Village.cad_name.ilike(village_pattern),
                    )
                )
            )
            filters.append(
                or_(
                    AirViolation.id.in_(matching_locations),
                    AirViolation.village_id.in_(matching_primary_villages),
                )
            )
        return filters

    def list_windows(self, params: AirViolationListParams) -> AirViolationWindowListResponse:
        items = self._load_items(
            params,
            supported_only=True,
            ordering=(
                AirViolation.event_date.asc(),
                AirViolation.event_time.asc().nullsfirst(),
                AirViolation.id.asc(),
            ),
        )
        context = self._context_items(params, items, supported_only=True)
        grouped = self._visible_breaches(items, context)
        total = len(grouped)
        paged = grouped[params.offset: params.offset + params.limit]
        return AirViolationWindowListResponse(
            items=[
                AirViolationWindowDTO(
                    id=item.id,
                    condition_id=item.condition_id,
                    unit_type=item.unit_type,
                    caza_en=item.unit_en,
                    caza_ar=item.unit_ar,
                    window_start=item.window_start,
                    window_end=item.window_end,
                    window_duration_minutes=item.window_minutes,
                    violation_count=len(item.report_ids),
                    villages=self._breach_village_dicts(item),
                )
                for item in paged
            ],
            total=total,
            limit=params.limit,
            offset=params.offset,
        )

    def discard_for_message(self, message: RawMessage) -> None:
        existing = self.db.scalar(
            select(AirViolation).where(AirViolation.raw_message_id == message.id)
        )
        if existing is not None:
            self.db.delete(existing)
            self.db.flush()
            increment(AIR_VIOLATION_CACHE_VERSION_KEY)
