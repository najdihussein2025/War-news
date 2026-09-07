"""Evidence-backed Arabic condition aliases for similarity matching."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionAlias:
    text: str
    raw_message_ids: tuple[int, ...]


CONDITION_ALIASES: dict[str, tuple[ConditionAlias, ...]] = {
    "قصف مدفعي": (
        ConditionAlias("مدفعية العدو تستهدف", (521, 527, 529)),
        ConditionAlias("قذيفة مدفعية استهدفت", (358,)),
    ),
    "قنابل صوتية": (
        ConditionAlias("ألقت محلقة قنبلة صوتية", (272,)),
        ConditionAlias("تلقي قنبلة صوتية", (343,)),
    ),
    "تلغيم وتفجير": (
        ConditionAlias("تنفيذ عملية تفجير", (2889, 3124)),
    ),
    "قنابل": (
        ConditionAlias("ألقت مسيرة معادية قنبلة", (255,)),
    ),
    "عملية تمشيط": (
        ConditionAlias("تمشيط بالأسلحة الرشاشة", (703,)),
    ),
}
