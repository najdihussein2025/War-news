from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.llm.dtos import (
    CasualtyScope,
    ExtractionCasualties,
    ExtractionResult,
    ExtractionSubEvent,
    VillageRoleEntry,
)
from app.news.dtos import MatchResultStatus
from app.news.models import Incident, IncidentDetail, MessageStatus
from app.news.services.dedup.fast_path_dedup import FastPathDedupOutcome
from app.news.services.matching.matching_service import MatchingService
from app.news.services.materialization.incident_materialization_service import (
    IncidentMaterializationService,
)
from tests.test_incident_materialization_service import (
    _SessionStub,
    _representative,
)
from tests.test_matching_service import _SimilarRepositoryStub, _extraction


HOUSE_SPAN = "غارة على منزل في كفررمان أدت إلى 8 شهداء و11 جريحاً"
CAR_SPAN = "استُهدفت سيارة فاستُشهد مسعف وأصيب 2"


def _two_action_extraction() -> ExtractionResult:
    return ExtractionResult(
        is_relevant=True,
        village=["كفر رمان"],
        action_description="غارات على منزل وسيارة",
        sub_events=[
            ExtractionSubEvent(
                locations=[VillageRoleEntry(village="كفر رمان", deaths=8, injuries=11)],
                action_text="غارة على منزل",
                casualties=ExtractionCasualties(
                    deaths=8,
                    injuries=11,
                    total_deaths=8,
                    total_injuries=11,
                ),
                evidence_span=HOUSE_SPAN,
            ),
            ExtractionSubEvent(
                locations=[VillageRoleEntry(village="كفر رمان", deaths=1, injuries=2)],
                action_text="استهداف سيارة",
                casualties=ExtractionCasualties(
                    deaths=1,
                    injuries=2,
                    total_deaths=1,
                    total_injuries=2,
                    male_deaths=1,
                ),
                evidence_span=CAR_SPAN,
            ),
        ],
        casualties=ExtractionCasualties(),
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )


class _ConditionByTextStub:
    def find_similar(self, text: str, limit: int = 5):
        if "سيار" in text:
            return [(SimpleNamespace(id=8), 0.91)]
        return [(SimpleNamespace(id=1), 0.93)]


class _TalloussaBeitYahounVillageStub:
    def find_similar(self, text: str, limit: int = 5):
        village_id = 1001 if text == "Talloussa" else 1002
        return [
            (
                SimpleNamespace(
                    id=village_id,
                    ref_name_ar=text,
                    caza_ar=None,
                    caza_en=None,
                    coord_x=None,
                    coord_y=None,
                ),
                1.0,
            )
        ]


class _TalloussaBeitYahounConditionStub:
    def find_similar(self, text: str, limit: int = 5):
        condition_id = 18 if "sweep" in text.lower() else 46
        return [(SimpleNamespace(id=condition_id), 1.0)]


class _RouteVillageRepositoryStub:
    def find_similar(self, text: str, limit: int = 5):
        village_id = 652 if "حاروف" in text else 1529
        return [
            (
                SimpleNamespace(
                    id=village_id,
                    ref_name_ar=text,
                    caza_ar="النبطية",
                    caza_en="Nabatiyeh",
                    coord_x=None,
                    coord_y=None,
                ),
                1.0,
            )
        ]


class _Raw11553VillageRepositoryStub:
    def __init__(self) -> None:
        self.zawtar = self._village(1519, "زوطر الشرقية", 724681, 3689717)
        self.mansouri = self._village(976, "المنصوري", 701000, 3679000)
        self.batroun_helta = self._village(675, "حلتا", 755897, 3792122)
        self.kfar_chouba = self._village(813, "كفر شوبا", 750226, 3689888)

    @staticmethod
    def _village(village_id: int, name: str, x: float, y: float):
        return SimpleNamespace(
            id=village_id,
            ref_name_ar=name,
            caza_ar=None,
            caza_en=None,
            coord_x=x,
            coord_y=y,
        )

    def resolve_alias(self, _normalized_text: str):
        return None

    def find_geo_conditional_aliases(self, normalized_text: str):
        if normalized_text in {"حلتا", "مزرعه حلتا"}:
            return [(self.kfar_chouba, 1.0)]
        return []

    def find_similar(self, text: str, limit: int = 5):
        candidates = {
            "زوطر": [(self.zawtar, 1.0)],
            "المنصوري": [(self.mansouri, 1.0)],
            "حلتا": [(self.batroun_helta, 1.0)],
            "مزرعه حلتا": [(self.batroun_helta, 1.0)],
            "كفرشوبا": [(self.kfar_chouba, 1.0)],
        }
        return candidates.get(text, [])[:limit]


