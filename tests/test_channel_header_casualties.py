"""A channel/page name is never news content (raw 44770 and 37903 regression).

``صفحة الإعلامي الشهيد علي شعيب`` heads many posts. Its «الشهيد» belongs to the page
name; it must never produce a death, injury, status, gender evidence or evidence span.
Only the body counts.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import app.news.services  # noqa: F401  (import order: loader <-> matching_service)
from app.core.llm_knowledge.message_text import clean_message_text
from app.core.llm_knowledge.source_headers import header_spans, strip_source_headers
from app.llm.dtos import CasualtyCountEvidence, ExtractionCasualties, ExtractionResult
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.news.models import Incident
from app.news.repositories import IncidentRepository
from app.news.services.incident_details.casualty_count_backstop import apply_casualty_count_backstop
from app.news.services.incident_details.casualty_gender_evidence import (
    apply_casualty_gender_backstops,
    infer_singular_death_count,
)
from app.news.services.incident_details.casualty_merge_provenance import (
    vet_incoming_casualties,
    vet_root_casualties,
)
from tests.test_casualty_merge_provenance import OWN_BODY, _world, db  # noqa: F401

HEADER = "صفحة الإعلامي الشهيد علي شعيب"
YATER = "قصف مدفعي يستهدف المنطقة الواقعة بين بلدتي ياطر وبيت ليف"
MAYFADOUN = "قصف مدفعي استهدف اطراف بلدة ميفدون"
BODY_DEATH = "استشهاد مواطن بغارة على بلدة كفرا"
BODY_INJURY = "إصابة شخصين في غارة على بلدة كفرا"


def _result(casualties: ExtractionCasualties | None = None) -> ExtractionResult:
    return ExtractionResult(
        is_relevant=True,
        village=["كفرا"],
        casualties=casualties or ExtractionCasualties(),
        model="test",
        extracted_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
    )


def _extract(body: str, casualties: ExtractionCasualties, spans: dict[str, str], header: str = HEADER):
    """What the live Tier 1 path does with an LLM answer: backstops on the raw post."""
    raw = f"{header}\n{body}"
    evidence = [CasualtyCountEvidence(field=f, evidence_span=s) for f, s in spans.items()]
    counted, _ = apply_casualty_count_backstop(raw, casualties, evidence)
    return apply_casualty_gender_backstops(raw, _result(counted)).casualties


@pytest.mark.parametrize("body", [YATER, MAYFADOUN])
def test_header_plus_shelling_has_no_casualties(body):
    # What Tier 1 stored for raw 44770 / 37903: deaths 1, male_deaths 1, span «شهيد».
    llm = ExtractionCasualties(deaths=1, total_deaths=1, male_deaths=1)
    spans = {"deaths": "شهيد", "total_deaths": "شهيد", "male_deaths": "شهيد"}
    casualties = _extract(body, llm, spans)
    assert casualties == ExtractionCasualties()
    assert infer_singular_death_count(f"{HEADER}\n{body}", ExtractionCasualties()).deaths is None


def test_header_plus_real_body_death_is_one_death():
    casualties = _extract(
        BODY_DEATH,
        ExtractionCasualties(deaths=1, total_deaths=1),
        {"deaths": "استشهاد مواطن", "total_deaths": "استشهاد مواطن"},
    )
    assert (casualties.deaths, casualties.total_deaths) == (1, 1)


def test_header_plus_two_injured_keeps_injuries_and_leaves_deaths_null():
    casualties = _extract(
        BODY_INJURY,
        ExtractionCasualties(injuries=2, total_injuries=2),
        {"injuries": "إصابة شخصين", "total_injuries": "إصابة شخصين"},
    )
    assert (casualties.injuries, casualties.total_injuries) == (2, 2)
    assert casualties.deaths is None and casualties.total_deaths is None


def test_span_inside_the_header_is_rejected_even_when_the_body_has_none():
    casualties = _extract(
        YATER,
        ExtractionCasualties(deaths=1),
        {"deaths": "الشهيد علي شعيب"},
    )
    assert casualties.deaths is None  # NULL, not 0


def test_bare_martyr_token_without_event_context_is_rejected():
    for body in ("الشهيد", "رحم الله الشهيد"):
        casualties = _extract(body, ExtractionCasualties(deaths=1), {"deaths": "الشهيد"})
        assert casualties.deaths is None, body


@pytest.mark.parametrize(
    "variant",
    [
        "صفحة الإعلامي الشهيد علي شعيب",
        "الإعلامي الشهيد علي شعيب",  # no «صفحة»
        "صفحة  الاعلامي   الشهيد علي شعيب",  # spacing, hamza
        "صفحة الإعلامي الشَّهيد علي شُعيب",  # diacritics
        "صفحه الاعلامي الشهيد علي شعيب",  # ة/ه
        "صفحة الإعلامي الشهيدة علي شعيب",
        "صفحة الإعلامي الشهيد - علي شعيب",
        "الإعلامي الشهيد علي شعيب | " + YATER,
    ],
)
def test_header_variants_are_stripped(variant):
    text = f"{variant}\n{YATER}" if "|" not in variant else variant
    assert header_spans(text)
    stripped = strip_source_headers(text)
    assert "شعيب" not in stripped and "شهيد" not in stripped.replace("الشهيدة", "")
    assert YATER in stripped
    assert clean_message_text(text) == YATER


def test_header_is_stripped_anywhere_and_raw_text_is_untouched():
    raw = f"{YATER}\n{HEADER}"
    assert clean_message_text(raw) == YATER
    assert raw.startswith(YATER) and HEADER in raw  # the DB value is never rewritten


def test_ordinary_body_text_is_not_stripped():
    assert strip_source_headers(BODY_DEATH) == BODY_DEATH
    assert strip_source_headers("منزل الشهيد علي معلم") == "منزل الشهيد علي معلم"


def test_extract_tier1_strips_the_header_before_any_model_call(monkeypatch):
    seen: dict[str, str] = {}
    service = object.__new__(OllamaExtractionService)

    def fake_current(post_text, raw_message_id=None):
        seen["text"] = post_text
        return _result()

    monkeypatch.setattr(service, "_extract_tier1_current", fake_current)
    monkeypatch.setattr(service, "_extract_tier1_split", fake_current)
    service.extract_tier1(f"{HEADER}\n{YATER}", raw_message_id=1)
    assert seen["text"] == YATER


# --- merge guard -----------------------------------------------------------------


def test_vet_refuses_numbers_when_no_message_can_be_loaded():
    decision = vet_incoming_casualties(None, {"deaths": 1}, incident_village_id=1)
    assert decision.values["deaths"] is None
    assert decision.rejected[0]["reason"] == "no_linked_message"
    assert vet_incoming_casualties(None, {"deaths": None}, incident_village_id=1).clean


def test_vet_root_casualties_nulls_header_only_numbers():
    from types import SimpleNamespace

    raw = SimpleNamespace(id=1, raw_text=f"{HEADER}\n{YATER}", match_result=None)
    casualties, rejected = vet_root_casualties(raw, ExtractionCasualties(deaths=1, total_deaths=1, male_deaths=1))
    assert casualties == ExtractionCasualties() and rejected


def test_pipeline_merge_header_only_duplicate_keeps_canonical_null(db):  # noqa: F811
    own = OWN_BODY.format(village="ياطر")
    incident, _own, linked = _world(db, "ياطر", own, f"{HEADER}\n{own}")
    repo = IncidentRepository(db)
    repo.create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)
    repo.merge_existing(incident, {"deaths": 1, "total_deaths": 1, "khabar": "x"}, linked.id)
    assert (incident.deaths, incident.total_deaths) == (None, None)


def test_pipeline_merge_real_body_death_is_adopted(db):  # noqa: F811
    own = OWN_BODY.format(village="كفرا")
    incident, _own, linked = _world(db, "كفرا", own, f"{HEADER}\n{BODY_DEATH}")
    repo = IncidentRepository(db)
    repo.create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)
    repo.merge_existing(incident, {"deaths": 1, "total_deaths": 1, "khabar": "x"}, linked.id)
    assert (incident.deaths, incident.total_deaths) == (1, 1)


def _duplicate_pair(db, linked_text: str, duplicate_deaths: int):
    """A casualty-free canonical incident plus a pending duplicate built from linked_text."""
    from datetime import date, time

    from uuid import uuid4

    from app.accounts.models import Role, User
    from app.news.models import DuplicateMatch, MatchStatus, MatchType

    role = db.scalar(select(Role).limit(1))
    user = User(username=f"u{uuid4().hex[:8]}", password_hash="x", full_name="Admin", role_id=role.id)
    db.add(user)
    db.flush()
    own = OWN_BODY.format(village="ياطر")
    canonical, _own, linked = _world(db, "ياطر", own, linked_text)
    duplicate = Incident(
        raw_message_id=linked.id, village_id=canonical.village_id, condition_id=canonical.condition_id,
        source_id=canonical.source_id, event_date=date(2026, 10, 18), event_time=time(7, 22),
        khabar=linked_text, verification_status="needs_verification", duplicate_flag=True,
        deaths=duplicate_deaths, total_deaths=duplicate_deaths, casualty_status="exact",
        locked_by_user_id=user.id,
    )
    db.add(duplicate)
    db.flush()
    match = DuplicateMatch(
        incident_id=duplicate.id, matched_incident_id=canonical.id,
        status=MatchStatus.pending, match_type=MatchType.soft, similarity_score=0.9,
    )
    db.add(match)
    db.flush()
    return canonical, duplicate, match, user


def test_manual_duplicate_confirm_does_not_copy_header_only_death(db):  # noqa: F811
    canonical, duplicate, match, user = _duplicate_pair(db, f"{HEADER}\n{OWN_BODY.format(village='ياطر')}", 1)
    IncidentRepository(db).resolve_duplicate(
        duplicate.id, match.id, "confirmed_duplicate", duplicate.version, user.id
    )
    db.refresh(canonical)
    assert (canonical.deaths, canonical.total_deaths) == (None, None)
    assert canonical.casualty_status != "exact"


def test_manual_duplicate_confirm_copies_a_real_body_death(db):  # noqa: F811
    canonical, duplicate, match, user = _duplicate_pair(db, f"{HEADER}\n{BODY_DEATH}", 1)
    IncidentRepository(db).resolve_duplicate(
        duplicate.id, match.id, "confirmed_duplicate", duplicate.version, user.id
    )
    db.refresh(canonical)
    assert (canonical.deaths, canonical.total_deaths) == (1, 1)


def test_a_channel_word_on_another_line_does_not_reject_a_real_casualty():
    """28917: «- القناة 12 العبرية» two lines below «ارتقى 9 شهداء» used to reject the 9."""
    text = (
        "ابرز الاحداث:\n- ارتكب العدو مجازر في بلدة كفررمان حيث ارتقى 9 شهداء واصابة اكثر من 13 جريح.\n"
        "- القناة 12 العبرية: الليلة أطلق حزب الله مسيّرتين"
    )
    decision = vet_incoming_casualties(
        __import__("types").SimpleNamespace(id=1, raw_text=text, match_result=None),
        {"deaths": 9, "injuries": 13},
        incident_village_id=None,
    )
    assert decision.clean and decision.values == {"deaths": 9, "injuries": 13}


def test_memorial_word_on_the_same_line_still_rejects():
    text = "تشييع الشهيد: ارتقى 9 شهداء"
    decision = vet_incoming_casualties(
        __import__("types").SimpleNamespace(id=1, raw_text=text, match_result=None),
        {"deaths": 9},
        incident_village_id=None,
    )
    assert not decision.clean
