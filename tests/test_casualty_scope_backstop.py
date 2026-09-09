from app.llm.dtos import CasualtyScope, VillageRole, VillageRoleEntry
from app.news.services.incident_details.casualty_scope_backstop import (
    validate_casualty_scope,
)


def _target(
    village: str,
    *,
    deaths: int | None = None,
    injuries: int | None = None,
) -> VillageRoleEntry:
    return VillageRoleEntry(
        village=village,
        role=VillageRole.target,
        deaths=deaths,
        injuries=injuries,
    )


def test_per_village_exact_requires_local_count_and_village_in_evidence() -> None:
    valid = validate_casualty_scope(
        casualty_scope=CasualtyScope.per_village_exact,
        evidence="سقط 3 شهداء في كفررمان",
        village_roles=[_target("كفررمان", deaths=3)],
    )
    unsupported = validate_casualty_scope(
        casualty_scope=CasualtyScope.per_village_exact,
        evidence="سقط 3 شهداء",
        village_roles=[_target("كفررمان", deaths=3)],
    )

    assert valid.plausible is True
    assert valid.matched_village_names == ("كفررمان",)
    assert unsupported.plausible is False


def test_bulletin_aggregate_requires_two_distinct_target_villages() -> None:
    result = validate_casualty_scope(
        casualty_scope=CasualtyScope.bulletin_aggregate,
        evidence="حصيلة الغارات على النبطية وكفررمان بلغت 4 شهداء",
        village_roles=[_target("النبطية"), _target("كفررمان")],
    )

    assert result.plausible is True
    assert result.village_count_in_evidence == 2


def test_bulletin_aggregate_does_not_double_count_overlapping_name() -> None:
    result = validate_casualty_scope(
        casualty_scope=CasualtyScope.bulletin_aggregate,
        evidence="غارة على النبطية الفوقا أوقعت إصابتين",
        village_roles=[_target("النبطية"), _target("النبطية الفوقا")],
    )

    assert result.plausible is False
    assert result.matched_village_names == ("النبطية الفوقا",)


def test_known_alias_can_support_claimed_village() -> None:
    result = validate_casualty_scope(
        casualty_scope=CasualtyScope.per_village_exact,
        evidence="سقط شهيدان في حي المسلخ",
        village_roles=[_target("النبطية", deaths=2)],
        aliases_by_village={"النبطية": ("حي المسلخ",)},
    )

    assert result.plausible is True
    assert result.matched_village_names == ("النبطية",)