class _Raw11553ConditionRepositoryStub:
    def find_similar(self, text: str, limit: int = 5):
        condition_id = (
            28
            if "تفكيك" in text
            else 18
            if "تمشيط" in text
            else 21
            if "تفجير" in text
            else 5
        )
        return [(SimpleNamespace(id=condition_id), 1.0)]


def test_matching_scores_each_sub_event_action() -> None:
    service = MatchingService(
        _SimilarRepositoryStub(851, 0.9),
        _ConditionByTextStub(),
    )

    result = service.match(_two_action_extraction())

    assert len(result.sub_event_matches) == 2
    assert result.sub_event_matches[0].matched_condition_id == 1
    assert result.sub_event_matches[1].matched_condition_id == 8
    assert (
        result.sub_event_matches[0].condition_match_status == MatchResultStatus.matched
    )
    assert (
        result.sub_event_matches[1].condition_match_status == MatchResultStatus.matched
    )


def test_message_10395_creates_only_declared_location_action_pairs() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    extraction = _two_action_extraction()
    match_result = MatchingService(
        _SimilarRepositoryStub(851, 0.9),
        _ConditionByTextStub(),
    ).match(extraction)
    representative = _representative(match_result=match_result.model_dump(mode="json"))
    representative.extraction_result = extraction.model_dump(mode="json")
    fast_dedup = SimpleNamespace(
        decide_for_village=lambda **_kwargs: SimpleNamespace(
            outcome=FastPathDedupOutcome.materialize,
            representative_raw_message_id=None,
            canonical_incident_id=None,
        )
    )

    created = service.process_fast_path(representative, fast_dedup)  # type: ignore[arg-type]

    incidents = [value for value in db.committed if isinstance(value, Incident)]
    details = [value for value in db.committed if isinstance(value, IncidentDetail)]
    assert len(created) == 2
    assert len(incidents) == 2
    counts = sorted(
        (incident.deaths, incident.injuries, incident.condition_id)
        for incident in incidents
    )
    assert counts == [(1, 2, 8), (8, 11, 1)]
    assert incidents[0].exact_hash != incidents[1].exact_hash
    assert incidents[0].story_group_id is not None
    assert incidents[0].story_group_id == incidents[1].story_group_id
    assert {incident.village_id for incident in incidents} == {851}
    male_deaths = {detail.male_d for detail in details}
    assert male_deaths == {1, None}


def test_talloussa_beit_yahoun_materializes_distinct_conditions() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    extraction = ExtractionResult(
        is_relevant=True,
        village=["Talloussa", "Beit Yahoun"],
        village_roles=[
            VillageRoleEntry(village="Talloussa"),
            VillageRoleEntry(village="Beit Yahoun"),
        ],
        action_description="multiple actions across 2 villages",
        sub_events=[
            ExtractionSubEvent(
                locations=[VillageRoleEntry(village="Talloussa")],
                action_text="sweeping operations",
                casualties=ExtractionCasualties(),
                evidence_span="Sweeping operations near Talloussa",
            ),
            ExtractionSubEvent(
                locations=[VillageRoleEntry(village="Beit Yahoun")],
                action_text="illumination and incendiary shelling",
                casualties=ExtractionCasualties(),
                evidence_span="Illumination and incendiary shelling near Beit Yahoun",
            ),
        ],
        casualties=ExtractionCasualties(),
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )
    match_result = MatchingService(
        _TalloussaBeitYahounVillageStub(),
        _TalloussaBeitYahounConditionStub(),
    ).match(extraction)
    representative = _representative(match_result=match_result.model_dump(mode="json"))
    representative.extraction_result = extraction.model_dump(mode="json")
    fast_dedup = SimpleNamespace(
        decide_for_village=lambda **_kwargs: SimpleNamespace(
            outcome=FastPathDedupOutcome.materialize,
            representative_raw_message_id=None,
            canonical_incident_id=None,
        )
    )

    created = service.process_fast_path(representative, fast_dedup)  # type: ignore[arg-type]

    incidents = [value for value in db.committed if isinstance(value, Incident)]
    assert len(created) == 2
    assert sorted((incident.village_id, incident.condition_id) for incident in incidents) == [
        (1001, 18),
        (1002, 46),
    ]


