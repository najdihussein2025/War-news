"""Read-only rescore of currently-flagged incidents against the current matcher.

Purpose
-------
Both matching fixes on ``main`` -- Arabic name normalization + compact-key
village scoring (``e2f33a7``) and the evidence-backed condition alias catalog
with bidirectional coverage ranking (``75a2a71`` / ``2abfdef``) -- change only
comparison-time behaviour. No historical ``raw_messages.match_result`` or
``incidents`` row was rewritten. This script recomputes, for every active
``needs_verification`` incident, what the village and condition match statuses
*would* be now, and reports how many incidents would fully auto-clear.

It writes nothing. It is safe to run against production data.

Method
------
* Load every active ``needs_verification`` incident and its representative
  ``raw_message`` (``match_result`` + ``extraction_result``).
* For each *stored* target village mention (``village_matches`` entries whose
  ``village_role`` is absent or ``target``) re-run the exact matcher path
  ``MatchingService`` uses: ``normalize_arabic_text`` then
  ``VillageRepository.find_similar`` then the 0.60 / 0.35 threshold ladder.
* Re-run the stored condition mention (``raw_condition_text``) through
  ``ConditionRepository.find_similar`` and the same ladder, including the
  id 2 / 39 distinguishing-token guard.
* An incident's match fully clears when the condition and every stored target
  village mention now land at ``matched`` (>= 0.60). "Fully auto-clears" then
  additionally requires no non-match uncertainty signal (``duplicate_flag`` --
  the only such signal present on the current 426; relevance / insufficient /
  casualty-transition signals are absent per docs/recon/verification-status-fix.md).

Results are cached per normalized mention string so the live pg_trgm queries
run once per distinct village / condition text.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
import app.news.models  # noqa: F401

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.news.dtos import MatchResultStatus
from app.news.models import Incident, RawMessage
from app.news.repositories.condition_repository import ConditionRepository
from app.news.repositories.village_repository import VillageRepository
from app.news.services.matching_service import (
    LOW_CONFIDENCE_THRESHOLD,
    MATCH_THRESHOLD,
    MatchingService,
)

NEAR_MISS_LO = 0.50
NEAR_MISS_HI = MATCH_THRESHOLD  # 0.60


@dataclass
class MentionRescore:
    text: str
    before_conf: float | None
    before_status: str | None
    after_conf: float | None
    after_status: str  # MatchResultStatus value


def _normalized_match_result(match_result: dict | None) -> dict | None:
    if not match_result:
        return None
    if "village_matches" in match_result:
        return match_result
    return {
        **match_result,
        "village_matches": [
            {
                "matched_village_id": match_result.get("matched_village_id"),
                "village_confidence": match_result.get("village_confidence"),
                "village_match_status": match_result.get(
                    "village_match_status", "unmatched"
                ),
                "village_review_required": match_result.get(
                    "village_review_required", True
                ),
                "raw_village_text": match_result.get("raw_village_text"),
                "village_role": match_result.get("village_role", "target"),
            }
        ],
    }


def _target_village_entries(match_result: dict) -> list[dict]:
    return [
        vm
        for vm in (match_result.get("village_matches") or [])
        if (vm.get("village_role") or "target") == "target"
    ]


def _band(conf: float | None) -> str:
    if conf is None:
        return "none"
    if conf >= MATCH_THRESHOLD:
        return "matched"
    if conf >= NEAR_MISS_LO:
        return "near_miss"  # 0.50 - 0.599
    if conf >= LOW_CONFIDENCE_THRESHOLD:
        return "moderate"  # 0.35 - 0.499
    return "far"  # < 0.35


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out",
        type=str,
        default=None,
        help="Optional path to write the full per-incident result as JSON.",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        service = MatchingService(VillageRepository(db), ConditionRepository(db))

        village_cache: dict[str, tuple[int | None, float | None, str]] = {}
        condition_cache: dict[str, tuple[int | None, float | None, str]] = {}

        def rescore_village(text: str) -> tuple[int | None, float | None, str]:
            key = text or ""
            if key not in village_cache:
                cm = service._match_mention(key, service.villages.find_similar)
                village_cache[key] = (cm.matched_id, cm.confidence, cm.status.value)
            return village_cache[key]

        def rescore_condition(text: str) -> tuple[int | None, float | None, str]:
            key = text or ""
            if key not in condition_cache:
                cm = service._match_mention(key, service.conditions.find_similar)
                condition_cache[key] = (cm.matched_id, cm.confidence, cm.status.value)
            return condition_cache[key]

        rows = db.execute(
            select(Incident, RawMessage)
            .join(RawMessage, RawMessage.id == Incident.raw_message_id)
            .where(
                Incident.verification_status == "needs_verification",
                Incident.is_deleted.is_(False),
            )
        ).all()

        total = len(rows)
        # Per-incident outcomes
        would_fully_auto_clear = 0          # match clears AND no other signal
        match_clears_but_dup_flag = 0       # match clears, blocked only by duplicate_flag
        still_village_only = 0
        still_condition_only = 0
        still_both = 0

        # Per-mention near-miss crossing (per incident entry, matching the
        # docs/recon "entries" methodology which is not deduped by message).
        village_nearmiss_total = 0
        village_nearmiss_crossed = 0
        condition_nearmiss_total = 0
        condition_nearmiss_crossed = 0

        # Aggregate band movement
        village_after_band = Counter()
        condition_after_band = Counter()

        per_incident_json: list[dict] = []

        # Cache the per-raw-message match verdict; many incidents share one message.
        message_verdict: dict[int, dict] = {}

        for incident, rm in rows:
            mr = _normalized_match_result(rm.match_result)
            if mr is None:
                # No stored match_result: cannot rescore, count as unresolved-both.
                still_both += 1
                per_incident_json.append(
                    {"incident_id": str(incident.id), "error": "no match_result"}
                )
                continue

            if rm.id not in message_verdict:
                targets = _target_village_entries(mr)
                village_mentions: list[MentionRescore] = []
                for vm in targets:
                    text = vm.get("raw_village_text") or ""
                    before_conf = vm.get("village_confidence")
                    _mid, after_conf, after_status = rescore_village(text)
                    village_mentions.append(
                        MentionRescore(
                            text=text,
                            before_conf=before_conf,
                            before_status=vm.get("village_match_status"),
                            after_conf=after_conf,
                            after_status=after_status,
                        )
                    )

                cond_text = mr.get("raw_condition_text") or ""
                _cid, cond_after_conf, cond_after_status = rescore_condition(cond_text)
                cond_mention = MentionRescore(
                    text=cond_text,
                    before_conf=mr.get("condition_confidence"),
                    before_status=mr.get("condition_match_status"),
                    after_conf=cond_after_conf,
                    after_status=cond_after_status,
                )

                villages_all_matched_now = bool(village_mentions) and all(
                    m.after_status == MatchResultStatus.matched.value
                    for m in village_mentions
                )
                condition_matched_now = (
                    cond_mention.after_status == MatchResultStatus.matched.value
                )

                message_verdict[rm.id] = {
                    "village_mentions": village_mentions,
                    "cond_mention": cond_mention,
                    "villages_all_matched_now": villages_all_matched_now,
                    "condition_matched_now": condition_matched_now,
                }

            verdict = message_verdict[rm.id]
            villages_ok = verdict["villages_all_matched_now"]
            condition_ok = verdict["condition_matched_now"]

            # Near-miss crossing tally (per incident entry)
            for m in verdict["village_mentions"]:
                if m.before_conf is not None and NEAR_MISS_LO <= m.before_conf < NEAR_MISS_HI:
                    village_nearmiss_total += 1
                    if m.after_conf is not None and m.after_conf >= MATCH_THRESHOLD:
                        village_nearmiss_crossed += 1
                village_after_band[_band(m.after_conf)] += 1
            cm = verdict["cond_mention"]
            if cm.before_conf is not None and NEAR_MISS_LO <= cm.before_conf < NEAR_MISS_HI:
                condition_nearmiss_total += 1
                if cm.after_conf is not None and cm.after_conf >= MATCH_THRESHOLD:
                    condition_nearmiss_crossed += 1
            condition_after_band[_band(cm.after_conf)] += 1

            if villages_ok and condition_ok:
                if bool(incident.duplicate_flag):
                    match_clears_but_dup_flag += 1
                else:
                    would_fully_auto_clear += 1
            elif not villages_ok and condition_ok:
                still_village_only += 1
            elif villages_ok and not condition_ok:
                still_condition_only += 1
            else:
                still_both += 1

            per_incident_json.append(
                {
                    "incident_id": str(incident.id),
                    "raw_message_id": rm.id,
                    "duplicate_flag": bool(incident.duplicate_flag),
                    "villages_all_matched_now": villages_ok,
                    "condition_matched_now": condition_ok,
                    "villages": [
                        {
                            "text": m.text,
                            "before": m.before_conf,
                            "after": m.after_conf,
                            "after_status": m.after_status,
                        }
                        for m in verdict["village_mentions"]
                    ],
                    "condition": {
                        "text": cm.text,
                        "before": cm.before_conf,
                        "after": cm.after_conf,
                        "after_status": cm.after_status,
                    },
                }
            )

        match_clears_total = would_fully_auto_clear + match_clears_but_dup_flag

        print("=" * 72)
        print("COMBINED MATCHING-FIX RESCORE  (read-only, no rows written)")
        print("=" * 72)
        print(f"active needs_verification incidents rescored : {total}")
        print(f"distinct representative raw_messages         : {len(message_verdict)}")
        print()
        print("-- incident-level outcome ------------------------------------------")
        print(f"match fully clears (condition + all target villages >= 0.60): {match_clears_total}")
        print(f"  -> would auto-clear now (no other signal)                 : {would_fully_auto_clear}")
        print(f"  -> match clears but still blocked by duplicate_flag       : {match_clears_but_dup_flag}")
        print(f"still blocked, village-only (condition ok)                  : {still_village_only}")
        print(f"still blocked, condition-only (villages ok)                 : {still_condition_only}")
        print(f"still blocked, both                                         : {still_both}")
        print()
        print("-- near-miss (0.50-0.599 stored) crossing 0.60 now ----------------")
        print(f"village mentions in near-miss band : {village_nearmiss_total:4d}   crossed: {village_nearmiss_crossed}")
        print(f"condition mentions in near-miss band: {condition_nearmiss_total:4d}   crossed: {condition_nearmiss_crossed}")
        print()
        print("-- after-fix band distribution (all rescored mentions) -----------")
        print(f"village   : {dict(village_after_band)}")
        print(f"condition : {dict(condition_after_band)}")
        print("=" * 72)

        if args.json_out:
            Path(args.json_out).write_text(
                json.dumps(per_incident_json, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            print(f"per-incident detail written to {args.json_out}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
