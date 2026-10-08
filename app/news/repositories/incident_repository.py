import base64
import hashlib
import json
import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import (
    and_,
    String,
    case,
    cast,
    desc,
    false,
    func,
    literal,
    or_,
    select,
    true,
    update as sa_update,
)
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import settings
from app.core.text_normalization import normalize_arabic_sql
from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.llm.dtos import ExtractedCandidate
from app.news.constants.air_violation_conditions import AIR_VIOLATION_CONDITION_ID_TUPLE
from app.news.dtos import (
    CasualtyDemographicsDTO,
    DuplicateCandidateIncidentDTO,
    IncidentDetailDTO,
    IncidentDuplicateCandidateDTO,
    IncidentDuplicateResolutionResultDTO,
    IncidentBulletinGroupDTO,
    IncidentCreateDTO,
    IncidentVillageDetailDTO,
    IncidentListItemDTO,
    IncidentListParams,
    IncidentListResponse,
    IncidentUpdateDTO,
    RelatedIncidentDTO,
    TollRevisionDTO,
)
from app.news.interfaces import IncidentRepositoryInterface
from app.news.models import (
    BulletinCasualtyGroup,
    Condition,
    DeletedReason,
    DuplicateMatch,
    Incident,
    IncidentDetail,
    IncidentOrigin,
    IncidentUpdate,
    MatchStatus,
    MatchType,
    MessageStatus,
    RawMessage,
    UpdateAction,
    Village,
)
from app.news.models.incident_verification_flag import IncidentVerificationFlag
from app.news.models.summary_bulletin import SummaryBulletin, SummaryItem
from app.news.services.incident_details.incident_detail_category_serializer import (
    serialize_incident_category_sections,
)
from app.news.services.incident_details.incident_detail_edit_service import (
    IncidentDetailEditError,
    apply_incident_detail_edits,
)
from app.news.services.incident_details.casualty_transition_merge import (
    apply_casualty_transitions,
    parse_casualty_transitions,
    sync_transition_totals,
)
from app.news.services.incident_details.casualty_transition_backstop import (
    detect_casualty_transition_backstop,
)
from app.news.services.incident_details.casualty_status import merge_casualty_status
from app.news.services.incident_details.casualty_merge_guard import guard_casualty_merge
from app.news.services.incident_details.casualty_status import target_location_count_from_extraction
from app.news.services.incident_details.incident_detail_merge import (
    merge_incident_detail_fields,
)
from app.news.services.dedup.text_similarity import (
    balanced_event_token_similarity,
    event_token_similarity,
)
from app.news.services.materialization.verification_signals import (
    active_non_duplicate_verification_reasons,
    extract_quality_flags,
)
from app.news.services.incidents.incident_change_log import (
    changed_fields,
    record_incident_change,
)
from app.news.services.incidents.soft_delete import soft_delete_incident
from app.news.services.materialization.verification_signals import (
    LOW_CONFIDENCE_VILLAGE_REVIEW_REASON,
)
from app.news.services.casualty_flag_evaluator import evaluate_casualty_flags_safely
from app.sources.models import Source, SourceType

logger = logging.getLogger(__name__)



