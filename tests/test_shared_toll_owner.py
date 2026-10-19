"""Target C: multi-village casualty numbers.

Case 1 - per-village numbers: each village row gets only its own numbers.
Case 2 - one shared total: the full total sits on the FIRST village mentioned in the
         text (deterministic), the other rows stay null, all rows are linked to one
         bulletin group owned by that village.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.llm.dtos import CasualtyScope, ExtractionCasualties, ExtractionResult, ExtractionSubEvent, VillageRoleEntry
from app.news.models import Condition, Incident, RawMessage, Village
from app.news.models.bulletin_casualty_group import (
    BulletinCasualtyGroup,
    BulletinCasualtyGroupMember,
)
from app.news.models.raw_message import MessageStatus
from app.news.repositories.bulletin_casualty_group_repository import (
    BulletinCasualtyGroupRepository,
    ordered_unique,
)
from app.news.services.dedup.fast_path_dedup import FastPathDedupOutcome
from app.news.services.materialization.incident_materialization_service import (
    IncidentMaterializationService,
)
from app.sources.models import Source, SourceType
from tests.test_incident_materialization_service import _SessionStub

TYRE, NABATIEH, BEIRUT = (201, 202, 203)
SHARED_TEXT = "قصف على صور والنبطية وبيروت والحصيلة 10 شهداء"
PER_VILLAGE_TEXT = "قصف على صور والنبطية وبيروت: صور 2 شهداء، النبطية 3 جرحى، بيروت 4 شهداء بينهم طفلان"


def _match(village: str, village_id: int, **extra) -> dict:
    return {
        "matched_village_id": village_id,
        "village_match_status": "matched",
        "village_role": "target",
        "raw_village_text": village,
        "village_confidence": 1.0,
        "village_review_required": False,
        **extra,
    }


def _representative(text: str, extraction: ExtractionResult, matches: list[dict], *, message_id: int = 42):
    return SimpleNamespace(
        id=message_id, source_id=9, raw_text=text,
        message_datetime=datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc),
        content_embedding=None,
        extraction_result=extraction.model_dump(mode="json"),
        match_result={
            "village_matches": matches,
            "matched_condition_id": 5, "condition_match_status": "matched",
            "condition_review_required": False, "any_village_low_confidence": False,
        },
        status=MessageStatus.parsed, error_message=None,
        fast_path_completed_at=None, tier2_completed_at=None, embedded_at=None, materialized_at=None,
    )


def _fast_dedup():
    return SimpleNamespace(
        decide_for_village=lambda **_k: SimpleNamespace(
            outcome=FastPathDedupOutcome.materialize,
            representative_raw_message_id=None, canonical_incident_id=None,
        )
    )


def _run(representative, groups=None):
    groups = groups or SimpleNamespace(
        create_for_message=MagicMock(return_value=SimpleNamespace(owner_village_id=None)),
        get_by_raw_message_id=MagicMock(return_value=None),
    )
    service = IncidentMaterializationService(_SessionStub(), bulletin_groups=groups)  # type: ignore[arg-type]
    created = service.process_fast_path(representative, _fast_dedup())  # type: ignore[arg-type]
    return {incident.village_id: incident for incident in created}, groups


def _roles(*names):
    return [VillageRoleEntry(village=name) for name in names]


def test_case1_per_village_numbers_land_on_their_own_rows_only():
    extraction = ExtractionResult(
        is_relevant=True, village=["صور", "النبطية", "بيروت"],
        village_roles=[
            VillageRoleEntry(village="صور", deaths=2),
            VillageRoleEntry(village="النبطية", injuries=3),
            VillageRoleEntry(village="بيروت", deaths=4, children_deaths=2),
        ],
        casualty_scope=CasualtyScope.per_village_exact,
        casualty_scope_evidence=PER_VILLAGE_TEXT,
        casualties=ExtractionCasualties(),
        model="test", extracted_at=datetime.now(timezone.utc),
    )
    representative = _representative(
        PER_VILLAGE_TEXT, extraction,
        [_match("صور", TYRE, deaths=2), _match("النبطية", NABATIEH, injuries=3),
         _match("بيروت", BEIRUT, deaths=4, children_deaths=2)],
    )

    rows, groups = _run(representative)

    assert (rows[TYRE].deaths, rows[TYRE].injuries) == (2, None)
    assert (rows[NABATIEH].deaths, rows[NABATIEH].injuries) == (None, 3)
    assert (rows[BEIRUT].deaths, rows[BEIRUT].injuries) == (4, None)
    groups.create_for_message.assert_not_called()  # no shared toll, no group, no verification trigger


def test_case2_shared_total_sits_on_first_mentioned_village_only():
    extraction = ExtractionResult(
        is_relevant=True, village=["بيروت", "النبطية", "صور"],  # extraction order differs from text order
        village_roles=_roles("بيروت", "النبطية", "صور"),
        casualty_scope=CasualtyScope.bulletin_aggregate,
        casualty_scope_evidence=SHARED_TEXT,
        casualties=ExtractionCasualties(total_deaths=10),
        model="test", extracted_at=datetime.now(timezone.utc),
    )
    matches = [_match("بيروت", BEIRUT), _match("النبطية", NABATIEH), _match("صور", TYRE)]

    rows, groups = _run(_representative(SHARED_TEXT, extraction, matches))

    assert (rows[TYRE].deaths, rows[TYRE].total_deaths) == (10, 10)
    for member in (NABATIEH, BEIRUT):
        assert (rows[member].deaths, rows[member].total_deaths) == (None, None)
        assert (rows[member].injuries, rows[member].total_injuries) == (None, None)
    kwargs = groups.create_for_message.call_args.kwargs
    assert kwargs["village_ids"] == [TYRE, NABATIEH, BEIRUT]  # text order, not sorted, not extraction order
    assert kwargs["owner_village_id"] == TYRE
    assert sum(r.total_deaths or 0 for r in rows.values()) == 10  # counted once


def test_case2_stated_breakdown_goes_with_the_total_on_the_owner():
    extraction = ExtractionResult(
        is_relevant=True, village=["صور", "النبطية"], village_roles=_roles("صور", "النبطية"),
        casualty_scope=CasualtyScope.bulletin_aggregate,
        casualty_scope_evidence="غارات على صور والنبطية أدت إلى 5 شهداء بينهم 2 أطفال",
        casualties=ExtractionCasualties(total_deaths=5, children_deaths=2),
        model="test", extracted_at=datetime.now(timezone.utc),
    )
    rows, _ = _run(_representative(
        "غارات على صور والنبطية أدت إلى 5 شهداء بينهم 2 أطفال", extraction,
        [_match("صور", TYRE), _match("النبطية", NABATIEH)],
    ))
    assert rows[TYRE].total_deaths == 5
    assert rows[NABATIEH].total_deaths is None


def test_sub_event_demographics_are_not_copied_onto_every_location():
    sub_event = ExtractionSubEvent(
        locations=[VillageRoleEntry(village="صور", deaths=1), VillageRoleEntry(village="النبطية", deaths=1)],
        action_text="غارة", evidence_span="غارة على صور والنبطية",
        casualties=ExtractionCasualties(deaths=2, total_deaths=2, male_deaths=2),
    )
    own = IncidentMaterializationService._event_casualties_for_match(
        sub_event, {"deaths": 1, "event_location_count": 2}
    )
    assert own.deaths == 1 and own.male_deaths is None and own.children_deaths is None


def test_reprocessing_the_same_message_keeps_the_same_owner():
    matches_a = [_match("بيروت", BEIRUT), _match("النبطية", NABATIEH), _match("صور", TYRE)]
    matches_b = list(reversed(matches_a))
    order = IncidentMaterializationService._first_mention_village_ids
    assert order(SHARED_TEXT, matches_a) == order(SHARED_TEXT, matches_b) == [TYRE, NABATIEH, BEIRUT]
    # clitics attached to the name (وبيروت) and the name inside a longer word
    assert order("قصف على والنبطية وصور", [_match("صور", TYRE), _match("النبطية", NABATIEH)])[0] == NABATIEH
    assert order("عصور قديمة ثم صور", [_match("صور", TYRE)]) == [TYRE]
    assert ordered_unique([3, 1, 3, 2, 1]) == [3, 1, 2]


# --- database: group, ordered membership, owner link ----------------------------------

@pytest.fixture
def db():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for repository integration coverage.")
    engine = create_engine(database_url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _db_world(db: Session):
    marker = uuid4().hex
    source = Source(type=SourceType.api, name=f"Toll source {marker}", config={})
    villages = [
        Village(acs_code=int(marker[i * 7:(i + 1) * 7], 16), ref_name_en=f"Toll {name} {marker}", ref_name_ar=name)
        for i, name in enumerate(("صور", "النبطية", "بيروت"))
    ]
    condition = Condition(action_en=f"Condition {marker}", action_ar=f"حالة {marker}")
    db.add_all([source, condition, *villages])
    db.flush()
    raw = RawMessage(source_id=source.id, external_message_id=f"{marker}-bulletin", raw_text=SHARED_TEXT,
                     raw_payload={}, message_datetime=datetime(2026, 10, 19, 9, tzinfo=timezone.utc))
    db.add(raw)
    db.flush()
    incidents = [
        Incident(raw_message_id=raw.id, village_id=v.id, condition_id=condition.id, source_id=source.id,
                 event_date=datetime(2026, 10, 19).date(), khabar=SHARED_TEXT)
        for v in villages
    ]
    db.add_all(incidents)
    db.flush()
    return raw, villages, incidents


def test_group_keeps_text_order_owner_and_links_incidents(db):
    raw, (tyre, nabatieh, beirut), incidents = _db_world(db)
    repo = BulletinCasualtyGroupRepository(db)
    ordered = [tyre.id, nabatieh.id, beirut.id]

    group = repo.create_for_message(
        raw_message_id=raw.id, village_ids=ordered, owner_village_id=ordered[0],
        casualty_scope=__import__("app.news.models.bulletin_casualty_group", fromlist=["CasualtyScope"]).CasualtyScope.bulletin_aggregate,
        total_deaths=10, total_injuries=None,
    )
    repo.link_incidents(group, incidents)
    # Reprocessing the same message (even with the ids supplied in another order) keeps the owner.
    again = repo.create_for_message(
        raw_message_id=raw.id, village_ids=ordered, owner_village_id=None,
        casualty_scope=group.casualty_scope, total_deaths=10, total_injuries=None,
    )

    assert again.id == group.id and again.village_ids == ordered
    assert group.owner_village_id == tyre.id
    assert group.owner_incident_id == incidents[0].id
    members = db.scalars(
        select(BulletinCasualtyGroupMember).where(BulletinCasualtyGroupMember.group_id == group.id)
        .order_by(BulletinCasualtyGroupMember.ordinal)
    ).all()
    assert [m.village_id for m in members] == ordered
    assert [m.incident_id for m in members] == [i.id for i in incidents]
    assert repo.get_by_incident_id(incidents[2].id).id == group.id


def test_case2_every_row_is_flagged_for_verification():
    extraction = ExtractionResult(
        is_relevant=True, village=["صور", "النبطية", "بيروت"], village_roles=_roles("صور", "النبطية", "بيروت"),
        casualty_scope=CasualtyScope.bulletin_aggregate, casualty_scope_evidence=SHARED_TEXT,
        casualties=ExtractionCasualties(total_deaths=10),
        model="test", extracted_at=datetime.now(timezone.utc),
    )
    rows, _ = _run(_representative(
        SHARED_TEXT, extraction,
        [_match("صور", TYRE), _match("النبطية", NABATIEH), _match("بيروت", BEIRUT)],
    ))
    assert {r.verification_status for r in rows.values()} == {"needs_verification"}
    assert all(r.verification_reason for r in rows.values())


def _owned_group(db: Session):
    from app.news.models.bulletin_casualty_group import CasualtyScope as StoredScope

    raw, (tyre, nabatieh, beirut), incidents = _db_world(db)
    repo = BulletinCasualtyGroupRepository(db)
    ids = [tyre.id, nabatieh.id, beirut.id]
    group = repo.create_for_message(
        raw_message_id=raw.id, village_ids=ids, owner_village_id=ids[0],
        casualty_scope=StoredScope.bulletin_aggregate, total_deaths=10, total_injuries=None,
    )
    repo.link_incidents(group, incidents)
    return raw, group, incidents


def test_recompute_keeps_the_full_toll_on_the_owner_and_nulls_members(db):
    from app.news.services.incident_details.incident_casualty_recompute import recompute_incident_casualties

    _, _, (owner, member_a, member_b) = _owned_group(db)
    for incident in (owner, member_a, member_b):
        recompute_incident_casualties(db, incident, reason_code="repair")

    assert (owner.deaths, owner.total_deaths) == (10, 10)
    assert (member_a.deaths, member_a.total_deaths) == (None, None)
    assert (member_b.deaths, member_b.total_deaths) == (None, None)


def test_reconciliation_never_moves_the_toll_off_the_owner(db):
    from app.news.services.reconciliation.bulletin_reconciliation_service import BulletinReconciliationService

    raw, group, (owner, member_a, member_b) = _owned_group(db)
    owner.deaths = owner.total_deaths = 10
    later = RawMessage(
        source_id=raw.source_id, external_message_id=f"{uuid4().hex}-later", raw_payload={},
        raw_text="صور 2 شهداء، النبطية 3 شهداء، بيروت 5 شهداء",
        message_datetime=datetime(2026, 10, 19, 10, tzinfo=timezone.utc),
        match_result={"village_matches": [
            _match("صور", owner.village_id, deaths=2),
            _match("النبطية", member_a.village_id, deaths=3),
            _match("بيروت", member_b.village_id, deaths=5),
        ]},
    )
    db.add(later)
    db.flush()
    service = BulletinReconciliationService(db)

    assert service._apply_candidate(group, later, resolved_at=datetime.now(timezone.utc)) is False
    assert service._apply_candidate(group, later, resolved_at=datetime.now(timezone.utc)) is False  # idempotent

    assert (owner.deaths, owner.total_deaths) == (10, 10)
    assert (member_a.deaths, member_b.deaths) == (None, None)
    assert owner.verification_status == "needs_verification"
    proposals = [u for u in db.scalars(select(__import__("app.news.models", fromlist=["IncidentUpdate"]).IncidentUpdate)
                 .where(__import__("app.news.models", fromlist=["IncidentUpdate"]).IncidentUpdate.incident_id == owner.id)).all()
                 if (u.new_values or {}).get("reason_code") == "reconciled_proposal"]
    assert len(proposals) == 1
    assert proposals[0].new_values["proposed_breakdown"][str(member_a.village_id)] == {"deaths": 3, "injuries": None}
    assert group.breakdown_status.value == "pending"


def test_per_village_breakdown_requires_the_village_own_evidence():
    from tests.test_extraction_service import (
        _CategoryDetailStub, _PresenceGateStub, _client_for_model_contents, _general_response,
    )
    from app.llm.services.ollama_extraction_service import OllamaExtractionService

    service = OllamaExtractionService(
        client=_client_for_model_contents([_general_response()]),
        presence_gate=_PresenceGateStub(categories=[]),
        category_detail=_CategoryDetailStub(details={}),
    )
    text = PER_VILLAGE_TEXT
    roles = service._validated_village_roles(
        [
            VillageRoleEntry(village="بيروت", deaths=4, children_deaths=2, evidence_span="بيروت 4 شهداء بينهم طفلان"),
            VillageRoleEntry(village="صور", deaths=2, male_deaths=2, evidence_span="صور 2 شهداء"),
        ],
        text,
        1,
    )
    by_name = {role.village: role for role in roles}
    assert by_name["بيروت"].children_deaths == 2          # stated for Beirut itself
    assert by_name["صور"].male_deaths is None              # "2 شهداء" is untyped: never guessed
    assert by_name["صور"].deaths == 2
