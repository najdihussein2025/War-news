"""Backfill ACCSTUDY null village_id rows after Debl/Jibbayn alias migration.

Works on already-materialized/error raw messages by calling MatchingService
directly (MatchIncidentAction only accepts status=parsed).
"""

from __future__ import annotations

import re
from copy import deepcopy

from pydantic import ValidationError
from sqlalchemy import select, text

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import ExtractionResult
from app.news.models import Incident, RawMessage
from app.news.models.village_location_alias import VillageLocationAlias
from app.news.repositories.condition_repository import ConditionRepository
from app.news.repositories.village_repository import VillageRepository
from app.news.services.matching.matching_service import MatchingService


def _village_list(extraction: dict) -> list[str]:
    villages = extraction.get("village")
    if isinstance(villages, list):
        return [v.strip() for v in villages if isinstance(v, str) and v.strip()]
    if isinstance(villages, str) and villages.strip():
        return [villages.strip()]
    return []


def _role_is_target(vm) -> bool:
    role = getattr(vm, "village_role", None)
    if role is None:
        return True
    value = getattr(role, "value", role)
    return value == "target"


def main() -> None:
    db = SessionLocal()
    try:
        aliases = list(
            db.scalars(
                select(VillageLocationAlias).where(
                    VillageLocationAlias.is_active.is_(True)
                )
            ).all()
        )
        aliases.sort(key=lambda a: len(a.alias_normalized or ""), reverse=True)

        incidents = list(
            db.scalars(
                select(Incident).where(
                    Incident.note.like("ACCSTUDY-%"),
                    Incident.village_id.is_(None),
                    Incident.is_deleted.is_(False),
                )
            ).all()
        )
        print(f"null_village_accstudy={len(incidents)}")

        matcher = MatchingService(VillageRepository(db), ConditionRepository(db))
        village_repo = VillageRepository(db)

        rematched = 0
        filled = 0
        extracted_patched = 0
        skipped = 0

        for incident in incidents:
            raw = (
                db.get(RawMessage, incident.raw_message_id)
                if incident.raw_message_id
                else None
            )
            if raw is None or raw.extraction_result is None:
                skipped += 1
                continue

            extraction = deepcopy(raw.extraction_result)
            village_list = _village_list(extraction)

            if not village_list:
                khabar = incident.khabar or raw.raw_text or ""
                norm_khabar = normalize_arabic_text(khabar)
                found: list[str] = []
                for alias in aliases:
                    token = alias.alias_normalized
                    if not token:
                        continue
                    pattern = (
                        rf"(?<![\w\u0600-\u06FF]){re.escape(token)}"
                        rf"(?![\w\u0600-\u06FF])"
                    )
                    if re.search(pattern, norm_khabar):
                        found.append(alias.alias_text)

                recovered: list[str] = []
                seen_ids: set[int] = set()
                for text_alias in found:
                    hit = village_repo.resolve_alias(
                        normalize_arabic_text(text_alias)
                    )
                    if hit is None:
                        continue
                    village, _score = hit
                    if village.id in seen_ids:
                        continue
                    seen_ids.add(village.id)
                    recovered.append(text_alias)

                if recovered:
                    village_list = recovered
                    extracted_patched += 1

            if village_list:
                # Ensure village_roles are VillageRoleEntry-shaped dicts.
                roles = extraction.get("village_roles") or []
                roles_ok = (
                    isinstance(roles, list)
                    and len(roles) == len(village_list)
                    and all(
                        isinstance(role, dict) and isinstance(role.get("village"), str)
                        for role in roles
                    )
                )
                if not roles_ok:
                    extraction["village"] = village_list
                    extraction["village_roles"] = [
                        {"village": name, "role": "target"} for name in village_list
                    ]
                    raw.extraction_result = extraction
                    db.add(raw)
                    db.flush()
                    extracted_patched += 1

            if not village_list:
                skipped += 1
                continue

            try:
                extraction_dto = ExtractionResult.model_validate(extraction)
            except ValidationError:
                skipped += 1
                continue

            result = matcher.match(extraction_dto)
            raw.match_result = result.model_dump(mode="json")
            db.add(raw)
            rematched += 1

            chosen_id = None
            chosen_display = None
            for vm in result.village_matches:
                if not _role_is_target(vm):
                    continue
                status = getattr(
                    vm.village_match_status, "value", vm.village_match_status
                )
                if status not in {"matched", "matched_low_confidence"}:
                    continue
                if isinstance(vm.matched_village_id, int):
                    chosen_id = vm.matched_village_id
                    if getattr(vm, "alias_matched", False):
                        chosen_display = (vm.raw_village_text or "").strip() or None
                    break

            if chosen_id is None:
                for vm in result.village_matches:
                    status = getattr(
                        vm.village_match_status, "value", vm.village_match_status
                    )
                    if status not in {"matched", "matched_low_confidence"}:
                        continue
                    if isinstance(vm.matched_village_id, int):
                        chosen_id = vm.matched_village_id
                        if getattr(vm, "alias_matched", False):
                            chosen_display = (
                                (vm.raw_village_text or "").strip() or None
                            )
                        break

            if chosen_id is None:
                skipped += 1
                continue

            incident.village_id = chosen_id
            if chosen_display and not incident.village_display_name:
                incident.village_display_name = chosen_display
            db.add(incident)
            filled += 1

        db.commit()
        print(
            f"rematched={rematched} filled={filled} "
            f"extracted_patched={extracted_patched} skipped={skipped}"
        )

        rows = db.execute(
            text(
                """
                SELECT i.note, i.village_id, v.ref_name_en, i.village_display_name,
                       LEFT(i.khabar, 60)
                FROM incidents i
                LEFT JOIN villages v ON v.id = i.village_id
                WHERE i.note IN ('ACCSTUDY-001', 'ACCSTUDY-004')
                ORDER BY i.note
                """
            )
        ).all()
        for row in rows:
            print(row)

        remaining = db.execute(
            text(
                """
                SELECT COUNT(*) FILTER (WHERE village_id IS NULL) AS null_v,
                       COUNT(*) AS total
                FROM incidents
                WHERE note LIKE 'ACCSTUDY-%' AND COALESCE(is_deleted, false) = false
                """
            )
        ).one()
        print(f"remaining_null={remaining[0]} total={remaining[1]}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