def _optional_count(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


@dataclass(frozen=True)
class FastDedupCandidate:
    """An active same-village + same-condition incident considered by the
    fast-path incident-level dedup, with the signals DuplicateComparisonService
    needs to return a verdict."""

    incident: Incident
    time_gap_seconds: float
    text_similarity: float | None
    embedding_similarity: float | None
    token_similarity: float | None = None


@dataclass(frozen=True)
class StoryCandidate:
    """Prior incident in the story-continuation window (no condition gate)."""

    incident: Incident
    time_gap_seconds: float
    embedding_similarity: float | None
    text_similarity: float | None = None
    token_similarity: float | None = None


@dataclass(frozen=True)
class SegmentReviewSource:
    """Materialized cross-source incident plus its persisted extraction shape."""

    incident: Incident
    extraction_result: dict[str, Any]
    match_result: dict[str, Any]
    raw_text: str | None = None
    message_datetime: datetime | None = None


class IncidentRepository(IncidentRepositoryInterface):
    _ENABLED_VERIFICATION_FLAG_TYPES = ("casualty_check",)
    _FLAG_LABELS = {"count_missing": "Missing number", "aggregate_no_breakdown": "Aggregate toll"}
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _war_context_text_filter(text_expr) -> object:
        patterns = (
            "%israel%",
            "%israeli%",
            "%idf%",
            "%enemy%",
            "%war%",
            "%military%",
            "%security%",
            "%strike%",
            "%airstrike%",
            "%shelling%",
            "%bombardment%",
            "%missile%",
            "%rocket%",
            "%drone%",
            "%raid%",
            "%targeted%",
            "%إسرائيل%",
            "%اسرائيل%",
            "%إسرائيلي%",
            "%اسرائيلي%",
            "%العدو%",
            "%حرب%",
            "%حربي%",
            "%أمني%",
            "%امني%",
            "%عسكري%",
            "%غارة%",
            "%غارات%",
            "%قصف%",
            "%استهداف%",
            "%استهدف%",
            "%صاروخ%",
            "%صواريخ%",
            "%مسيرة%",
        )
        return or_(*(text_expr.ilike(pattern) for pattern in patterns))

    @staticmethod
    def _palestine_scope_text_filter(text_expr) -> object:
        patterns = (
            "%palestine%",
            "%gaza%",
            "%ramallah%",
            "%west bank%",
            "%nablus%",
            "%jenin%",
            "%khan younis%",
            "%rafah%",
            "%فلسطين%",
            "%غزة%",
            "%رام الله%",
            "%رامالله%",
            "%الضفة الغربية%",
            "%نابلس%",
            "%جنين%",
            "%خان يونس%",
            "%رفح%",
        )
        return or_(*(text_expr.ilike(pattern) for pattern in patterns))

    @staticmethod
    def _lebanon_scope_text_filter(text_expr) -> object:
        patterns = (
            "%lebanon%",
            "%lebanese%",
            "%لبنان%",
            "%لبناني%",
        )
        return or_(*(text_expr.ilike(pattern) for pattern in patterns))

    @classmethod
    def _visible_incident_scope_filter(cls) -> object:
        text_expr = func.coalesce(Incident.khabar, RawMessage.raw_text, "")
        ordinary_burning_properties = and_(
            Condition.action_en == "Burning Properties",
            ~cls._war_context_text_filter(text_expr),
        )
        palestine_only = and_(
            cls._palestine_scope_text_filter(text_expr),
            ~cls._lebanon_scope_text_filter(text_expr),
        )
        return ~or_(ordinary_burning_properties, palestine_only)

    def list_all(self, params: IncidentListParams) -> IncidentListResponse:
        needs_verification = self._needs_verification_column()
        event_datetime = func.coalesce(
            RawMessage.message_datetime,
            RawMessage.received_at,
        )
        event_date = func.coalesce(
            Incident.event_date,
            func.date(event_datetime),
        )
        created_at = func.coalesce(Incident.created_at, RawMessage.received_at)
        filters = self._list_filters(
            params,
            event_date_expr=event_date,
        )
        cursor = self._decode_list_cursor(params.cursor)

        selected_columns = (
            Incident.id.label("id"),
            RawMessage.id.label("raw_message_id"),
            RawMessage.status.label("raw_status"),
            func.coalesce(
                Village.ref_name_en,
                Village.cad_name,
            ).label("village"),
            Condition.action_en.label("condition"),
            Condition.action_ar.label("condition_ar"),
            event_date.label("event_date"),
            Incident.event_time,
            func.coalesce(
                Incident.khabar,
                func.left(RawMessage.raw_text, 300),
            ).label("khabar"),
            case(
                (
                    RawMessage.source_platform.is_not(None),
                    func.initcap(RawMessage.source_platform),
                ),
                (RawMessage.external_message_id.ilike("twitter:%"), "Twitter"),
                (RawMessage.external_message_id.ilike("telegram:%"), "Telegram"),
                (RawMessage.external_message_id.ilike("facebook:%"), "Facebook"),
                (Source.type == SourceType.telegram, "Telegram"),
                (Source.type == SourceType.api, "API"),
                (Source.type == SourceType.manual, "Manual"),
                (Source.type == SourceType.twitter, "Twitter"),
                (Source.type == SourceType.facebook, "Facebook"),
                (Source.type == SourceType.website, "Website"),
                else_=None,
            ).label("source"),
            self._source_reference_expression().label("source_reference"),
            func.coalesce(RawMessage.source_name, SummaryBulletin.channel).label("source_name"),
            Incident.total_deaths,
            Incident.total_injuries,
            case(
                (needs_verification, False),
                else_=True,
            ).label("matched"),
            case(
                (needs_verification, "needs_verification"),
                (
                    Incident.verification_status == "needs_verification",
                    "auto_processed",
                ),
                else_=func.coalesce(Incident.verification_status, "auto_processed"),
            ).label("verification_status"),
            case(
                (needs_verification, Incident.verification_reason),
                else_=Incident.verification_reason,
            ).label("verification_reason"),
            Incident.verified_by_user_id,
            Incident.verified_at,
            case(
                (Incident.duplicate_flag.is_(True), "possible"),
                else_="none",
            ).label("duplicate_flag"),
            Incident.duplicate_level,
            Incident.duplicate_similarity_score,
            Incident.details_pending,
            created_at.label("created_at"),
            func.coalesce(Incident.version, 1).label("version"),
            Incident.locked_by_user_id,
            Incident.edit_lock_expires_at,
            Incident.village_id,
            Incident.story_group_id,
            Incident.quality_flags,
            RawMessage.match_result,
            cast(Incident.origin, String).label("origin"),
            Incident.source_summary_item_id,
            SummaryItem.summary_id.label("summary_id"),
            SummaryBulletin.channel.label("summary_channel"),
            SummaryBulletin.window_end.label("summary_window_end"),
        )
        base_query = (
            select(*selected_columns)
            .select_from(Incident)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .outerjoin(SummaryItem, SummaryItem.id == Incident.source_summary_item_id)
            .outerjoin(SummaryBulletin, SummaryBulletin.id == SummaryItem.summary_id)
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == func.coalesce(Incident.source_id, RawMessage.source_id))
            .where(*filters)
        )
        if cursor is not None:
            base_query = base_query.where(
                self._list_cursor_filter(
                    params,
                    cursor,
                    created_at,
                    event_date,
                )
            )

        rows = self.db.execute(
            base_query.order_by(
                *self._list_ordering(params),
            ).limit(params.limit + 1)
        ).all()
        has_next_page = len(rows) > params.limit
        page_rows = rows[: params.limit]
        flags_by_incident = self._visible_flags_by_incident(
            [row.id for row in page_rows if row.id is not None]
        )
        def joined_query(query):
            return (
                query.select_from(Incident)
                .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
                .outerjoin(Village, Village.id == Incident.village_id)
                .outerjoin(Condition, Condition.id == Incident.condition_id)
                .outerjoin(Source, Source.id == func.coalesce(Incident.source_id, RawMessage.source_id))
                .where(*filters)
            )

        total = self.db.scalar(joined_query(select(func.count(Incident.id))))
        latest_incident_at = self.db.scalar(
            joined_query(
                select(
                    func.max(
                        func.greatest(
                            created_at,
                            func.coalesce(Incident.updated_at, RawMessage.received_at),
                        )
                    )
                )
            )
        )
        summary = self.db.execute(
            joined_query(
                select(
                    func.count(Incident.id)
                    .filter(self._needs_verification_column())
                    .label("needs_verification_count"),
                    func.count(Incident.id)
                    .filter(
                        or_(
                            func.coalesce(Incident.total_deaths, 0) > 0,
                            func.coalesce(Incident.total_injuries, 0) > 0,
                        )
                    )
                    .label("casualties_count"),
                )
            )
        ).one()
        outside_range_filters = self._outside_range_needs_verification_filters(params)
        outside_range_count = (
            self.db.scalar(
                select(func.count(Incident.id))
                .select_from(Incident)
                .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
                .outerjoin(Village, Village.id == Incident.village_id)
                .outerjoin(Condition, Condition.id == Incident.condition_id)
                .outerjoin(Source, Source.id == Incident.source_id)
                .where(*outside_range_filters)
            )
            if outside_range_filters is not None
            else 0
        )

        items = [
                IncidentListItemDTO.model_validate(
                    {
                        **row._mapping,
                        **self._verification_payload(
                            row.id, row.duplicate_flag == "possible",
                            row.verification_reason, flags_by_incident,
                        ),
                        "khabar": strip_emoji_and_pictographs(
                            row._mapping["khabar"]
                        ).strip(),
                        **self._list_village_match_payload(row._mapping),
                        "quality_flags": extract_quality_flags(row.quality_flags),
                    }
                )
                for row in page_rows
            ]
        bulletin_count = 0
        if params.verification_status == "needs_verification" or params.verification_type is not None:
            bulletin_count = int(
                self.db.scalar(
                    joined_query(select(func.count(func.distinct(Incident.raw_message_id))))
                    .where(Incident.raw_message_id.is_not(None))
                )
                or 0
            )
        return IncidentListResponse(
            items=items,
            total=int(total or 0),
            limit=params.limit,
            next_cursor=(
                self._encode_list_cursor(page_rows[-1]._mapping)
                if has_next_page and page_rows
                else None
            ),
            latest_incident_at=latest_incident_at,
            needs_verification_count=int(summary.needs_verification_count or 0),
            casualties_count=int(summary.casualties_count or 0),
            needs_verification_outside_range_count=int(outside_range_count or 0),
            needs_verification_bulletin_count=bulletin_count,
            grouped_items=(
                self._group_list_items_by_raw_message(items)
                if params.group_by == "raw_message"
                else []
            ),
        )

    @staticmethod
    def _group_list_items_by_raw_message(
        items: list[IncidentListItemDTO],
    ) -> list[IncidentBulletinGroupDTO]:
        grouped: dict[int, list[IncidentListItemDTO]] = {}
        for item in items:
            if item.raw_message_id is None:
                continue
            grouped.setdefault(item.raw_message_id, []).append(item)
        result: list[IncidentBulletinGroupDTO] = []
        for raw_message_id, incidents in grouped.items():
            first = incidents[0]
            reasons = [
                reason
                for reason in dict.fromkeys(
                    incident.verification_reason
                    for incident in incidents
                    if incident.verification_reason
                )
            ]
            verification_types = [
                item
                for item in dict.fromkeys(
                    verification_type
                    for incident in incidents
                    for verification_type in incident.verification_types
                )
            ]
            result.append(
                IncidentBulletinGroupDTO(
                    raw_message_id=raw_message_id,
                    khabar=first.khabar,
                    source=first.source,
                    source_name=first.source_name,
                    source_reference=first.source_reference,
                    event_date=first.event_date,
                    event_time=first.event_time,
                    verification_reasons=reasons,
                    verification_types=verification_types,
                    incidents=incidents,
                )
            )
        return result

    def get_by_id(self, incident_id: UUID) -> IncidentDetailDTO | None:
        row = self.db.execute(
            select(
                Incident,
                Village,
                func.coalesce(
                    Incident.village_display_name,
                    Village.ref_name_en,
                    Village.cad_name,
                ).label("village"),
                Condition.action_en.label("condition"),
                case(
                    (Source.type == SourceType.telegram, "Telegram"),
                    (Source.type == SourceType.api, "API"),
                    (Source.type == SourceType.manual, "Manual"),
                    (Source.type == SourceType.twitter, "Twitter"),
                    (Source.type == SourceType.facebook, "Facebook"),
                    (Source.type == SourceType.website, "Website"),
                    else_=None,
                ).label("source"),
                self._source_reference_expression().label("source_reference"),
                RawMessage.source_name.label("source_name"),
                RawMessage.raw_payload.label("raw_payload"),
                RawMessage.match_result.label("match_result"),
                case((self._needs_verification_column(), False), else_=True).label(
                    "matched"
                ),
                case(
                    (Incident.duplicate_flag.is_(True), "possible"),
                    else_="none",
                ).label("duplicate_flag"),
                IncidentDetail,
                BulletinCasualtyGroup,
            )
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == Incident.source_id)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .outerjoin(IncidentDetail, IncidentDetail.incident_id == Incident.id)
            .outerjoin(
                BulletinCasualtyGroup,
                BulletinCasualtyGroup.raw_message_id == Incident.raw_message_id,
            )
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.village_id.is_not(None),
                Incident.condition_id.not_in(AIR_VIOLATION_CONDITION_ID_TUPLE),
                self._visible_incident_scope_filter(),
            )
        ).one_or_none()
        if row is None:
            return None

        incident = row.Incident
        flags_by_incident = self._visible_flags_by_incident([incident.id])
        detail = row.IncidentDetail
        bulletin_group = row.BulletinCasualtyGroup
        village = row.Village
        match_result = row.match_result if isinstance(row.match_result, dict) else {}
        village_matches = match_result.get("village_matches")
        if not isinstance(village_matches, list):
            village_matches = [match_result] if match_result else []
        village_match = next(
            (
                entry
                for entry in village_matches
                if isinstance(entry, dict)
                and entry.get("matched_village_id") == incident.village_id
            ),
            {},
        )

        def match_village_id(key: str) -> int | None:
            value = village_match.get(key)
            return (
                value
                if isinstance(value, int) and not isinstance(value, bool)
                else None
            )

        anchor_village_id = match_village_id("geo_context_anchor_village_id")
        alternate_village_id = match_village_id("alternate_candidate_village_id")
        geo_context_distance = village_match.get("geo_context_distance_meters")
        if not isinstance(geo_context_distance, (int, float)):
            geo_context_distance = None
        related_village_ids = {
            value
            for value in (anchor_village_id, alternate_village_id)
            if value is not None
        }
        related_village_names = (
            dict(
                self.db.execute(
                    select(
                        Village.id,
                        func.coalesce(
                            Incident.village_display_name,
                            Village.ref_name_en,
                            Village.cad_name,
                            Village.acs_name,
                        ),
                    ).where(Village.id.in_(related_village_ids))
                ).all()
            )
            if related_village_ids
            else {}
        )
        values = {
            "id": incident.id,
            "village": row.village,
            "village_details": (
                IncidentVillageDetailDTO(
                    id=village.id,
                    acs_code=village.acs_code,
                    acs_name=village.acs_name,
                    cad_name=village.cad_name,
                    ref_name_en=village.ref_name_en,
                    ref_name_ar=village.ref_name_ar,
                    caza_en=village.caza_en,
                    caza_ar=village.caza_ar,
                    mohafaza_en=village.mohafaza_en,
                    mohafaza_ar=village.mohafaza_ar,
                    coord_x=village.coord_x,
                    coord_y=village.coord_y,
                )
                if village is not None
                else None
            ),
            "condition": row.condition,
            "source": row.source,
            "source_reference": row.source_reference,
            "source_name": row.source_name,
            "khabar": strip_emoji_and_pictographs(incident.khabar).strip(),
            "note": self._sanitize_optional_text(incident.note),
            "moh": incident.moh,
            "martyrs": incident.martyrs,
            "worker_name": incident.worker_name,
            "source_link": incident.source_link
            or self._source_link_from_raw_payload(row.raw_payload),
            "source_link_2": incident.source_link_2,
            "total_deaths": incident.total_deaths,
            "total_injuries": incident.total_injuries,
            "deaths": incident.deaths,
            "injuries": incident.injuries,
            "event_date": incident.event_date,
            "event_time": incident.event_time,
            "created_at": incident.created_at,
            "version": incident.version,
            "locked_by_user_id": incident.locked_by_user_id,
            "edit_lock_expires_at": incident.edit_lock_expires_at,
            "matched": row.matched,
            "verification_status": (
                "needs_verification" if flags_by_incident.get(incident.id)
                else incident.verification_status
                if incident.verification_status != "needs_verification"
                or self._is_user_visible_needs_verification(incident)
                else "auto_processed"
            ),
            "verification_reason": (
                self._flag_summary(flags_by_incident[incident.id][0])
                if flags_by_incident.get(incident.id)
                else incident.verification_reason
                if incident.verification_status != "needs_verification"
                or self._is_user_visible_needs_verification(incident)
                else None
            ),
            **self._verification_payload(
                incident.id, bool(incident.duplicate_flag),
                incident.verification_reason, flags_by_incident,
            ),
            "duplicate_flag": row.duplicate_flag,
            "quality_flags": extract_quality_flags(incident.quality_flags),
            "duplicate_level": incident.duplicate_level,
            "duplicate_similarity_score": incident.duplicate_similarity_score,
            "village_review_required": bool(
                village_match.get("village_review_required", False)
            ),
            "any_village_low_confidence": bool(
                match_result.get("any_village_low_confidence", False)
            ),
            "resolved_by_geo_context": bool(
                village_match.get("resolved_by_geo_context", False)
            ),
            "geo_context_anchor_village_id": anchor_village_id,
            "geo_context_anchor_village_name": related_village_names.get(
                anchor_village_id
            ),
            "geo_context_distance_meters": geo_context_distance,
            "normalized_from": village_match.get("normalized_from")
            if isinstance(village_match.get("normalized_from"), str)
            else None,
            "alternate_candidate_village_id": alternate_village_id,
            "alternate_candidate_village_name": related_village_names.get(
                alternate_village_id
            ),
            "casualty_demographics": CasualtyDemographicsDTO(
                male_d=detail.male_d if detail is not None else None,
                male_i=detail.male_i if detail is not None else None,
                female_d=detail.female_d if detail is not None else None,
                female_i=detail.female_i if detail is not None else None,
                children_d=detail.children_d if detail is not None else None,
                children_i=detail.children_i if detail is not None else None,
            ),
            "bulletin_group": bulletin_group,
            "toll_revisions": self._toll_revisions_for(incident.id),
            "related_incidents": self._related_incidents_for(incident),
            "open_casualty_flags_count": len(flags_by_incident.get(incident.id, [])),
            **self._summary_origin_payload(incident),
            **serialize_incident_category_sections(detail),
        }
        return IncidentDetailDTO.model_validate(values)

    def _summary_origin_payload(self, incident: Incident) -> dict[str, Any]:
        """Where the incident came from, plus its summary (channel/date) for display."""
        payload: dict[str, Any] = {
            "origin": getattr(incident.origin, "value", incident.origin) or "live",
            "source_summary_item_id": incident.source_summary_item_id,
        }
        if incident.source_summary_item_id is None:
            return payload
        summary = self.db.execute(
            select(SummaryBulletin.id, SummaryBulletin.channel, SummaryBulletin.window_end)
            .join(SummaryItem, SummaryItem.summary_id == SummaryBulletin.id)
            .where(SummaryItem.id == incident.source_summary_item_id)
        ).one_or_none()
        if summary is not None:
            payload.update(
                summary_id=summary.id,
                summary_channel=summary.channel,
                summary_window_end=summary.window_end,
            )
        return payload

    def _list_village_match_payload(self, row: Mapping[str, Any]) -> dict[str, Any]:
        match_result = row.get("match_result") if isinstance(row, Mapping) else None
        if not isinstance(match_result, dict):
            return {}
        village_matches = match_result.get("village_matches")
        if not isinstance(village_matches, list):
            village_matches = [match_result] if match_result else []
        village_id = row.get("village_id")
        village_match = next(
            (
                entry
                for entry in village_matches
                if isinstance(entry, dict)
                and entry.get("matched_village_id") == village_id
            ),
            {},
        )
        anchor_id = village_match.get("geo_context_anchor_village_id")
        anchor_name = None
        if isinstance(anchor_id, int) and not isinstance(anchor_id, bool):
            anchor_name = self.db.scalar(
                select(func.coalesce(Village.ref_name_en, Village.cad_name))
                .where(Village.id == anchor_id)
                .limit(1)
            )
        distance = village_match.get("geo_context_distance_meters")
        return {
            "resolved_by_geo_context": bool(
                village_match.get("resolved_by_geo_context", False)
            ),
            "geo_context_anchor_village_name": anchor_name,
            "geo_context_distance_meters": distance
            if isinstance(distance, (int, float))
            else None,
            "normalized_from": village_match.get("normalized_from")
            if isinstance(village_match.get("normalized_from"), str)
            else None,
        }

    def _toll_revisions_for(self, incident_id: UUID) -> list[TollRevisionDTO]:
        updates = self.db.scalars(
            select(IncidentUpdate)
            .where(
                IncidentUpdate.incident_id == incident_id,
                IncidentUpdate.action == UpdateAction.pipeline_merge,
            )
            .order_by(IncidentUpdate.created_at.asc())
        ).all()
        revisions: list[TollRevisionDTO] = []
        for update in updates:
            new_values = update.new_values or {}
            if not new_values.get("story_revision"):
                continue
            old_values = update.old_values or {}
            old_deaths = _optional_count(
                old_values.get("total_deaths"), old_values.get("deaths")
            )
            old_injuries = _optional_count(
                old_values.get("total_injuries"), old_values.get("injuries")
            )
            new_deaths = _optional_count(
                new_values.get("total_deaths"), new_values.get("deaths")
            )
            new_injuries = _optional_count(
                new_values.get("total_injuries"), new_values.get("injuries")
            )
            if (old_deaths, old_injuries) == (new_deaths, new_injuries):
                continue
            merged_from_value = new_values.get("merged_from")
            merged_from = (
                merged_from_value if isinstance(merged_from_value, dict) else {}
            )
            revisions.append(
                TollRevisionDTO(
                    updated_at=update.created_at,
                    old_deaths=old_deaths,
                    old_injuries=old_injuries,
                    new_deaths=new_deaths,
                    new_injuries=new_injuries,
                    source_raw_message_id=merged_from.get("raw_message_id"),
                    source_channel=merged_from.get("channel"),
                    source_khabar=merged_from.get("khabar"),
                )
            )
        return revisions

    def _related_incidents_for(self, incident: Incident) -> list[RelatedIncidentDTO]:
        clauses: list[Any] = []
        if incident.story_group_id is not None:
            clauses.append(Incident.story_group_id == incident.story_group_id)
        if incident.raw_message_id is not None:
            clauses.append(Incident.raw_message_id == incident.raw_message_id)
        if not clauses:
            return []
        rows = self.db.execute(
            select(
                Incident,
                Condition.action_en.label("condition"),
                func.coalesce(
                    Incident.village_display_name,
                    Village.ref_name_en,
                    Village.cad_name,
                ).label("village"),
            )
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Village, Village.id == Incident.village_id)
            .where(
                Incident.id != incident.id,
                Incident.is_deleted.is_(False),
                or_(*clauses),
            )
            .order_by(Incident.event_time.asc(), Incident.created_at.asc())
        ).all()
        related: list[RelatedIncidentDTO] = []
        seen: set[UUID] = set()
        for row in rows:
            sibling: Incident = row.Incident
            if sibling.id in seen:
                continue
            seen.add(sibling.id)
            same_bulletin = (
                incident.raw_message_id is not None
                and sibling.raw_message_id == incident.raw_message_id
            )
            same_village = (
                incident.village_id is not None
                and sibling.village_id == incident.village_id
            )
            relation = (
                "same_bulletin_other_village"
                if same_bulletin and not same_village
                else "same_location_sub_event"
            )
            related.append(
                RelatedIncidentDTO(
                    id=sibling.id,
                    village=row.village,
                    condition=row.condition,
                    raw_message_id=sibling.raw_message_id,
                    relation=relation,
                    total_deaths=sibling.total_deaths,
                    total_injuries=sibling.total_injuries,
                )
            )
        return related

    def create_manual(
        self, payload: IncidentCreateDTO, created_by: UUID
    ) -> IncidentDetailDTO:
        village_name = payload.village.strip()
        condition_name = payload.condition.strip()
        sanitized_khabar = strip_emoji_and_pictographs(payload.khabar).strip()
        sanitized_note = self._sanitize_optional_text(payload.note)
        sanitized_source_link = self._sanitize_optional_text(payload.source_link)
        village = self.db.scalar(
            select(Village).where(
                Village.is_active.is_(True),
                or_(
                    func.lower(Village.ref_name_en) == village_name.lower(),
                    func.lower(Village.cad_name) == village_name.lower(),
                    func.lower(Village.ref_name_ar) == village_name.lower(),
                ),
            )
        )
        if village is None:
            raise ValueError("Village was not found. Enter an existing village name.")
        condition = self.db.scalar(
            select(Condition).where(
                Condition.is_active.is_(True),
                or_(
                    func.lower(Condition.action_en) == condition_name.lower(),
                    func.lower(Condition.action_ar) == condition_name.lower(),
                ),
            )
        )
        if condition is None:
            raise ValueError(
                "Condition was not found. Enter an existing condition name."
            )
        source = self._ensure_manual_source()
        incident = Incident(
            village_id=village.id,
            condition_id=condition.id,
            source_id=source.id,
            event_month=payload.event_date.strftime("%B"),
            event_date=payload.event_date,
            event_time=payload.event_time,
            khabar=sanitized_khabar,
            note=sanitized_note,
            source_link=sanitized_source_link,
            created_by=created_by,
        )
        self.db.add(incident)
        self.db.flush()
        record_incident_change(
            self.db,
            incident_id=incident.id,
            action=UpdateAction.create,
            old_values=None,
            new_values={
                "village_id": village.id,
                "condition_id": condition.id,
                "event_date": payload.event_date,
                "event_time": payload.event_time,
                "khabar": sanitized_khabar,
                "note": sanitized_note,
                "source_link": sanitized_source_link,
            },
            performed_by=created_by,
        )
        self.db.commit()
        detail = self.get_by_id(incident.id)
        if detail is None:
            raise RuntimeError("Created incident could not be loaded.")
        return detail

    def update(
        self, incident_id: UUID, payload: IncidentUpdateDTO, user_id: UUID
    ) -> IncidentDetailDTO | None:
        incident = self.db.scalar(
            select(Incident)
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == payload.version,
                Incident.locked_by_user_id == user_id,
            )
            .with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if (
                self.db.scalar(
                    select(Incident.id).where(
                        Incident.id == incident_id, Incident.is_deleted.is_(False)
                    )
                )
                is None
            ):
                return None
            raise StaleDataError("Incident version or edit lock is stale.")
        text_fields = {
            "khabar",
            "note",
            "worker_name",
            "source_link",
            "source_link_2",
        }
        # Partial update: only fields the client sent are touched. The UI never
        # sends source_link_2, and a full dump used to null it on every save.
        submitted = payload.model_dump(exclude={"version"}, exclude_unset=True)
        before = {field: getattr(incident, field) for field in submitted}
        for field, value in submitted.items():
            if field in text_fields:
                value = self._sanitize_optional_text(value)
                if field == "khabar" and value is None:
                    value = ""
            setattr(incident, field, value)
        if "event_date" in submitted:
            incident.event_month = payload.event_date.strftime("%B")
        old_values, new_values = changed_fields(
            before,
            {field: getattr(incident, field) for field in submitted},
        )
        if new_values:
            record_incident_change(
                self.db,
                incident_id=incident.id,
                action=UpdateAction.edit,
                old_values=old_values,
                new_values=new_values,
                performed_by=user_id,
            )
        incident.locked_by_user_id = None
        incident.edit_lock_expires_at = None
        if any(field in submitted for field in ("deaths", "injuries", "total_deaths", "total_injuries")):
            evaluate_casualty_flags_safely(self.db, incident.id)
        self.db.commit()
        return self.get_by_id(incident_id)

    def update_details(
        self,
        incident_id: UUID,
        fields: dict[str, Any],
        performed_by: UUID,
        version: int,
    ) -> IncidentDetailDTO | None:
        incident = self.db.scalar(
            select(Incident)
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == version,
                Incident.locked_by_user_id == performed_by,
            )
            .with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if (
                self.db.scalar(
                    select(Incident.id).where(
                        Incident.id == incident_id, Incident.is_deleted.is_(False)
                    )
                )
                is None
            ):
                return None
            raise StaleDataError("Incident version or edit lock is stale.")

        detail = self.db.scalar(
            select(IncidentDetail).where(IncidentDetail.incident_id == incident_id)
        )
        if detail is None:
            detail = IncidentDetail(incident_id=incident_id)
            self.db.add(detail)
            self.db.flush()

        try:
            old_values, new_values = apply_incident_detail_edits(
                incident,
                detail,
                fields,
            )
        except IncidentDetailEditError as exc:
            raise ValueError(str(exc)) from exc

        if old_values != new_values:
            self.db.add(
                IncidentUpdate(
                    incident_id=incident.id,
                    action=UpdateAction.edit,
                    old_values=old_values,
                    new_values=new_values,
                    performed_by=performed_by,
                )
            )

        self.db.add(detail)
        self.db.add(incident)
        incident.locked_by_user_id = None
        incident.edit_lock_expires_at = None
        if any(field in fields for field in ("deaths", "injuries", "total_deaths", "total_injuries")):
            evaluate_casualty_flags_safely(self.db, incident.id)
        self.db.commit()
        return self.get_by_id(incident_id)

    def delete(self, incident_id: UUID, version: int, user_id: UUID) -> bool:
        incident = self.db.scalar(
            select(Incident)
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == version,
                Incident.locked_by_user_id == user_id,
            )
            .with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if (
                self.db.scalar(
                    select(Incident.id).where(
                        Incident.id == incident_id, Incident.is_deleted.is_(False)
                    )
                )
                is None
            ):
                return False
            raise StaleDataError("Incident version or edit lock is stale.")
        soft_delete_incident(self.db, incident, reason=DeletedReason.admin.value, performed_by=user_id)
        evaluate_casualty_flags_safely(self.db, incident.id)
        self.db.commit()
        return True

    def acquire_edit_lock(
        self, incident_id: UUID, user_id: UUID
    ) -> IncidentDetailDTO | None:
        now = datetime.now(timezone.utc)
        result = self.db.execute(
            sa_update(Incident)
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                (
                    Incident.locked_by_user_id.is_(None)
                    | (Incident.edit_lock_expires_at <= now)
                    | (Incident.locked_by_user_id == user_id)
                ),
            )
            .values(
                locked_by_user_id=user_id,
                edit_lock_expires_at=now + timedelta(minutes=5),
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if (
                self.db.scalar(
                    select(Incident.id).where(
                        Incident.id == incident_id, Incident.is_deleted.is_(False)
                    )
                )
                is None
            ):
                return None
            raise StaleDataError("Incident is being edited by another administrator.")
        self.db.commit()
        return self.get_by_id(incident_id)

    def set_verification(
        self,
        incident_id: UUID,
        status: str,
        reason: str | None,
        version: int,
        user_id: UUID,
    ) -> IncidentDetailDTO | None:
        incident = self.db.scalar(
            select(Incident)
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == version,
            )
            .with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if (
                self.db.scalar(
                    select(Incident.id).where(
                        Incident.id == incident_id, Incident.is_deleted.is_(False)
                    )
                )
                is None
            ):
                return None
            raise StaleDataError("Incident verification version is stale.")
        old_values = {
            "verification_status": incident.verification_status,
            "verification_reason": incident.verification_reason,
            "verified_by_user_id": str(incident.verified_by_user_id)
            if incident.verified_by_user_id
            else None,
        }
        incident.verification_status = status
        incident.verification_reason = reason
        incident.verified_by_user_id = user_id
        incident.verified_at = datetime.now(timezone.utc)
        if status == "rejected" and incident.raw_message_id is not None:
            raw_message = self.db.scalar(
                select(RawMessage)
                .where(RawMessage.id == incident.raw_message_id)
                .with_for_update()
            )
            # Reject is per incident: the raw message (and so the Rejected News
            # page) only flips once none of its village incidents is still live.
            if raw_message is not None and not self._has_other_live_incident(
                incident.raw_message_id,
                exclude_incident_id=incident.id,
            ):
                filter_result = dict(raw_message.filter_result or {})
                filter_result.update(
                    {
                        "verdict": "reject",
                        "reasoning": reason,
                        "review_source": "human",
                        "reviewed_by_user_id": str(user_id),
                    }
                )
                raw_message.filter_result = filter_result
                raw_message.status = MessageStatus.rejected
                raw_message.error_message = reason
        self.db.add(
            IncidentUpdate(
                incident_id=incident.id,
                action=UpdateAction.status_change,
                old_values=old_values,
                new_values={
                    "verification_status": status,
                    "verification_reason": reason,
                    "verified_by_user_id": str(user_id),
                },
                performed_by=user_id,
            )
        )
        evaluate_casualty_flags_safely(self.db, incident.id)
        self.db.commit()
        return self.get_by_id(incident_id)

    def get_pending_duplicate_candidate(
        self, incident_id: UUID
    ) -> IncidentDuplicateCandidateDTO | None:
        match = self.db.scalar(
            select(DuplicateMatch)
            .where(
                DuplicateMatch.incident_id == incident_id,
                DuplicateMatch.status == MatchStatus.pending,
                DuplicateMatch.matched_incident_id.is_not(None),
            )
            .order_by(DuplicateMatch.similarity_score.desc().nullslast())
        )
        if match is None or match.matched_incident_id is None:
            return None
        candidate = self.get_by_id(match.matched_incident_id)
        if candidate is None:
            return None
        return IncidentDuplicateCandidateDTO(
            match_id=match.id,
            similarity_score=float(match.similarity_score or 0.0),
            candidate=DuplicateCandidateIncidentDTO(
                id=candidate.id,
                village=candidate.village,
                condition=candidate.condition,
                event_date=candidate.event_date,
                event_time=candidate.event_time,
                khabar=candidate.khabar,
                source=candidate.source,
                source_reference=candidate.source_reference,
                source_name=candidate.source_name,
                total_deaths=candidate.total_deaths,
                total_injuries=candidate.total_injuries,
            ),
        )

    def resolve_duplicate(
        self,
        incident_id: UUID,
        match_id: int,
        decision: str,
        version: int,
        user_id: UUID,
    ) -> IncidentDuplicateResolutionResultDTO | None:
        incident = self.db.scalar(
            select(Incident)
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == version,
                Incident.locked_by_user_id == user_id,
            )
            .with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if (
                self.db.scalar(
                    select(Incident.id).where(
                        Incident.id == incident_id, Incident.is_deleted.is_(False)
                    )
                )
                is None
            ):
                return None
            raise StaleDataError("Incident version or edit lock is stale.")

        match = self.db.scalar(
            select(DuplicateMatch)
            .where(
                DuplicateMatch.id == match_id,
                DuplicateMatch.incident_id == incident_id,
                DuplicateMatch.status == MatchStatus.pending,
                DuplicateMatch.matched_incident_id.is_not(None),
            )
            .with_for_update()
        )
        if match is None or match.matched_incident_id is None:
            self.db.rollback()
            raise StaleDataError("Duplicate match is missing or already resolved.")

        canonical_id = match.matched_incident_id
        if decision == MatchStatus.false_positive.value:
            incident.duplicate_flag = False
            if (
                incident.verification_status == "needs_verification"
                and not self._should_keep_needs_verification_after_duplicate_clear(
                    incident.verification_reason, incident
                )
            ):
                incident.verification_status = "auto_processed"
                incident.verification_reason = None
            match.status = MatchStatus.false_positive
        elif decision == MatchStatus.confirmed_duplicate.value:
            canonical = self.db.scalar(
                select(Incident)
                .where(
                    Incident.id == canonical_id,
                    Incident.is_deleted.is_(False),
                )
                .with_for_update()
            )
            if canonical is None:
                self.db.rollback()
                raise StaleDataError(
                    "The suggested main incident is no longer available."
                )
            if incident.duplicate_level == "segment":
                incident_datetime = datetime.combine(
                    incident.event_date, incident.event_time or time(0, 0)
                )
                canonical_datetime = datetime.combine(
                    canonical.event_date, canonical.event_time or time(0, 0)
                )
                canonical_is_earlier = canonical_datetime < incident_datetime
                if canonical_datetime == incident_datetime:
                    canonical_is_earlier = bool(
                        canonical.raw_message_id is not None
                        and incident.raw_message_id is not None
                        and canonical.raw_message_id < incident.raw_message_id
                    )
                if not canonical_is_earlier:
                    self.db.rollback()
                    raise ValueError(
                        "A segment-review duplicate can only be confirmed against "
                        "an earlier main incident."
                    )
            if incident.village_id != canonical.village_id:
                self.db.rollback()
                raise ValueError(
                    "Incidents from different villages cannot be confirmed as duplicates."
                )
            if incident.condition_id != canonical.condition_id:
                self.db.rollback()
                raise ValueError(
                    "Incidents with different conditions cannot be confirmed as duplicates."
                )

            old_values = self._snapshot_merge_fields(canonical)
            for field in ("deaths", "injuries", "total_deaths", "total_injuries"):
                setattr(
                    canonical,
                    field,
                    self._max_preserving_empty(
                        getattr(canonical, field), getattr(incident, field)
                    ),
                )
            if incident.casualty_status is not None:
                duplicate_raw_message = (
                    self.db.get(RawMessage, incident.raw_message_id)
                    if incident.raw_message_id is not None
                    else None
                )
                self._merge_casualty_status_fields(
                    canonical,
                    {
                        "casualty_status": incident.casualty_status,
                        "casualty_deaths_status": getattr(incident, "casualty_deaths_status", None),
                        "casualty_injuries_status": getattr(incident, "casualty_injuries_status", None),
                        "casualty_status_remaining_total": getattr(
                            incident, "casualty_status_remaining_total", None
                        ),
                        "casualty_is_preliminary": incident.casualty_is_preliminary,
                        "casualty_status_evidence": incident.casualty_status_evidence,
                    },
                    incoming_is_newest=self._revision_is_newer(
                        canonical, duplicate_raw_message
                    ),
                )
            if canonical.source_link is None:
                canonical.source_link = incident.source_link
            if canonical.source_link_2 is None:
                canonical.source_link_2 = incident.source_link_2 or incident.source_link

            duplicate_detail = self.db.scalar(
                select(IncidentDetail).where(IncidentDetail.incident_id == incident.id)
            )
            if duplicate_detail is not None:
                canonical_detail = self.db.scalar(
                    select(IncidentDetail).where(
                        IncidentDetail.incident_id == canonical.id
                    )
                )
                if canonical_detail is None:
                    canonical_detail = IncidentDetail(incident_id=canonical.id)
                    self.db.add(canonical_detail)
                    self.db.flush()
                excluded = {"id", "incident_id", "created_at", "updated_at"}
                merge_incident_detail_fields(
                    canonical_detail,
                    {
                        column.name: getattr(duplicate_detail, column.name)
                        for column in IncidentDetail.__table__.columns
                        if column.name not in excluded
                    },
                )

            new_values = self._snapshot_merge_fields(canonical)
            new_values["merged_from"] = {
                "raw_message_id": incident.raw_message_id,
                "channel": None,
                "khabar": incident.khabar,
            }
            self.db.add(
                IncidentUpdate(
                    incident_id=canonical.id,
                    action=UpdateAction.pipeline_merge,
                    old_values=old_values,
                    new_values=new_values,
                    performed_by=user_id,
                )
            )
            soft_delete_incident(self.db, incident, reason="DUPLICATE_MERGE", canonical_incident_id=canonical.id, performed_by=user_id)
            evaluate_casualty_flags_safely(self.db, incident.id)
            match.status = MatchStatus.confirmed_duplicate
            self.db.flush()
            if (
                incident.raw_message_id is not None
                and canonical.raw_message_id is not None
            ):
                self.mark_raw_duplicate_if_fully_subsumed(
                    raw_message_id=incident.raw_message_id,
                    canonical_raw_message_id=canonical.raw_message_id,
                )
        else:
            self.db.rollback()
            raise ValueError("Unsupported duplicate resolution decision.")

        match.resolved_by = user_id
        incident.locked_by_user_id = None
        incident.edit_lock_expires_at = None
        self.db.add(
            IncidentUpdate(
                incident_id=incident.id,
                action=UpdateAction.status_change,
                old_values={"duplicate_flag": True, "duplicate_status": "pending"},
                new_values={"duplicate_flag": False, "duplicate_status": decision},
                performed_by=user_id,
            )
        )
        evaluate_casualty_flags_safely(self.db, incident_id)
        if decision == MatchStatus.confirmed_duplicate.value:
            evaluate_casualty_flags_safely(self.db, canonical_id)
        self.db.commit()
        return IncidentDuplicateResolutionResultDTO(
            decision=decision,
            incident_id=incident_id,
            canonical_incident_id=canonical_id
            if decision == MatchStatus.confirmed_duplicate.value
            else incident_id,
        )

    def release_edit_lock(self, incident_id: UUID, user_id: UUID) -> bool:
        result = self.db.execute(
            sa_update(Incident)
            .where(Incident.id == incident_id, Incident.locked_by_user_id == user_id)
            .values(locked_by_user_id=None, edit_lock_expires_at=None)
        )
        self.db.commit()
        return result.rowcount > 0

    def list_duplicate_candidates(
        self,
        village_id: int,
        event_date: date,
        khabar_embedding: list[float],
        window_days: int,
        exclude_raw_message_id: int | None = None,
    ) -> list[tuple[Incident, float]]:
        start_date = event_date - timedelta(days=window_days)
        end_date = event_date + timedelta(days=window_days)
        embedding_similarity = (
            1.0 - Incident.khabar_embedding.cosine_distance(khabar_embedding)
        ).label("embedding_similarity")
        filters = [
            Incident.village_id == village_id,
            Incident.is_deleted.is_(False),
            Incident.event_date >= start_date,
            # Admin-rejected incidents never absorb new reports automatically.
            Incident.verification_status.is_distinct_from("rejected"),
            Incident.event_date <= end_date,
            Incident.khabar_embedding.is_not(None),
        ]
        if exclude_raw_message_id is not None:
            filters.append(Incident.raw_message_id != exclude_raw_message_id)

        rows = self.db.execute(
            select(Incident, embedding_similarity)
            .where(and_(*filters))
            .order_by(desc(embedding_similarity))
        ).all()

        return [
            (incident, float(embedding_score or 0.0))
            for incident, embedding_score in rows
        ]

    def create_with_detail(
        self,
        message: RawMessage,
        candidate: ExtractedCandidate,
        village_id: int,
        condition_id: int,
        khabar_embedding: list[float],
        duplicate_flag: bool = False,
    ) -> Incident:
        event_datetime = message.message_datetime
        if event_datetime is None:
            raise RuntimeError(
                "raw_message.message_datetime is required for incident creation."
            )

        exact_hash = self._build_exact_hash(
            khabar=message.raw_text or "",
            village_id=village_id,
            condition_id=condition_id,
            event_date=event_datetime.date().isoformat(),
        )

        incident = Incident(
            village_id=village_id,
            condition_id=condition_id,
            source_id=message.source_id,
            raw_message_id=message.id,
            event_date=event_datetime.date(),
            event_time=event_datetime.time(),
            khabar=message.raw_text or "",
            khabar_embedding=khabar_embedding,
            deaths=candidate.deaths,
            injuries=candidate.injuries,
            exact_hash=exact_hash,
            duplicate_flag=duplicate_flag,
            created_by=None,
        )
        self.db.add(incident)
        self.db.flush()
        self.db.add(
            IncidentDetail(
                incident_id=incident.id,
                male_d=candidate.male_d,
                male_i=candidate.male_i,
                female_d=candidate.female_d,
                female_i=candidate.female_i,
                children_d=candidate.children_d,
                children_i=candidate.children_i,
            )
        )
        self.db.flush()
        return incident

    def create_duplicate_match(
        self,
        incident: Incident,
        matched_incident: Incident,
        similarity_score: float,
        status: MatchStatus = MatchStatus.pending,
    ) -> None:
        if incident.village_id != matched_incident.village_id:
            raise ValueError("Duplicate matches require the same canonical village.")
        self.db.add(
            DuplicateMatch(
                incident_id=incident.id,
                matched_incident_id=matched_incident.id,
                match_type=MatchType.soft,
                similarity_score=similarity_score,
                status=status,
            )
        )
        self.db.flush()

    def create_fast_path_duplicate_match(
        self,
        *,
        canonical_incident: Incident,
        raw_message_id: int,
        status: MatchStatus = MatchStatus.pending,
        similarity_score: float | None = None,
    ) -> None:
        """Record a fast-path duplicate evaluation against an existing incident."""
        self.db.add(
            DuplicateMatch(
                incident_id=canonical_incident.id,
                matched_incident_id=None,
                raw_message_id=raw_message_id,
                match_type=MatchType.exact,
                similarity_score=similarity_score,
                status=status,
            )
        )
        self.db.flush()

    def redirect_pending_duplicate_matches(
        self,
        *,
        retired_incident: Incident,
        canonical_incident: Incident | None,
    ) -> int:
        """Keep pending review links pointed at an active canonical incident."""
        if canonical_incident is None or canonical_incident.id == retired_incident.id:
            return 0
        result = self.db.execute(
            sa_update(DuplicateMatch)
            .where(
                DuplicateMatch.matched_incident_id == retired_incident.id,
                DuplicateMatch.status == MatchStatus.pending,
            )
            .values(matched_incident_id=canonical_incident.id)
        )
        return int(result.rowcount or 0)

    def merge_existing(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        raw_message = self.db.get(RawMessage, raw_message_id)
        guard = self._casualty_merge_guard(existing, raw_message, new_candidate_data)
        source_label = self._merge_source_label(raw_message)
        detail = self.db.scalar(
            select(IncidentDetail).where(IncidentDetail.incident_id == existing.id)
        )
        old_values = self._snapshot_merge_audit(existing, detail)
        if new_candidate_data.get("casualty_status") is not None and not guard.suppress:
            self._merge_casualty_status_fields(
                existing,
                new_candidate_data,
                incoming_is_newest=self._revision_is_newer(existing, raw_message),
            )
        source_text = (
            getattr(raw_message, "raw_text", None)
            if raw_message is not None
            else new_candidate_data.get("khabar")
        )
        parsed_transitions = parse_casualty_transitions(
            new_candidate_data.get("casualty_transitions")
        )
        backstop = detect_casualty_transition_backstop(source_text)
        transition_already_applied = False
        if parsed_transitions:
            transition_already_applied = (
                self.db.scalar(
                    select(IncidentUpdate.id).where(
                        IncidentUpdate.incident_id == existing.id,
                        IncidentUpdate.action == UpdateAction.pipeline_merge,
                        IncidentUpdate.new_values["merged_from"][
                            "raw_message_id"
                        ].astext
                        == str(raw_message_id),
                        IncidentUpdate.new_values.has_key(  # type: ignore[attr-defined]
                            "deaths_transitioned_from_injuries"
                        ),
                    )
                )
                is not None
            )
        if source_text and not backstop.plausible:
            # The model can confuse separate casualty groups (for example,
            # "a martyr and two injured") with an injured-to-deceased update.
            # Never mutate stored totals without explicit transition wording.
            parsed_transitions = []
        elif transition_already_applied:
            # A raw message can reach the same canonical incident through more
            # than one village match. Its transition must remain idempotent.
            parsed_transitions = []

        transition_fields, transition_provenance, needs_review = (
            apply_casualty_transitions(
                existing,
                parsed_transitions,
            )
        )
        if backstop.plausible and not parsed_transitions:
            needs_review = True
            transition_provenance["possible_missed_casualty_transition"] = {
                "matched_keywords": list(backstop.matched_keywords),
                "note": (
                    "possible casualty transition detected in text but not "
                    "extracted - needs verification"
                ),
            }
        if transition_provenance:
            for key in list(transition_provenance.keys()):
                transition_provenance[key] = {
                    **transition_provenance[key],
                    "raw_message_id": raw_message_id,
                    "channel": source_label,
                }
        if needs_review:
            existing.duplicate_flag = True
            existing.verification_status = "needs_verification"
            existing.verification_reason = (
                "Possible duplicate — casualty count conflict detected during merge"
                + (
                    f". Matched terms: {', '.join(backstop.matched_keywords)}."
                    if backstop.plausible
                    else "."
                )
            )
        else:
            # A successful automatic merge resolves its duplicate decision.
            # Keep the flag only for an explicit casualty-transition conflict.
            existing.duplicate_flag = False
            if (
                existing.verification_status == "needs_verification"
                and not self._should_keep_needs_verification_after_duplicate_clear(
                    existing.verification_reason, existing
                )
            ):
                existing.verification_status = "auto_processed"
                existing.verification_reason = None
            self._demote_verified_after_pipeline_write(
                existing,
                f"Pipeline merged raw message {raw_message_id} into this verified incident",
            )
        sync_transition_totals(existing, transition_fields)

        suppressed: dict[str, Any] = {}
        admin_edited_fields = self._admin_edited_casualty_fields(existing.id)
        for field, incoming_key in (
            ("deaths", "deaths"),
            ("injuries", "injuries"),
            ("total_deaths", "total_deaths"),
            ("total_injuries", "total_injuries"),
        ):
            if field in transition_fields:
                continue
            if field in admin_edited_fields:
                suppressed[f"{field}_suppressed"] = {"reason": "admin_edited", "raw_message_id": raw_message_id}
                continue
            if guard.suppress:
                incoming_value = new_candidate_data.get(incoming_key)
                if incoming_value is not None:
                    suppressed[f"{field}_suppressed"] = {
                        "value": incoming_value,
                        "raw_message_id": raw_message_id,
                        "channel": source_label,
                        "reason": guard.reason,
                    }
                continue
            incoming_value = new_candidate_data.get(incoming_key)
            if field.startswith("total_") and incoming_value is None:
                fallback_key = "deaths" if field == "total_deaths" else "injuries"
                incoming_value = new_candidate_data.get(fallback_key)
            current_value = getattr(existing, field)
            merged_value = self._max_preserving_empty(current_value, incoming_value)
            if isinstance(incoming_value, int) and merged_value != incoming_value:
                suppressed[f"{field}_suppressed"] = {
                    "value": incoming_value,
                    "raw_message_id": raw_message_id,
                    "channel": source_label,
                }
            setattr(existing, field, merged_value)

        mapped_fields = new_candidate_data.get("mapped_fields") or {}
        if mapped_fields:
            if detail is None:
                detail = IncidentDetail(incident_id=existing.id)
                self.db.add(detail)
                self.db.flush()
            if self._merge_introduces_new_presence_categories(detail, mapped_fields):
                existing.details_pending = True
            merge_incident_detail_fields(detail, mapped_fields)
            self.db.add(detail)

        origin_note = self._origin_village_note(
            new_candidate_data.get("origin_villages")
        )
        if origin_note:
            existing.note = self._append_unique_note(existing.note, origin_note)

        khabar = new_candidate_data.get("khabar")

        new_values = self._snapshot_merge_audit(existing, detail)
        if transition_provenance:
            new_values = {**new_values, **transition_provenance}
        if suppressed:
            new_values = {**new_values, **suppressed}
        new_values = {
            **new_values,
            "merged_from": {
                "raw_message_id": raw_message_id,
                "channel": source_label,
                "khabar": khabar if isinstance(khabar, str) else None,
            },
        }
        if old_values != new_values:
            self.db.add(
                IncidentUpdate(
                    incident_id=existing.id,
                    action=UpdateAction.pipeline_merge,
                    old_values=old_values,
                    new_values=new_values,
                    performed_by=None,
                )
            )
        self.db.add(existing)
        evaluate_casualty_flags_safely(self.db, existing.id)

    def apply_story_revision(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
        *,
        heuristic_only: bool = False,
    ) -> bool:
        """Update casualty fields supplied by a later report of the same event.

        Unmentioned fields are left unchanged. The same source message cannot
        apply its revision twice (mirrors transition-merge idempotency).

        Returns False (nothing written) when the report is not newer than the
        incident's data, or when a heuristic-only revision would lower a count;
        the latter flags the incident for review instead.
        """
        if self._story_revision_already_applied(existing.id, raw_message_id):
            return False

        raw_message = self.db.get(RawMessage, raw_message_id)
        guard = self._casualty_merge_guard(existing, raw_message, new_candidate_data)
        if not self._revision_is_newer(existing, raw_message):
            logger.info(
                "story revision skipped raw_message_id=%s incident_id=%s: "
                "not newer than the incident's data",
                raw_message_id,
                existing.id,
            )
            return False
        lowered = self._revision_lowered_fields(existing, new_candidate_data)
        if heuristic_only and lowered:
            existing.verification_status = "needs_verification"
            existing.verification_reason = (
                f"Unconfirmed story revision from raw message {raw_message_id} "
                f"would lower {', '.join(sorted(lowered))}; review before applying"
            )
            record_incident_change(
                self.db,
                incident_id=existing.id,
                action=UpdateAction.pipeline_merge,
                old_values={field: getattr(existing, field) for field in lowered},
                new_values={
                    "proposed_story_revision": {
                        field: new_candidate_data.get(field) for field in lowered
                    },
                    "story_revision_held_raw_message_id": raw_message_id,
                },
                performed_by=None,
            )
            self.db.add(existing)
            return False
        source_label = self._merge_source_label(raw_message)
        detail = self.db.scalar(
            select(IncidentDetail).where(IncidentDetail.incident_id == existing.id)
        )
        old_values = self._snapshot_merge_audit(existing, detail)

        for field in ("deaths", "injuries", "total_deaths", "total_injuries"):
            if guard.suppress:
                continue
            if field in self._admin_edited_casualty_fields(existing.id):
                continue
            incoming = new_candidate_data.get(field)
            if isinstance(incoming, int) and not isinstance(incoming, bool):
                setattr(existing, field, incoming)
        if new_candidate_data.get("casualty_status") is not None and not guard.suppress:
            self._merge_casualty_status_fields(
                existing, new_candidate_data, incoming_is_newest=True
            )
        self._demote_verified_after_pipeline_write(
            existing,
            f"Story revision from raw message {raw_message_id} changed this verified incident",
        )
        if (
            isinstance(new_candidate_data.get("martyrs"), str)
            and new_candidate_data["martyrs"].strip()
        ):
            existing.martyrs = new_candidate_data["martyrs"].strip()

        mapped_fields = new_candidate_data.get("mapped_fields") or {}
        demographic_updates = {
            key: new_candidate_data[key]
            for key in (
                "male_d",
                "male_i",
                "female_d",
                "female_i",
                "children_d",
                "children_i",
            )
            if new_candidate_data.get(key) is not None
        }
        if mapped_fields or demographic_updates:
            if detail is None:
                detail = IncidentDetail(incident_id=existing.id)
                self.db.add(detail)
                self.db.flush()
            if mapped_fields:
                merge_incident_detail_fields(detail, mapped_fields)
            for key, value in demographic_updates.items():
                setattr(detail, key, value)
            self.db.add(detail)

        new_values = self._snapshot_merge_audit(existing, detail)
        khabar = new_candidate_data.get("khabar")
        new_values = {
            **new_values,
            "story_revision": True,
            "story_relationship": "revision",
            "merged_from": {
                "raw_message_id": raw_message_id,
                "channel": source_label,
                "khabar": khabar if isinstance(khabar, str) else None,
            },
        }
        if guard.suppress:
            new_values["aggregate_casualties_suppressed"] = {
                "reason": guard.reason,
                "raw_message_id": raw_message_id,
            }
        self.db.add(
            IncidentUpdate(
                incident_id=existing.id,
                action=UpdateAction.pipeline_merge,
                old_values=old_values,
                new_values=new_values,
                performed_by=None,
            )
        )
        self.db.add(existing)
        evaluate_casualty_flags_safely(self.db, existing.id)
        return True

    @staticmethod
    def _revision_lowered_fields(
        existing: Incident,
        new_candidate_data: dict[str, Any],
    ) -> set[str]:
        lowered: set[str] = set()
        for field in ("deaths", "injuries", "total_deaths", "total_injuries"):
            incoming = new_candidate_data.get(field)
            current = getattr(existing, field)
            if (
                isinstance(incoming, int)
                and not isinstance(incoming, bool)
                and isinstance(current, int)
                and incoming < current
            ):
                lowered.add(field)
        return lowered

    def _revision_is_newer(
        self,
        existing: Incident,
        raw_message: RawMessage | None,
    ) -> bool:
        """A revision must be later than every report the incident already holds."""
        if raw_message is None:
            return True
        new_at = getattr(raw_message, "message_datetime", None) or getattr(
            raw_message, "received_at", None
        )
        source_ids = [
            int(value)
            for value in self.db.scalars(
                select(
                    IncidentUpdate.new_values["merged_from"]["raw_message_id"].astext
                ).where(
                    IncidentUpdate.incident_id == existing.id,
                    IncidentUpdate.action == UpdateAction.pipeline_merge,
                )
            ).all()
            if value and str(value).isdigit()
        ]
        own_raw_message_id = getattr(existing, "raw_message_id", None)
        if own_raw_message_id is not None:
            source_ids.append(own_raw_message_id)
        if new_at is None or not source_ids:
            return True
        latest = self.db.scalar(
            select(
                func.max(func.coalesce(RawMessage.message_datetime, RawMessage.received_at))
            ).where(RawMessage.id.in_(source_ids))
        )
        return latest is None or new_at > latest

    def _has_other_live_incident(
        self,
        raw_message_id: int,
        *,
        exclude_incident_id: UUID,
    ) -> bool:
        return (
            self.db.scalar(
                select(Incident.id)
                .where(
                    Incident.raw_message_id == raw_message_id,
                    Incident.id != exclude_incident_id,
                    Incident.is_deleted.is_(False),
                    Incident.verification_status.is_distinct_from("rejected"),
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _demote_verified_after_pipeline_write(existing: Incident, reason: str) -> None:
        """A human-verified badge must not sit over machine-altered data."""
        if existing.verification_status != "verified":
            return
        existing.verification_status = "needs_verification"
        existing.verification_reason = reason

    def _story_revision_already_applied(
        self,
        incident_id: UUID,
        raw_message_id: int,
    ) -> bool:
        return (
            self.db.scalar(
                select(IncidentUpdate.id).where(
                    IncidentUpdate.incident_id == incident_id,
                    IncidentUpdate.action == UpdateAction.pipeline_merge,
                    IncidentUpdate.new_values["merged_from"]["raw_message_id"].astext
                    == str(raw_message_id),
                    IncidentUpdate.new_values.has_key(  # type: ignore[attr-defined]
                        "story_revision"
                    ),
                )
            )
            is not None
        )

    def link_story_group(self, left: Incident, right: Incident) -> UUID:
        group_id = left.story_group_id or right.story_group_id or uuid4()
        left.story_group_id = group_id
        right.story_group_id = group_id
        self.db.add(left)
        self.db.add(right)
        return group_id

    def find_active_incident_for_raw_message_village(
        self,
        raw_message_id: int,
        village_id: int,
    ) -> Incident | None:
        return self.db.scalar(
            select(Incident).where(
                Incident.raw_message_id == raw_message_id,
                Incident.village_id == village_id,
                Incident.is_deleted.is_(False),
            )
        )

    def has_active_incidents_for_raw_message(self, raw_message_id: int) -> bool:
        count = self.db.scalar(
            select(func.count(Incident.id)).where(
                Incident.raw_message_id == raw_message_id,
                Incident.is_deleted.is_(False),
            )
        )
        return int(count or 0) > 0

    def find_fast_dedup_candidates(
        self,
        *,
        village_id: int,
        condition_id: int,
        message_datetime: datetime,
        lookup_window_days: int,
        candidate_text: str | None = None,
        candidate_embedding: list[float] | None = None,
        exclude_raw_message_id: int | None = None,
    ) -> list[FastDedupCandidate]:
        """Return active same-village + same-condition incidents inside the outer
        lookup window, each annotated with the time gap and (when the candidate
        supplies text / an embedding) the word_similarity() and cosine
        similarity against this candidate.

        The outer window here is only a coarse pre-filter — the actual
        duplicate / distinct decision is made by DuplicateComparisonService from
        the returned time gap + similarity values.
        """
        naive_dt = message_datetime.replace(tzinfo=None)
        event_date = naive_dt.date()
        start_date = event_date - timedelta(days=lookup_window_days)
        end_date = event_date + timedelta(days=lookup_window_days)

        columns: list[Any] = [Incident]
        want_text = bool(candidate_text and candidate_text.strip())
        want_embedding = candidate_embedding is not None
        if want_text:
            columns.append(
                func.word_similarity(
                    normalize_arabic_sql(Incident.khabar),
                    normalize_arabic_sql(literal(candidate_text)),
                ).label("text_similarity")
            )
        if want_embedding:
            columns.append(
                (
                    1.0 - Incident.khabar_embedding.cosine_distance(candidate_embedding)
                ).label("embedding_similarity")
            )

        filters = [
            Incident.village_id == village_id,
            Incident.condition_id == condition_id,
            Incident.is_deleted.is_(False),
            Incident.verification_status.is_distinct_from("rejected"),
            Incident.event_date >= start_date,
            Incident.event_date <= end_date,
        ]
        if exclude_raw_message_id is not None:
            filters.append(Incident.raw_message_id != exclude_raw_message_id)

        result = self.db.execute(select(*columns).where(*filters))
        if result is None:
            return []
        rows = result.all()

        candidates: list[FastDedupCandidate] = []
        for row in rows:
            incident = row[0]
            idx = 1
            text_similarity: float | None = None
            if want_text:
                text_similarity = float(row[idx] or 0.0)
                idx += 1
            embedding_similarity: float | None = None
            if want_embedding:
                value = row[idx]
                embedding_similarity = None if value is None else float(value)
                idx += 1
            incident_dt = datetime.combine(
                incident.event_date, incident.event_time or time(0, 0)
            )
            gap_seconds = abs((incident_dt - naive_dt).total_seconds())
            candidates.append(
                FastDedupCandidate(
                    incident=incident,
                    time_gap_seconds=gap_seconds,
                    text_similarity=text_similarity,
                    embedding_similarity=embedding_similarity,
                    token_similarity=event_token_similarity(
                        incident.khabar,
                        candidate_text,
                    ),
                )
            )

        candidates.sort(key=lambda c: c.time_gap_seconds)
        return candidates

    def find_segment_review_sources(
        self,
        *,
        village_id: int,
        condition_id: int,
        source_id: int,
        source_name: str | None,
        source_platform: str | None,
        event_datetime: datetime,
        window_days: int,
        max_event_gap_hours: int,
        exclude_raw_message_id: int,
        max_results: int,
    ) -> list[SegmentReviewSource]:
        """Return active, materialized, different-source segment containers."""
        current_datetime = event_datetime
        event_date = current_datetime.date()
        start_date = event_date - timedelta(days=window_days)
        end_date = event_date + timedelta(days=window_days)
        candidate_datetime = RawMessage.message_datetime
        rows = self.db.execute(
            select(
                Incident,
                RawMessage.extraction_result,
                RawMessage.match_result,
                RawMessage.raw_text,
                RawMessage.message_datetime,
            )
            .join(RawMessage, RawMessage.id == Incident.raw_message_id)
            .where(
                Incident.village_id == village_id,
                Incident.condition_id == condition_id,
                Incident.source_id.is_not(None),
                or_(
                    Incident.source_id != source_id,
                    func.coalesce(RawMessage.source_name, "") != (source_name or ""),
                    func.coalesce(RawMessage.source_platform, "")
                    != (source_platform or ""),
                ),
                Incident.raw_message_id != exclude_raw_message_id,
                Incident.is_deleted.is_(False),
                Incident.event_date >= start_date,
                Incident.event_date <= end_date,
                candidate_datetime
                >= current_datetime - timedelta(hours=max_event_gap_hours),
                or_(
                    candidate_datetime < current_datetime,
                    and_(
                        candidate_datetime == current_datetime,
                        Incident.raw_message_id < exclude_raw_message_id,
                    ),
                ),
                RawMessage.status.in_(
                    [MessageStatus.materialized, MessageStatus.duplicate]
                ),
                RawMessage.extraction_result.is_not(None),
                RawMessage.match_result.is_not(None),
                RawMessage.message_datetime.is_not(None),
            )
            .order_by(candidate_datetime.desc(), Incident.raw_message_id.desc())
            .limit(max_results)
        ).all()
        return [
            SegmentReviewSource(
                incident=row[0],
                extraction_result=row[1] if isinstance(row[1], dict) else {},
                match_result=row[2] if isinstance(row[2], dict) else {},
                raw_text=row[3] if isinstance(row[3], str) else None,
                message_datetime=row[4],
            )
            for row in rows
        ]

    def segment_text_similarity(self, left: str, right: str) -> float:
        trigram_score = self.db.scalar(
            select(
                # A one-way containment score can be 1.0 for a bare location
                # inside a full report. Requiring the weaker direction keeps
                # both texts responsible for the match.
                func.least(
                    func.word_similarity(
                        normalize_arabic_sql(literal(left)),
                        normalize_arabic_sql(literal(right)),
                    ),
                    func.word_similarity(
                        normalize_arabic_sql(literal(right)),
                        normalize_arabic_sql(literal(left)),
                    ),
                )
            )
        )
        token_score = balanced_event_token_similarity(left, right)
        return max(float(trigram_score or 0.0), float(token_score or 0.0))

    def has_pending_segment_review_match(
        self,
        *,
        incident_id: UUID,
        matched_incident_id: UUID,
    ) -> bool:
        match_id = self.db.scalar(
            select(DuplicateMatch.id)
            .where(
                DuplicateMatch.incident_id == incident_id,
                DuplicateMatch.matched_incident_id == matched_incident_id,
                DuplicateMatch.match_type == MatchType.soft,
                DuplicateMatch.status == MatchStatus.pending,
            )
            .limit(1)
        )
        return match_id is not None

    def find_story_candidates(
        self,
        *,
        village_ids: set[int],
        message_datetime: datetime,
        window_hours: int,
        embedding_threshold: float,
        max_results: int,
        candidate_text: str | None = None,
        candidate_embedding: list[float] | None = None,
        exclude_raw_message_id: int | None = None,
    ) -> list[StoryCandidate]:
        """Same-village prior incidents inside a wide hour window.

        Unlike :meth:`find_fast_dedup_candidates` this path does **not**
        require ``condition_id`` equality. Condition match/mismatch is an
        input to story-relationship classification, not a pre-filter.

        Ranked by embedding similarity descending and capped at
        ``max_results``. Rows below ``embedding_threshold`` or without an
        embedding are dropped. Returns empty when no village ids or no
        candidate embedding is supplied.
        """
        village_ids = {
            village_id
            for village_id in village_ids
            if isinstance(village_id, int) and not isinstance(village_id, bool)
        }
        if not village_ids or candidate_embedding is None or max_results <= 0:
            return []

        naive_dt = message_datetime.replace(tzinfo=None)
        lookup_days = max(1, (int(window_hours) + 23) // 24)
        event_date = naive_dt.date()
        start_date = event_date - timedelta(days=lookup_days)
        end_date = event_date + timedelta(days=lookup_days)
        max_gap_seconds = float(window_hours) * 3600.0

        columns: list[Any] = [Incident]
        want_text = bool(candidate_text and candidate_text.strip())
        columns.append(
            (
                1.0 - Incident.khabar_embedding.cosine_distance(candidate_embedding)
            ).label("embedding_similarity")
        )
        if want_text:
            columns.append(
                func.word_similarity(
                    normalize_arabic_sql(Incident.khabar),
                    normalize_arabic_sql(literal(candidate_text)),
                ).label("text_similarity")
            )

        filters = [
            Incident.village_id.in_(village_ids),
            Incident.is_deleted.is_(False),
            Incident.verification_status.is_distinct_from("rejected"),
            Incident.event_date >= start_date,
            Incident.event_date <= end_date,
            Incident.khabar_embedding.is_not(None),
        ]
        if exclude_raw_message_id is not None:
            filters.append(Incident.raw_message_id != exclude_raw_message_id)

        result = self.db.execute(select(*columns).where(*filters))
        if result is None:
            return []
        rows = result.all()

        candidates: list[StoryCandidate] = []
        for row in rows:
            incident = row[0]
            embedding_value = row[1]
            if embedding_value is None:
                continue
            embedding_similarity = float(embedding_value)
            if embedding_similarity < embedding_threshold:
                continue
            text_similarity: float | None = None
            if want_text:
                text_similarity = float(row[2] or 0.0)
            incident_dt = datetime.combine(
                incident.event_date, incident.event_time or time(0, 0)
            )
            gap_seconds = abs((incident_dt - naive_dt).total_seconds())
            if gap_seconds > max_gap_seconds:
                continue
            candidates.append(
                StoryCandidate(
                    incident=incident,
                    time_gap_seconds=gap_seconds,
                    embedding_similarity=embedding_similarity,
                    text_similarity=text_similarity,
                    token_similarity=event_token_similarity(
                        incident.khabar,
                        candidate_text,
                    ),
                )
            )

        candidates.sort(
            key=lambda c: (
                -(c.embedding_similarity or 0.0),
                c.time_gap_seconds,
            )
        )
        return candidates[:max_results]

    def find_cross_village_dedup_candidates(
        self,
        *,
        village_id: int,
        condition_id: int,
        message_datetime: datetime,
        lookup_window_days: int,
        min_text_similarity: float,
        candidate_text: str | None = None,
        candidate_embedding: list[float] | None = None,
        exclude_raw_message_id: int | None = None,
    ) -> list[FastDedupCandidate]:
        """Same-condition, *different*-village candidates for the cross-village
        possible_duplicate backstop.

        Pre-filters on ``word_similarity >= min_text_similarity`` when text is
        available so the elevated cross-village threshold is enforced in SQL.
        """
        naive_dt = message_datetime.replace(tzinfo=None)
        event_date = naive_dt.date()
        start_date = event_date - timedelta(days=lookup_window_days)
        end_date = event_date + timedelta(days=lookup_window_days)

        columns: list[Any] = [Incident]
        want_text = bool(candidate_text and candidate_text.strip())
        want_embedding = candidate_embedding is not None
        text_sim_col = None
        if want_text:
            text_sim_col = func.word_similarity(
                normalize_arabic_sql(Incident.khabar),
                normalize_arabic_sql(literal(candidate_text)),
            ).label("text_similarity")
            columns.append(text_sim_col)
        if want_embedding:
            columns.append(
                (
                    1.0 - Incident.khabar_embedding.cosine_distance(candidate_embedding)
                ).label("embedding_similarity")
            )

        filters = [
            Incident.village_id != village_id,
            Incident.condition_id == condition_id,
            Incident.is_deleted.is_(False),
            Incident.event_date >= start_date,
            Incident.event_date <= end_date,
        ]
        if exclude_raw_message_id is not None:
            filters.append(Incident.raw_message_id != exclude_raw_message_id)
        if text_sim_col is not None:
            filters.append(text_sim_col >= min_text_similarity)

        rows = self.db.execute(select(*columns).where(*filters)).all()

        candidates: list[FastDedupCandidate] = []
        for row in rows:
            incident = row[0]
            idx = 1
            text_similarity: float | None = None
            if want_text:
                text_similarity = float(row[idx] or 0.0)
                idx += 1
            embedding_similarity: float | None = None
            if want_embedding:
                value = row[idx]
                embedding_similarity = None if value is None else float(value)
                idx += 1
            incident_dt = datetime.combine(
                incident.event_date, incident.event_time or time(0, 0)
            )
            gap_seconds = abs((incident_dt - naive_dt).total_seconds())
            candidates.append(
                FastDedupCandidate(
                    incident=incident,
                    time_gap_seconds=gap_seconds,
                    text_similarity=text_similarity,
                    embedding_similarity=embedding_similarity,
                    token_similarity=event_token_similarity(
                        incident.khabar,
                        candidate_text,
                    ),
                )
            )

        candidates.sort(key=lambda c: c.time_gap_seconds)
        return candidates

    def soft_delete_superseded_by_summary(
        self,
        incident: Incident,
        *,
        canonical_incident_id: UUID | None,
        note: str,
    ) -> None:
        """Retire an old-path incident the summary backfill replaced (never a non-summary one)."""
        soft_delete_incident(self.db, incident, reason="SUMMARY_SUPERSEDED", canonical_incident_id=canonical_incident_id)
        incident.note = f"{incident.note}\n\n{note}" if incident.note else note
        evaluate_casualty_flags_safely(self.db, incident.id)

    def _record_soft_delete(
        self,
        incident: Incident,
        *,
        reason: DeletedReason,
        canonical_incident_id: UUID | None,
        performed_by: UUID | None = None,
    ) -> None:
        record_incident_change(
            self.db,
            incident_id=incident.id,
            action=UpdateAction.delete,
            old_values={"is_deleted": False},
            new_values={
                "is_deleted": True,
                "deleted_reason": reason.value,
                "canonical_incident_id": canonical_incident_id,
            },
            performed_by=performed_by,
        )
        evaluate_casualty_flags_safely(self.db, incident.id)
        if canonical_incident_id is not None:
            evaluate_casualty_flags_safely(self.db, canonical_incident_id)

    def soft_delete_for_raw_message_id(
        self,
        raw_message_id: int,
        *,
        representative_raw_message_id: int | None = None,
        similarity_score: float | None = None,
        reason: DeletedReason = DeletedReason.cluster_subsumption,
    ) -> list[UUID]:
        incidents = list(
            self.db.scalars(
                select(Incident).where(
                    Incident.raw_message_id == raw_message_id,
                    Incident.is_deleted.is_(False),
                )
            ).all()
        )
        for incident in incidents:
            representative_incident: Incident | None = None
            if representative_raw_message_id is not None:
                representative_incident = (
                    self.find_active_incident_for_raw_message_village(
                        representative_raw_message_id,
                        incident.village_id,
                    )
                )
            self.redirect_pending_duplicate_matches(
                retired_incident=incident,
                canonical_incident=representative_incident,
            )
            soft_delete_incident(self.db, incident, reason="RAW_MESSAGE_SOFT_DELETE", canonical_incident_id=(representative_incident.id if representative_incident else None))
            evaluate_casualty_flags_safely(self.db, incident.id)
            if representative_incident is not None:
                self.create_duplicate_match(
                    incident=incident,
                    matched_incident=representative_incident,
                    similarity_score=similarity_score or 0.0,
                    status=MatchStatus.confirmed_duplicate,
                )
        self.db.flush()
        if representative_raw_message_id is not None:
            self.mark_raw_duplicate_if_fully_subsumed(
                raw_message_id=raw_message_id,
                canonical_raw_message_id=representative_raw_message_id,
            )
        return [incident.id for incident in incidents]

    def soft_delete_for_village_incident(
        self,
        raw_message_id: int,
        village_id: int,
        *,
        matched_incident_id: UUID | None = None,
        similarity_score: float | None = None,
        reason: DeletedReason = DeletedReason.duplicate_merge,
    ) -> list[UUID]:
        """Soft-delete only the incident(s) for a specific (raw_message_id, village_id) pair."""
        incidents = list(
            self.db.scalars(
                select(Incident).where(
                    Incident.raw_message_id == raw_message_id,
                    Incident.village_id == village_id,
                    Incident.is_deleted.is_(False),
                )
            ).all()
        )
        matched_incident: Incident | None = None
        if matched_incident_id is not None:
            matched_incident = self.db.get(Incident, matched_incident_id)

        for incident in incidents:
            self.redirect_pending_duplicate_matches(
                retired_incident=incident,
                canonical_incident=matched_incident,
            )
            soft_delete_incident(self.db, incident, reason="RAW_MESSAGE_SOFT_DELETE", canonical_incident_id=matched_incident.id if matched_incident else None)
            evaluate_casualty_flags_safely(self.db, incident.id)
            if matched_incident is not None:
                self.create_duplicate_match(
                    incident=incident,
                    matched_incident=matched_incident,
                    similarity_score=similarity_score or 0.0,
                    status=MatchStatus.confirmed_duplicate,
                )
        self.db.flush()
        if matched_incident is not None and matched_incident.raw_message_id is not None:
            self.mark_raw_duplicate_if_fully_subsumed(
                raw_message_id=raw_message_id,
                canonical_raw_message_id=matched_incident.raw_message_id,
            )
        return [incident.id for incident in incidents]

    def mark_raw_duplicate_if_fully_subsumed(
        self,
        *,
        raw_message_id: int,
        canonical_raw_message_id: int,
    ) -> bool:
        """Link a raw to the canonical root once it has no active incidents.

        A raw may describe several villages, so retiring one village incident
        must not hide the entire source bulletin.
        """
        if raw_message_id == canonical_raw_message_id:
            return False
        if self.has_active_incidents_for_raw_message(raw_message_id):
            return False

        raw = self.db.get(RawMessage, raw_message_id)
        canonical = self.db.get(RawMessage, canonical_raw_message_id)
        if raw is None or canonical is None:
            return False

        visited = {raw_message_id}
        while canonical.duplicate_of_id is not None:
            if canonical.id in visited:
                raise ValueError("Circular raw-message duplicate chain detected.")
            visited.add(canonical.id)
            parent = self.db.get(RawMessage, canonical.duplicate_of_id)
            if parent is None:
                break
            canonical = parent

        if raw.id == canonical.id:
            return False
        raw.status = MessageStatus.duplicate
        raw.duplicate_of_id = canonical.id
        raw.error_message = None
        self.db.add(raw)
        # Keep every duplicate link direct. Existing children may point at a
        # row that has now itself been canonicalized.
        children = list(
            self.db.scalars(
                select(RawMessage).where(
                    RawMessage.duplicate_of_id == raw.id,
                    RawMessage.id != canonical.id,
                )
            ).all()
        )
        for child in children:
            child.duplicate_of_id = canonical.id
            self.db.add(child)
        return True

    def begin_nested(self) -> AbstractContextManager[object]:
        return self.db.begin_nested()

    def rollback(self) -> None:
        self.db.rollback()

    @classmethod
    def _visible_flag_exists(cls, reason_code: str | None = None) -> object:
        criteria = [
            IncidentVerificationFlag.incident_id == Incident.id,
            IncidentVerificationFlag.status == "open",
            IncidentVerificationFlag.flag_type.in_(cls._ENABLED_VERIFICATION_FLAG_TYPES),
            or_(IncidentVerificationFlag.visible_after.is_(None), IncidentVerificationFlag.visible_after <= func.now()),
        ]
        if reason_code is not None:
            criteria.append(IncidentVerificationFlag.reason_code == reason_code)
        return select(literal(1)).where(*criteria).exists()

    @classmethod
    def _needs_verification_column(cls) -> object:
        return or_(
            Incident.verification_status == "needs_verification",
            cls._visible_flag_exists(),
        )

    def _visible_flags_by_incident(self, incident_ids: list[UUID]) -> dict[UUID, list[IncidentVerificationFlag]]:
        if not incident_ids:
            return {}
        rows = self.db.scalars(
            select(IncidentVerificationFlag).where(
                IncidentVerificationFlag.incident_id.in_(incident_ids),
                IncidentVerificationFlag.status == "open",
                IncidentVerificationFlag.flag_type.in_(self._ENABLED_VERIFICATION_FLAG_TYPES),
                or_(IncidentVerificationFlag.visible_after.is_(None), IncidentVerificationFlag.visible_after <= func.now()),
            ).order_by(IncidentVerificationFlag.created_at)
        ).all()
        result: dict[UUID, list[IncidentVerificationFlag]] = {}
        for flag in rows:
            result.setdefault(flag.incident_id, []).append(flag)
        return result

    @classmethod
    def _flag_summary(cls, flag: IncidentVerificationFlag) -> str:
        detail = flag.detail if isinstance(flag.detail, dict) else {}
        return str(detail.get("summary") or cls._FLAG_LABELS.get(flag.reason_code, "Verification check"))[:240]

    @classmethod
    def _verification_payload(cls, incident_id, duplicate: bool, duplicate_reason, flags_by_incident) -> dict[str, Any]:
        flags = flags_by_incident.get(incident_id, [])
        types = (["duplicate"] if duplicate else []) + [
            "casualty_missing_number" if flag.reason_code == "count_missing" else "casualty_aggregate_toll"
            for flag in flags
        ]
        payload: dict[str, Any] = {
            "verification_types": list(dict.fromkeys(types)),
            "open_flags": [{
                "flag_id": flag.id, "reason_code": flag.reason_code,
                "label": cls._FLAG_LABELS.get(flag.reason_code, "Verification check"),
                "severity": flag.severity, "summary": cls._flag_summary(flag),
                "evidence_sentence": (flag.detail or {}).get("evidence_sentence"),
            } for flag in flags],
        }
        if flags:
            payload.update(verification_status="needs_verification", verification_reason=cls._flag_summary(flags[0]))
        return payload

    @staticmethod
    def _is_casualty_review_reason(reason: str | None) -> bool:
        return bool(
            reason
            and reason.startswith(("Category casualties", "Unsupported casualty_scope"))
        )

    @classmethod
    def _is_user_visible_needs_verification(cls, incident: Incident) -> bool:
        """True when stored NV should surface to list/detail clients."""
        return bool(
            incident.verification_status == "needs_verification"
        )

    def _should_keep_needs_verification_after_duplicate_clear(
        self,
        reason: str | None,
        incident: Incident | None = None,
    ) -> bool:
        """Preserve stored or source-backed non-duplicate review signals."""
        raw_message = (
            self.db.get(RawMessage, incident.raw_message_id)
            if incident is not None and incident.raw_message_id is not None
            else None
        )
        return bool(
            active_non_duplicate_verification_reasons(
                match_result=raw_message.match_result if raw_message else None,
                extraction_result=raw_message.extraction_result if raw_message else None,
                tier2_retry_count=(raw_message.tier2_retry_count or 0) if raw_message else 0,
                tier2_retry_limit=settings.extraction_max_retries,
                verification_reason=reason,
                village_id=getattr(incident, "village_id", None),
            )
        )

    @classmethod
    def _list_filters(
        cls,
        params: IncidentListParams,
        *,
        event_date_expr=None,
    ) -> list[object]:
        event_date_column = event_date_expr if event_date_expr is not None else Incident.event_date
        filters: list[object] = [
            Incident.is_deleted.is_(False),
            Incident.village_id.is_not(None),
            Incident.condition_id.not_in(AIR_VIOLATION_CONDITION_ID_TUPLE),
            cls._visible_incident_scope_filter(),
            # Summary-created incidents have no raw message of their own (so no stage can
            # re-read the bulletin for them); every other incident must be materialized.
            or_(
                Incident.origin == IncidentOrigin.summary,
                and_(
                    RawMessage.id.is_not(None),
                    RawMessage.status == MessageStatus.materialized,
                    ~RawMessage.raw_payload.op("?")("ocr_text"),
                ),
            ),
        ]
        if params.verification_status is None:
            filters.append(Incident.verification_status != "rejected")
        if params.village:
            village_pattern = f"%{params.village}%"
            filters.append(
                or_(
                    Village.ref_name_en.ilike(village_pattern),
                    Village.cad_name.ilike(village_pattern),
                    Village.ref_name_ar.ilike(village_pattern),
                )
            )
        if params.condition:
            filters.append(
                or_(
                    Condition.action_en.ilike(f"%{params.condition}%"),
                    Condition.action_ar.ilike(f"%{params.condition}%"),
                )
            )
        if params.source_type:
            filters.append(Source.type == params.source_type.lower())
        if params.source_name:
            filters.append(RawMessage.source_name == params.source_name)
        if params.event_date_from is not None:
            filters.append(event_date_column >= params.event_date_from)
        if params.event_date_to is not None:
            filters.append(event_date_column <= params.event_date_to)
        if params.flagged_only:
            filters.append(
                or_(
                    Incident.duplicate_flag.is_(True),
                    cls._needs_verification_column(),
                )
            )
        if params.verification_status == "needs_verification":
            filters.append(cls._needs_verification_column())
        elif params.verification_status == "matched":
            # Legacy alias: "confident / not needing verification".
            filters.append(Incident.verification_status != "needs_verification")
        elif params.verification_status is not None:
            filters.append(Incident.verification_status == params.verification_status)
            if params.verification_status in ("auto_processed", "verified"):
                filters.append(~cls._needs_verification_column())
        if params.verification_type == "duplicate":
            filters.append(Incident.duplicate_flag.is_(True))
        elif params.verification_type == "casualty_missing_number":
            filters.append(cls._visible_flag_exists("count_missing"))
        elif params.verification_type == "casualty_aggregate_toll":
            filters.append(cls._visible_flag_exists("aggregate_no_breakdown"))
        if params.duplicate_only:
            filters.append(Incident.duplicate_flag.is_(True))
        if params.has_casualties:
            filters.append(
                or_(
                    func.coalesce(Incident.total_deaths, 0) > 0,
                    func.coalesce(Incident.total_injuries, 0) > 0,
                )
            )
        return filters

    @classmethod
    def _outside_range_needs_verification_filters(
        cls, params: IncidentListParams
    ) -> list[object] | None:
        """Needs-verification rows hidden only by the event date range."""
        if params.verification_status != "needs_verification" and params.verification_type is None:
            return None
        if params.event_date_from is None and params.event_date_to is None:
            return None
        undated = params.model_copy(update={"event_date_from": None, "event_date_to": None})
        outside = [Incident.event_date.is_(None)]
        if params.event_date_from is not None:
            outside.append(Incident.event_date < params.event_date_from)
        if params.event_date_to is not None:
            outside.append(Incident.event_date > params.event_date_to)
        return [*cls._list_filters(undated), cls._needs_verification_column(), or_(*outside)]

    @staticmethod
    def _list_ordering(params: IncidentListParams) -> tuple[object, ...]:
        event_datetime = func.coalesce(
            RawMessage.message_datetime,
            RawMessage.received_at,
        )
        event_date = func.coalesce(
            Incident.event_date,
            func.date(event_datetime),
        )
        created_at = func.coalesce(Incident.created_at, RawMessage.received_at)
        raw_message_sort_id = func.coalesce(RawMessage.id, 0)
        if params.sort_order == "oldest":
            return (
                event_date.asc(),
                Incident.event_time.asc().nullslast(),
                created_at.asc(),
                raw_message_sort_id.asc(),
                Incident.id.asc().nullslast(),
            )
        return (
            event_date.desc(),
            Incident.event_time.desc().nullslast(),
            created_at.desc(),
            raw_message_sort_id.desc(),
            Incident.id.desc().nullslast(),
        )

    @staticmethod
    def _decode_list_cursor(cursor: str | None) -> dict[str, object] | None:
        if cursor is None:
            return None
        try:
            payload = json.loads(
                base64.urlsafe_b64decode(cursor.encode("ascii") + b"===")
            )
            created_at = datetime.fromisoformat(payload["sort_created_at"])
            event_date = date.fromisoformat(payload["sort_event_date"])
            event_time_is_null = payload["sort_event_time_is_null"]
            event_time = (
                None
                if event_time_is_null
                else time.fromisoformat(payload["sort_event_time"])
            )
            incident_id = payload["incident_id"]
            raw_message_id = payload["raw_message_id"]
            return {
                "sort_created_at": created_at,
                "sort_event_date": event_date,
                "sort_event_time_is_null": event_time_is_null,
                "sort_event_time": event_time,
                "raw_message_id": (
                    int(raw_message_id) if raw_message_id is not None else None
                ),
                "incident_id": UUID(incident_id) if incident_id is not None else None,
            }
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid incidents cursor.") from exc

    @staticmethod
    def _encode_list_cursor(row: Any) -> str:
        event_time = row["event_time"]
        payload = {
            "sort_created_at": row["created_at"].isoformat(),
            "sort_event_date": row["event_date"].isoformat(),
            "sort_event_time_is_null": event_time is None,
            "sort_event_time": event_time.isoformat()
            if event_time is not None
            else None,
            "raw_message_id": row["raw_message_id"],
            "incident_id": str(row["id"]) if row["id"] is not None else None,
        }
        return (
            base64.urlsafe_b64encode(
                json.dumps(payload, separators=(",", ":")).encode("utf-8")
            )
            .decode("ascii")
            .rstrip("=")
        )

    @staticmethod
    def _list_cursor_filter(
        params: IncidentListParams,
        cursor: dict[str, object],
        created_at: object,
        event_date: object,
    ) -> object:
        created_value = cursor["sort_created_at"]
        event_date_value = cursor["sort_event_date"]
        event_time_value = cursor["sort_event_time"]
        raw_message_id = cursor["raw_message_id"]
        raw_message_sort_id = func.coalesce(RawMessage.id, 0)
        raw_message_sort_value = raw_message_id if raw_message_id is not None else 0
        incident_id = cursor["incident_id"]
        before = params.sort_order == "newest"
        comparison = (
            (lambda column, value: column < value)
            if before
            else (lambda column, value: column > value)
        )
        created_equal = created_at == created_value
        event_date_equal = event_date == event_date_value
        event_time_equal = (
            Incident.event_time.is_(None)
            if event_time_value is None
            else Incident.event_time == event_time_value
        )
        event_time_after = (
            Incident.event_time.is_(None) if event_time_value is not None else false()
        )
        if event_time_value is not None:
            event_time_after = or_(
                comparison(Incident.event_time, event_time_value),
                Incident.event_time.is_(None),
            )
        incident_after = (
            or_(Incident.id.is_(None), comparison(Incident.id, incident_id))
            if incident_id is not None
            else false()
        )
        return or_(
            comparison(event_date, event_date_value),
            and_(event_date_equal, event_time_after),
            and_(
                event_date_equal,
                event_time_equal,
                comparison(created_at, created_value),
            ),
            and_(
                event_date_equal,
                event_time_equal,
                created_equal,
                comparison(raw_message_sort_id, raw_message_sort_value),
            ),
            and_(
                event_date_equal,
                event_time_equal,
                created_equal,
                raw_message_sort_id == raw_message_sort_value,
                incident_after,
            ),
        )

    @staticmethod
    def _has_incident_scoped_filters(params: IncidentListParams) -> bool:
        return bool(
            params.village
            or params.condition
            or params.source_type
            or params.source_name
            or params.event_date_from is not None
            or params.event_date_to is not None
            or params.flagged_only
            or params.verification_status is not None
            or params.duplicate_only
        )

    @staticmethod
    def _build_exact_hash(
        khabar: str,
        village_id: int,
        condition_id: int,
        event_date: str,
    ) -> str:
        normalized = " ".join(khabar.split())
        key = f"{normalized}|{village_id}|{condition_id}|{event_date}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _max_preserving_empty(current: int | None, incoming: Any) -> int | None:
        incoming_value = incoming if isinstance(incoming, int) else None
        if current is None and incoming_value is None:
            return None
        return max(current or 0, incoming_value or 0)

    @staticmethod
    def _append_unique_note(existing_note: str | None, note_text: str) -> str:
        if not existing_note:
            return note_text
        if note_text in existing_note:
            return existing_note
        return f"{existing_note}\n\n{note_text}"

    @staticmethod
    def _origin_village_note(origin_villages: Any) -> str | None:
        if not isinstance(origin_villages, list):
            return None
        normalized: list[str] = []
        for item in origin_villages:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if value and value not in normalized:
                normalized.append(value)
        if not normalized:
            return None
        if len(normalized) == 1:
            return f"Origin village: {normalized[0]}"
        return f"Origin villages: {', '.join(normalized)}"

    @staticmethod
    def _snapshot_merge_fields(incident: Incident) -> dict[str, Any]:
        return {
            "casualty_status": incident.casualty_status,
            "casualty_deaths_status": getattr(incident, "casualty_deaths_status", None),
            "casualty_injuries_status": getattr(incident, "casualty_injuries_status", None),
            "casualty_status_remaining_total": getattr(
                incident, "casualty_status_remaining_total", None
            ),
            "casualty_is_preliminary": incident.casualty_is_preliminary,
            "casualty_status_evidence": incident.casualty_status_evidence,
            "deaths": incident.deaths,
            "total_deaths": incident.total_deaths,
            "injuries": incident.injuries,
            "total_injuries": incident.total_injuries,
            "note": incident.note,
            "details_pending": incident.details_pending,
        }
    @staticmethod
    def _merge_casualty_status_fields(
        incident: Incident,
        incoming: dict[str, Any],
        *,
        incoming_is_newest: bool,
    ) -> None:
        if incoming.get("casualty_status") is None:
            return
        merged = merge_casualty_status(
            incident.casualty_status,
            bool(incident.casualty_is_preliminary),
            incident.casualty_status_evidence,
            incoming.get("casualty_status"),
            bool(incoming.get("casualty_is_preliminary")),
            incoming.get("casualty_status_evidence"),
            incoming_is_newest=incoming_is_newest,
            current_deaths_status=getattr(incident, "casualty_deaths_status", None),
            incoming_deaths_status=incoming.get("casualty_deaths_status"),
            current_injuries_status=getattr(incident, "casualty_injuries_status", None),
            incoming_injuries_status=incoming.get("casualty_injuries_status"),
            current_remaining_total=getattr(incident, "casualty_status_remaining_total", None),
            incoming_remaining_total=incoming.get("casualty_status_remaining_total"),
        )
        incident.casualty_status = merged["casualty_status"]
        incident.casualty_deaths_status = merged.get("casualty_deaths_status")
        incident.casualty_injuries_status = merged.get("casualty_injuries_status")
        incident.casualty_status_remaining_total = merged.get("casualty_status_remaining_total")
        incident.casualty_is_preliminary = merged["casualty_is_preliminary"]
        incident.casualty_status_evidence = merged["casualty_status_evidence"]

    @classmethod
    def _snapshot_merge_audit(
        cls,
        incident: Incident,
        detail: IncidentDetail | None,
    ) -> dict[str, Any]:
        snapshot = cls._snapshot_merge_fields(incident)
        if detail is None:
            return snapshot
        for key in detail.__table__.columns.keys():
            if key == "incident_id":
                continue
            snapshot[f"detail.{key}"] = getattr(detail, key)
        return snapshot

    @staticmethod
    def _merge_introduces_new_presence_categories(
        detail: IncidentDetail,
        mapped_fields: dict[str, Any],
    ) -> bool:
        for key, value in mapped_fields.items():
            if value is not True:
                continue
            column = IncidentDetail.__table__.columns.get(key)
            if column is None or column.type.python_type is not bool:
                continue
            if getattr(detail, key) is not True:
                return True
        return False

    @staticmethod
    def _casualty_merge_guard(
        existing: Incident,
        raw_message: RawMessage | None,
        incoming: dict[str, Any],
    ):
        extraction = dict(getattr(raw_message, "extraction_result", None) or {})
        match_result = dict(getattr(raw_message, "match_result", None) or {})
        return guard_casualty_merge(
            incident_village_id=existing.village_id,
            target_location_count=target_location_count_from_extraction(
                extraction.get("village"),
                extraction.get("village_roles"),
                extraction.get("sub_events"),
            ),
            casualty_scope=extraction.get("casualty_scope"),
            incoming_status=incoming.get("casualty_status"),
            village_matches=match_result.get("village_matches") or [],
        )

    def _admin_edited_casualty_fields(self, incident_id: UUID) -> set[str]:
        fields: set[str] = set()
        if not hasattr(self.db, "scalars"):
            return fields
        values = self.db.scalars(select(IncidentUpdate.new_values).where(
            IncidentUpdate.incident_id == incident_id,
            IncidentUpdate.performed_by.is_not(None),
            IncidentUpdate.action == UpdateAction.edit,
        )).all()
        for payload in values:
            fields.update(set(payload or {}) & {"deaths", "injuries", "total_deaths", "total_injuries"})
        return fields
    @staticmethod
    def _merge_source_label(raw_message: RawMessage | None) -> str | None:
        if raw_message is None:
            return None
        for candidate in (
            raw_message.source_name,
            raw_message.origin_account,
            raw_message.source_platform,
        ):
            if candidate:
                return str(candidate)
        return None

    @staticmethod
    def _source_reference_expression() -> object:
        return func.coalesce(
            func.nullif(RawMessage.origin_account, ""),
            func.nullif(RawMessage.source_name, ""),
            RawMessage.external_message_id,
        )

    @staticmethod
    def _source_link_from_raw_payload(raw_payload: Any) -> str | None:
        if not isinstance(raw_payload, dict):
            return None
        for key in ("post_link", "source_link", "link", "url", "post_url"):
            value = raw_payload.get(key)
            if isinstance(value, str):
                value = value.strip()
                if value:
                    return value
        return None

    @staticmethod
    def _sanitize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        sanitized = strip_emoji_and_pictographs(value).strip()
        return sanitized or None

    def _ensure_manual_source(self) -> Source:
        source = self.db.scalar(
            select(Source).where(Source.type == SourceType.manual).limit(1)
        )
        if source is not None:
            return source

        source = Source(
            type=SourceType.manual,
            name="Manual Entry",
            external_id="manual_incidents",
            config={},
            is_active=True,
        )
        self.db.add(source)
        self.db.flush()
        return source