def test_single_action_extraction_does_not_split() -> None:
    result = MatchingService(
        _SimilarRepositoryStub(11, 0.7),
        _SimilarRepositoryStub(5, 0.8),
    ).match(_extraction())

    assert result.sub_event_matches == []
    assert result.matched_condition_id == 5


def test_raw_9302_route_scoped_casualty_is_not_copied_to_both_endpoints() -> None:
    route_span = "شهيد في غارة استهدفت دراجة على طريق مرج حاروف - زبدين"
    extraction = ExtractionResult(
        is_relevant=True,
        village=["حاروف", "زبدين"],
        village_roles=[],
        action_description="غارة على دراجة نارية",
        sub_events=[
            ExtractionSubEvent(
                locations=[
                    VillageRoleEntry(village="حاروف"),
                    VillageRoleEntry(
                        village="زبدين",
                        deaths=1,
                        evidence_span=route_span,
                    ),
                ],
                action_text="غارة على دراجة نارية",
                casualties=ExtractionCasualties(
                    deaths=1,
                    total_deaths=1,
                    male_deaths=1,
                ),
                evidence_span=route_span,
            )
        ],
        casualty_scope=CasualtyScope.per_village_exact,
        casualties=ExtractionCasualties(),
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )
    match_result = MatchingService(
        _RouteVillageRepositoryStub(),
        _ConditionByTextStub(),
    ).match(extraction)
    representative = _representative(match_result=match_result.model_dump(mode="json"))
    representative.raw_text = route_span
    representative.extraction_result = extraction.model_dump(mode="json")
    db = _SessionStub()

    created = IncidentMaterializationService(db).process_fast_path(  # type: ignore[arg-type]
        representative,
        SimpleNamespace(
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.materialize,
                representative_raw_message_id=None,
                canonical_incident_id=None,
            )
        ),
    )

    assert len(created) == 2
    assert sorted(incident.deaths or 0 for incident in created) == [0, 1]
    assert created[0].story_group_id == created[1].story_group_id
    assert created[0].story_group_id is not None


def test_bulletin_aggregate_materializes_one_row_per_target_village() -> None:
    extraction = ExtractionResult(
        is_relevant=True,
        village=["ميس الجبل", "يارون", "رامية"],
        village_roles=[
            VillageRoleEntry(village="ميس الجبل"),
            VillageRoleEntry(village="يارون"),
            VillageRoleEntry(village="رامية"),
        ],
        action_description="سلسلة غارات متزامنة",
        casualty_scope=CasualtyScope.bulletin_aggregate,
        casualty_scope_evidence=(
            "سلسلة غارات طالت بلدات ميس الجبل ويارون ورامية، ما أسفر عن "
            "شهيدين و6 جرحى في حصيلة إجمالية"
        ),
        casualties=ExtractionCasualties(total_deaths=2, total_injuries=6),
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )
    match_result = {
        "matched_condition_id": 1,
        "condition_match_status": "matched",
        "village_matches": [
            {
                "matched_village_id": 101,
                "village_match_status": "matched",
                "village_role": "target",
                "raw_village_text": "ميس الجبل",
            },
            {
                "matched_village_id": 102,
                "village_match_status": "matched",
                "village_role": "target",
                "raw_village_text": "يارون",
            },
            {
                "matched_village_id": 103,
                "village_match_status": "matched",
                "village_role": "target",
                "raw_village_text": "رامية",
            },
        ],
    }
    representative = _representative(match_result=match_result)
    representative.raw_text = extraction.casualty_scope_evidence
    representative.extraction_result = extraction.model_dump(mode="json")
    db = _SessionStub()

    created = IncidentMaterializationService(db).process_fast_path(  # type: ignore[arg-type]
        representative,
        SimpleNamespace(
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.materialize,
                representative_raw_message_id=None,
                canonical_incident_id=None,
            )
        ),
    )

    assert len(created) == 3
    assert {incident.village_id for incident in created} == {101, 102, 103}
    assert {(incident.deaths, incident.injuries) for incident in created} == {
        (None, None)
    }
    assert {
        (incident.total_deaths, incident.total_injuries) for incident in created
    } == {(None, None)}


