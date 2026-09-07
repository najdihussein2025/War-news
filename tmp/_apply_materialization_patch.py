"""Replace confident_duplicate override + pass event_time to find_best_match."""
from __future__ import annotations

from pathlib import Path

TARGET = Path(
    "app/news/services/materialization/incident_materialization_service.py"
)
# Note: service-folder refactors may move this file; re-run if sole-verdict
# markers disappear from the confident_duplicate block.

START = "            if decision.outcome == FastPathDedupOutcome.confident_duplicate:"
# Distinct-path insert (unique: no duplicate_flag kwarg)
END = """            incident = self._insert_fast_incident(
                representative=representative,
                extraction=extraction,
                village_id=village_id,
                condition_id=condition_id,
                event_datetime=event_datetime,
                origin_villages=origin_villages,
            )"""

NEW_BLOCK = '''            if decision.outcome == FastPathDedupOutcome.confident_duplicate:
                # DuplicateComparisonService is the sole verdict authority on the
                # fast path — do not re-score with DedupMatchingService /
                # dedup_time_window_days (that override reintroduced Mansouri-class
                # false positives).
                canonical_incident = decision.canonical_incident
                if decision.representative_raw_message_id is not None:
                    representative_raw_message_id = decision.representative_raw_message_id

                if (
                    self.dedup_service is not None
                    and village_id is not None
                    and canonical_incident is not None
                ):
                    mapped_fields = map_categories(
                        extraction.categories,
                        emergency_org_matcher=self.emergency_org_matcher,
                    )
                    casualties = extraction.casualties
                    total_deaths, total_injuries = compute_rollups(
                        mapped_fields,
                        casualties,
                    )
                    score = decision.similarity_score or 0.0
                    try:
                        self.dedup_service.merge_into_incident(
                            existing=canonical_incident,
                            new_candidate_data={
                                "deaths": casualties.deaths,
                                "injuries": casualties.injuries,
                                "total_deaths": total_deaths,
                                "total_injuries": total_injuries,
                                "khabar": representative.raw_text or "",
                                "origin_villages": origin_villages,
                                "mapped_fields": mapped_fields,
                                "casualty_transitions": [
                                    item.model_dump(mode="json")
                                    for item in extraction.casualty_transitions
                                ],
                            },
                            raw_message_id=representative.id,
                        )
                        fast_dedup.incidents.create_fast_path_duplicate_match(
                            canonical_incident=canonical_incident,
                            raw_message_id=representative.id,
                            status=MatchStatus.confirmed_duplicate,
                            similarity_score=score,
                        )
                        self._mark_materialized(representative, fast_path=True)
                        self.db.commit()
                        created.append(canonical_incident)
                        logger.info(
                            "raw_message_id=%s village_id=%s fast_path merged into "
                            "incident_id=%s score=%.3f method=%s",
                            representative.id,
                            village_id,
                            canonical_incident.id,
                            score,
                            decision.similarity_method,
                        )
                    except Exception:
                        self.db.rollback()
                        raise
                    if holds_village_lock:
                        self.db.commit()
                    continue

                confident_duplicate_villages += 1
                self.fast_stats.skipped_confident_duplicate += 1
                try:
                    if canonical_incident is not None:
                        # Link-only path keeps the historical kwargs (no score) so
                        # lightweight test doubles and older callers stay valid.
                        fast_dedup.incidents.create_fast_path_duplicate_match(
                            canonical_incident=canonical_incident,
                            raw_message_id=representative.id,
                        )
                    representative.fast_path_completed_at = datetime.now(timezone.utc)
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
                logger.info(
                    "raw_message_id=%s village_id=%s fast_path confident_duplicate "
                    "canonical_incident_id=%s representative_raw_message_id=%s "
                    "duplicate_match_written=%s (link only; no merge service)",
                    representative.id,
                    village_id,
                    decision.canonical_incident_id,
                    decision.representative_raw_message_id,
                    canonical_incident is not None,
                )
                continue

'''

OLD_CALL = """                existing, score = self.dedup_service.find_best_match(
                    village_id=village_id,
                    condition_id=condition_id,
                    event_date=event_datetime.date(),
                    khabar_embedding=khabar_embedding,
                    exclude_raw_message_id=representative.id,
                )"""

NEW_CALL = """                existing, score = self.dedup_service.find_best_match(
                    village_id=village_id,
                    condition_id=condition_id,
                    event_date=event_datetime.date(),
                    khabar_embedding=khabar_embedding,
                    exclude_raw_message_id=representative.id,
                    event_time=event_datetime.time(),
                )"""


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "sole verdict authority" in text and "event_time=event_datetime.time()" in text:
        print("already patched")
        compile(text, str(TARGET), "exec")
        return

    start = text.index(START)
    end = text.index(END, start)
    text = text[:start] + NEW_BLOCK + text[end:]
    if OLD_CALL not in text:
        raise SystemExit("materialize find_best_match call not found after block replace")
    text = text.replace(OLD_CALL, NEW_CALL, 1)
    compile(text, str(TARGET), "exec")
    TARGET.write_text(text, encoding="utf-8")
    print("patched materialization confident_duplicate + event_time")


if __name__ == "__main__":
    main()
