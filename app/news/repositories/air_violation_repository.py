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
    RawMessage,
    Village,
)
from app.news.services.air_violations.window_grouping_service import (
    AirViolationWindowInput,
    AirViolationWindowVillage,
    assign_air_violation_window_ids,
    group_air_violation_windows,
    surveillance_window_minutes,
)
from app.news.services.air_violations.caza_alias_resolver import canonicalize_caza
from app.news.services.air_violations.air_violation_eligibility import (
    evaluate_air_violation_location,
    evaluate_air_violation_text,
)
from app.news.services.air_violations.air_violation_routing import (
    record_air_violation_outcome,
)
from app.news.services.air_violations.war_month import war_month
from app.sources.models import Source, SourceType
from app.sources.services.red_alert_collector import classify_condition


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
AIR_VIOLATION_WARPLANE_CAZA_HOURS = 4
AIR_VIOLATION_DEFAULT_CAZA_HOURS = 1


def _normalize_caza_token(value: str) -> str:
    return re.sub(r"[\W_]+", " ", value.casefold()).strip()


def _normalized_village_name(value: object) -> str:
    return " ".join(normalize_arabic_text(str(value or "")).casefold().split())


def air_violation_caza_window_hours(caza_en: str | None, condition_id: int | None = None) -> int:
    if condition_id == AIR_VIOLATION_WARPLANE_CONDITION_ID:
        return AIR_VIOLATION_WARPLANE_CAZA_HOURS
    if condition_id == AIR_VIOLATION_DRONE_CONDITION_ID:
        minutes = surveillance_window_minutes(caza_en)
        return max(1, (minutes or 60) // 60)
    return AIR_VIOLATION_DEFAULT_CAZA_HOURS


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
    def _air_violation_window_input(item: dict[str, object]) -> AirViolationWindowInput:
        return AirViolationWindowInput(
            id=int(item["id"]),
            condition_id=int(item["condition_id"]),
            caza_en=item.get("caza_en"),
            caza_ar=item.get("caza_ar"),
            event_date=item["event_date"],
            event_time=item.get("event_time"),
            villages=tuple(
                AirViolationWindowVillage(
                    village_id=village.get("village_id"),
                    name=str(village.get("name") or ""),
                )
                for village in (item.get("villages") or [])
                if isinstance(village, dict)
            ),
        )

    @staticmethod
    def _attach_window_metadata(
        items: list[dict[str, object]],
        all_items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        assignments = assign_air_violation_window_ids(
            AirViolationRepository._air_violation_window_input(item)
            for item in all_items
        )
        window_stats: dict[str, dict[str, object]] = {}
        for item in sorted(
            all_items,
            key=lambda row: (
                row["event_date"],
                row.get("event_time") or time.min,
                int(row["id"]),
            ),
        ):
            if int(item["condition_id"]) != 36:
                continue
            item_id = int(item["id"])
            window_id = assignments.get(item_id) or item.get("window_id")
            if not window_id:
                continue
            item_dt = datetime.combine(item["event_date"], item.get("event_time") or time.min)
            stats = window_stats.setdefault(
                str(window_id),
                {"start": item_dt, "end": item_dt, "count": 0, "villages": [], "reports": []},
            )
            stats["start"] = min(stats["start"], item_dt)
            stats["end"] = max(stats["end"], item_dt)
            stats["count"] = int(stats["count"]) + 1
            villages_by_key = {
                (
                    ("id", village.get("village_id"))
                    if village.get("village_id") is not None
                    else ("name", _normalized_village_name(village.get("name")))
                ): village
                for village in stats["villages"]
            }
            for village in item.get("villages") or []:
                key = (
                    ("id", village.get("village_id"))
                    if village.get("village_id") is not None
                    else ("name", _normalized_village_name(village.get("name")))
                )
                villages_by_key.setdefault(key, village)
            stats["villages"] = list(villages_by_key.values())
            stats["reports"].append({
                "id": item_id,
                "event_date": item["event_date"],
                "event_time": item.get("event_time"),
                "khabar": item.get("khabar") or "",
                "source_name": item.get("source_name") or "Unknown source",
                "source_link": item.get("source_link"),
                "villages": list(item.get("villages") or []),
            })

        for item in items:
            if int(item["condition_id"]) != 36:
                item["window_id"] = None
                item["window_start"] = None
                item["window_end"] = None
                item["window_violation_count"] = None
                item["window_duration_minutes"] = None
                item["window_reports"] = []
                continue
            window_duration_minutes = surveillance_window_minutes(item.get("caza_en"))
            if window_duration_minutes is None:
                item["window_id"] = None
                item["window_start"] = None
                item["window_end"] = None
                item["window_violation_count"] = None
                item["window_duration_minutes"] = None
                item["window_reports"] = []
                continue
            item_id = int(item["id"])
            window_id = assignments.get(item_id) or item.get("window_id")
            item["window_id"] = window_id
            stats = window_stats.get(str(window_id)) if window_id else None
            item["window_start"] = stats["start"] if stats else None
            item["window_end"] = stats["end"] if stats else None
            item["window_violation_count"] = stats["count"] if stats else None
            item["window_duration_minutes"] = window_duration_minutes
            if stats:
                item["villages"] = list(stats["villages"])
                item["window_reports"] = sorted(
                    stats["reports"],
                    key=lambda report: (
                        report["event_date"],
                        report["event_time"] or time.min,
                        report["id"],
                    ),
                )
            else:
                item["window_reports"] = []
        return items

    @staticmethod
    def _collapse_windowed_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
        collapsed: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in items:
            window_id = item.get("window_id")
            key = (
                str(window_id)
                if window_id and int(item["condition_id"]) == 36
                else f"record-{item['id']}"
            )
            if key in seen:
                continue
            seen.add(key)
            collapsed.append(item)
        return collapsed

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
        result = self.db.execute(
            sa_delete(AirViolation).where(
                AirViolation.id == air_violation_id,
                AirViolation.version == version,
                AirViolation.locked_by_user_id == user_id,
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(AirViolation, air_violation_id) is None:
                return False
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

    def list_all(self, params: AirViolationListParams) -> AirViolationListResponse:
        filters = self._filters(params, supported_only=False)

        def list_query(query_filters: list[object]):
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

        if params.sort_order == "oldest":
            ordering = (
                AirViolation.event_date.asc(),
                AirViolation.event_time.asc().nullslast(),
                AirViolation.id.asc(),
            )
        else:
            ordering = (
                AirViolation.event_date.desc(),
                AirViolation.event_time.desc().nullslast(),
                AirViolation.id.desc(),
            )
        all_rows = self.db.execute(list_query(filters).order_by(*ordering)).all()
        all_items = self._with_village_labels(all_rows)
        window_context_items = all_items
        if all_items and (
            params.event_date_from is not None
            or params.event_date_to is not None
            or params.last_hours is not None
        ):
            # A filter can begin or end in the middle of a 1/4-hour window.
            # Include the adjacent dates while calculating metadata so details
            # still show every report and village belonging to that window.
            event_dates = [item["event_date"] for item in all_items]
            context_params = params.model_copy(update={
                "limit": 100,
                "offset": 0,
                "event_date_from": min(event_dates) - timedelta(days=1),
                "event_date_to": max(event_dates) + timedelta(days=1),
                "last_hours": None,
            })
            context_rows = self.db.execute(
                list_query(self._filters(context_params, supported_only=False)).order_by(
                    AirViolation.event_date.desc(),
                    AirViolation.event_time.desc().nullslast(),
                    AirViolation.id.desc(),
                )
            ).all()
            window_context_items = self._with_village_labels(context_rows)
        all_items = self._attach_window_metadata(all_items, window_context_items)
        display_items = self._collapse_windowed_items(all_items)
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
        rows = self.db.execute(
            select(
                AirViolation.condition_id,
            )
            .where(*self._filters(params, supported_only=True))
        ).all()
        counts: dict[int, int] = {}
        for row in rows:
            condition_id = int(row.condition_id)
            counts[condition_id] = counts.get(condition_id, 0) + 1
        return AirViolationSummaryDTO(
            warplanes=counts.get(35, 0),
            surveillance_aircraft=counts.get(36, 0),
            helicopters=counts.get(38, 0),
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
        duplicate_khabar = (
            values["khabar"]
            if self._requires_exact_duplicate_text(result)
            else None
        )
        if (
            existing is None
            and result.matched_condition_id != AIR_VIOLATION_WARPLANE_CONDITION_ID
            and not self._should_bypass_recent_duplicate_check(message, result)
            and self._has_recent_air_violation(
                caza_en,
                caza_ar,
                occurred_at,
                condition_id=result.matched_condition_id,
                khabar=duplicate_khabar,
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

    @staticmethod
    def _requires_exact_duplicate_text(result: MatchResultDTO) -> bool:
        return bool(result.village_matches)

    def _has_recent_air_violation(
        self,
        caza_en: str | None,
        caza_ar: str | None,
        occurred_at: datetime,
        *,
        condition_id: int,
        khabar: str | None,
    ) -> bool:
        window_hours = air_violation_caza_window_hours(caza_en, condition_id)
        cutoff = occurred_at - timedelta(hours=window_hours)
        filters = [
            AirViolation.condition_id == condition_id,
            AirViolation.event_date >= cutoff.date(),
            AirViolation.event_date <= occurred_at.date(),
        ]
        if caza_en:
            filters.append(AirViolation.caza_en == caza_en)
        elif caza_ar:
            filters.append(AirViolation.caza_ar == caza_ar)
        else:
            filters.append(AirViolation.caza_en.is_(None))
            filters.append(AirViolation.caza_ar.is_(None))
        existing_records = self.db.scalars(select(AirViolation).where(*filters)).all()
        occurred_naive = occurred_at.replace(tzinfo=None)
        cutoff_naive = cutoff.replace(tzinfo=None)
        normalized_khabar = _normalize_duplicate_text(khabar)
        return any(
            cutoff_naive <= _air_violation_event_datetime(record) <= occurred_naive
            and (
                normalized_khabar == ""
                or _normalize_duplicate_text(record.khabar) == normalized_khabar
            )
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
        filters = self._filters(
            params.model_copy(update={"limit": 100, "offset": 0}),
            supported_only=True,
        )
        rows = self.db.execute(
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
                func.coalesce(Source.name, "Unknown source").label("source_name"),
            )
            .outerjoin(Condition, Condition.id == AirViolation.condition_id)
            .outerjoin(Source, Source.id == AirViolation.source_id)
            .outerjoin(RawMessage, RawMessage.id == AirViolation.raw_message_id)
            .where(*filters)
            .order_by(AirViolation.event_date.asc(), AirViolation.event_time.asc().nullsfirst(), AirViolation.id.asc())
        ).all()
        items = self._with_village_labels(rows)
        grouped = group_air_violation_windows(
            self._air_violation_window_input(item)
            for item in items
        )
        total = len(grouped)
        paged = grouped[params.offset: params.offset + params.limit]
        return AirViolationWindowListResponse(
            items=[
                AirViolationWindowDTO(
                    id=item.id,
                    caza_en=item.caza_en,
                    caza_ar=item.caza_ar,
                    window_start=item.window_start,
                    window_end=item.window_end,
                    violation_count=item.violation_count,
                    villages=list(item.villages),
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