def test_locationless_multi_village_sub_events_are_flagged_not_multiplied() -> None:
    extraction = ExtractionResult(
        is_relevant=True,
        village=["زوطر", "المنصوري"],
        action_description="قصف مدفعي وتفجير",
        sub_events=[
            ExtractionSubEvent(
                locations=[],
                action_text="قصف مدفعي",
                evidence_span="قصف مدفعي باتجاه زوطر",
            ),
            ExtractionSubEvent(
                locations=[],
                action_text="تفجير",
                evidence_span="تفجير في المنصوري",
            ),
        ],
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )
    match_result = MatchingService(
        _SimilarRepositoryStub(976, 0.9),
        _ConditionByTextStub(),
    ).match(extraction)
    match_payload = match_result.model_dump(mode="json")
    match_payload["village_matches"][1]["matched_village_id"] = 977
    representative = _representative(match_result=match_payload)
    representative.extraction_result = extraction.model_dump(mode="json")
    representative.filter_result = {}
    representative.low_confidence_relevance = False
    db = _SessionStub()

    created = IncidentMaterializationService(db).process_fast_path(  # type: ignore[arg-type]
        representative,
        SimpleNamespace(),
    )

    assert created == []
    assert not any(isinstance(value, Incident) for value in db.committed)
    assert representative.status == MessageStatus.parsed
    assert representative.low_confidence_relevance is True
    assert representative.filter_result["needs_review"] is True
    assert "lack explicit location binding" in representative.error_message
    assert representative.fast_path_completed_at is not None


def test_raw_11553_materializes_only_declared_location_action_pairs() -> None:
    extraction = ExtractionResult(
        is_relevant=True,
        village=["زوطر", "المنصوري", "مزرعة حلتا", "كفرشوبا"],
        action_description="إطلاق قذائف هاون وتفجير وتفكيك وتمشيط",
        sub_events=[
            ExtractionSubEvent(
                locations=[VillageRoleEntry(village="زوطر")],
                action_text="إطلاق قذائف هاون",
                evidence_span="إطلاق قذائف هاون باتجاه بلدة زوطر الشرقية",
            ),
            ExtractionSubEvent(
                locations=[VillageRoleEntry(village="زوطر")],
                action_text="تمشيط بالأسلحة الرشاشة",
                evidence_span="عملية تمشيط بالأسلحة الرشاشة باتجاه البلدة",
            ),
            ExtractionSubEvent(
                locations=[VillageRoleEntry(village="المنصوري")],
                action_text="تفجير",
                evidence_span="عملية تفجير في بلدة المنصوري",
            ),
            ExtractionSubEvent(
                locations=[
                    VillageRoleEntry(
                        village="مزرعة حلتا",
                        qualifier_text="كفرشوبا",
                    )
                ],
                action_text="تفكيك أجهزة الإنترنت وألواح الطاقة الشمسية",
                evidence_span="تفكيك أجهزة الإنترنت وألواح الطاقة الشمسية في مزرعة حلتا – كفرشوبا",
            ),
            ExtractionSubEvent(
                locations=[VillageRoleEntry(village="حلتا")],
                action_text="قذيفة هاون",
                evidence_span="قذيفة هاون استهدفت محيط المنازل في بلدة حلتا",
            ),
        ],
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )
    village_repository = _Raw11553VillageRepositoryStub()
    match_result = MatchingService(
        village_repository,
        _Raw11553ConditionRepositoryStub(),
    ).match(extraction)
    representative = _representative(match_result=match_result.model_dump(mode="json"))
    representative.raw_text = "\n".join(
        event.evidence_span or "" for event in extraction.sub_events
    )
    representative.extraction_result = extraction.model_dump(mode="json")
    db = _SessionStub()
    fast_dedup = SimpleNamespace(
        decide_for_village=lambda **_kwargs: SimpleNamespace(
            outcome=FastPathDedupOutcome.materialize,
            representative_raw_message_id=None,
            canonical_incident_id=None,
        )
    )

    created = IncidentMaterializationService(db).process_fast_path(  # type: ignore[arg-type]
        representative,
        fast_dedup,
    )

    assert len(created) == 5
    assert sorted(
        (incident.village_id, incident.condition_id) for incident in created
    ) == [
        (813, 5),
        (813, 28),
        (976, 21),
        (1519, 5),
        (1519, 18),
    ]
    assert all(
        match.raw_village_text != "كفرشوبا" for match in match_result.village_matches
    )


