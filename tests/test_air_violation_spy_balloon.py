import importlib.util
import sys
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.news.constants.air_violation_conditions import AIR_VIOLATION_CONDITION_IDS
from app.news.dtos import MatchResultDTO, MatchResultStatus, VillageMatchResult
from app.news.models import AirViolation, MessageStatus
from app.news.repositories.air_violation_repository import AirViolationRepository
from app.news.services.matching.condition_evidence_override import (
    condition_from_explicit_evidence,
)
from app.sources.services.red_alert_collector import classify_condition


def test_spy_balloon_is_an_air_violation_condition():
    assert 34 in AIR_VIOLATION_CONDITION_IDS


def test_balloon_text_is_classified_as_spy_balloon():
    assert classify_condition("منطاد تجسسي إسرائيلي يحلق فوق بنت جبيل") == 34
    assert classify_condition("منطاد فوق صور") == 34
    assert classify_condition("بالون تجسس فوق الخيام") == 34
    assert classify_condition("spy balloon over Tyre") == 34


def test_thermal_balloons_stay_decoy_flares_not_spy_balloons():
    text = "إلقاء بالونات حرارية فوق الخيام"

    assert classify_condition(text) != 34
    assert condition_from_explicit_evidence(text) != "Spy Balloon"
    assert condition_from_explicit_evidence("منطاد تجسسي فوق صور") == "Spy Balloon"
    assert condition_from_explicit_evidence("منطاد تجسسي وغارة على صور") != "Spy Balloon"


def test_balloon_report_is_routed_to_air_violations_not_incidents():
    village = SimpleNamespace(
        id=7, ref_name_en="Bint Jbeil", ref_name_ar="بنت جبيل", acs_name=None,
        cad_name=None, caza_en="Bint Jubail", caza_ar="بنت جبيل",
    )
    db = MagicMock()
    db.scalar.return_value = None
    db.scalars.return_value.all.return_value = []
    db.execute.return_value.all.return_value = []
    db.get.side_effect = lambda model, key: (
        village if key == 7 else SimpleNamespace(action_ar="منطاد تجسسي", action_en="Spy Balloon")
    )
    text = "منطاد تجسسي إسرائيلي يحلق فوق بنت جبيل"
    from datetime import datetime, timezone

    message = SimpleNamespace(
        id=1, source_id=1, external_message_id=None, source_platform="telegram",
        raw_text=text, raw_payload={}, filter_result=None, status=MessageStatus.parsed,
        error_message=None, message_datetime=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
        received_at=None,
    )
    result = MatchResultDTO(
        village_matches=[VillageMatchResult(
            matched_village_id=7, village_confidence=1.0,
            village_match_status=MatchResultStatus.matched, village_review_required=False,
            raw_village_text="بنت جبيل",
        )],
        any_village_low_confidence=False, matched_condition_id=34, condition_confidence=1.0,
        condition_match_status=MatchResultStatus.matched, condition_review_required=False,
        raw_condition_text=text,
    )

    assert AirViolationRepository(db).route_from_match(message, result) is True
    written = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], AirViolation)]
    assert [row.condition_id for row in written] == [34]


def _load_migration_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "migrate_spy_balloon_incidents_to_air_violations.py"
    spec = importlib.util.spec_from_file_location("migrate_spy_balloon", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _incident(raw_message_id, village_id):
    return SimpleNamespace(
        id=f"incident-{raw_message_id}-{village_id}", raw_message_id=raw_message_id,
        village_id=village_id, source_id=1, event_date=date(2026, 10, 5),
        event_time=time(9, 0), event_month="October", khabar="balloon",
        note=None, source_link=None, is_deleted=False,
    )


def test_migration_dry_run_writes_nothing_and_reports_candidates():
    migration = _load_migration_script()
    db = MagicMock()
    db.scalars.return_value.all.return_value = [
        _incident(10, 1), _incident(10, 2), _incident(11, 3),
    ]
    db.scalar.return_value = None

    summary = migration.run(db, apply=False)

    assert summary.candidates == 3
    assert summary.processed == 0
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_migration_skips_incidents_whose_raw_message_already_has_an_air_violation():
    migration = _load_migration_script()
    db = MagicMock()
    db.scalars.return_value.all.return_value = [_incident(10, 1), _incident(11, 3)]
    db.scalar.side_effect = [123, None]

    summary = migration.run(db, apply=False)

    assert summary.skipped_existing == 1
    assert summary.candidates == 1