def test_plain_between_clause_does_not_collapse_unrelated_action_villages() -> None:
    raw_text = (
        "القصف المدفعي: صربين علي الطاهر حداثا حاريص "
        "التفجيرات المعادية: بين برعشيت و كونين"
    )
    extraction = ExtractionResult(
        is_relevant=True,
        village=["صربين", "علي الطاهر", "حداثا", "حاريص", "برعشيت", "كونين"],
        action_description="multiple actions across 6 villages",
        sub_events=[
            ExtractionSubEvent(
                locations=[
                    VillageRoleEntry(village="صربين"),
                    VillageRoleEntry(village="علي الطاهر"),
                    VillageRoleEntry(village="حداثا"),
                    VillageRoleEntry(village="حاريص"),
                ],
                action_text="قصف مدفعي",
                evidence_span="القصف المدفعي: صربين علي الطاهر حداثا حاريص",
            ),
            ExtractionSubEvent(
                locations=[
                    VillageRoleEntry(village="برعشيت"),
                    VillageRoleEntry(village="كونين"),
                ],
                action_text="تلغيم وتفجير",
                evidence_span="التفجيرات المعادية: بين برعشيت و كونين",
            ),
        ],
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )
    village_matches = []
    for village_id, village, condition_id, event_index, event_size in [
        (1, "صربين", 5, 0, 4),
        (2, "علي الطاهر", 5, 0, 4),
        (3, "حداثا", 5, 0, 4),
        (4, "حاريص", 5, 0, 4),
        (5, "برعشيت", 21, 1, 2),
        (6, "كونين", 21, 1, 2),
    ]:
        village_matches.append(
            {
                "raw_village_text": village,
                "matched_village_id": village_id,
                "village_confidence": 1.0,
                "village_match_status": "matched",
                "village_review_required": False,
                "village_role": "target",
                "matched_condition_id": condition_id,
                "condition_match_status": "matched",
                "condition_review_required": False,
                "event_index": event_index,
                "event_location_count": event_size,
            }
        )
    representative = _representative(
        match_result={
            "village_matches": village_matches,
            "any_village_low_confidence": False,
            "raw_condition_text": "multiple actions across 6 villages",
            "condition_confidence": 0.8,
            "matched_condition_id": 5,
            "condition_match_status": "matched",
            "condition_review_required": False,
        }
    )
    representative.raw_text = raw_text
    representative.extraction_result = extraction.model_dump(mode="json")
    db = _SessionStub()

    created = IncidentMaterializationService(db).process_fast_path(  # type: ignore[arg-type]
        representative,
        SimpleNamespace(
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.materialize,
                representative_raw_message_id=None,
                canonical_incident_id=None,
            )
        ),
    )

    assert sorted((incident.village_id, incident.condition_id) for incident in created) == [
        (1, 5),
        (2, 5),
        (3, 5),
        (4, 5),
        (5, 21),
    ]
    assert all(incident.village_id != 6 for incident in created)
    mining = next(incident for incident in created if incident.condition_id == 21)
    assert mining.verification_status == "needs_verification"
    assert "كونين" in (mining.note or "")
