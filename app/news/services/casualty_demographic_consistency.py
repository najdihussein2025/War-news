from __future__ import annotations

from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
)


def reconcile_root_demographics(
    root: ExtractionCasualties,
    categories: dict[ExtractionCategoryKey, ExtractionCategory],
) -> ExtractionCasualties:
    """Resolve a root gender split contradicted by stronger category evidence.

    Category counts identify the people connected to a vehicle, institution, etc.
    When one gender's category count equals the complete reported total, the
    opposite gender cannot also have a positive count.  This is arithmetic
    reconciliation, not demographic guessing.  Child counts are preserved
    because age and gender can overlap.
    """
    values = root.model_dump(mode="python")
    for suffix, total_key, reported_key in (
        ("deaths", "total_deaths", "deaths"),
        ("injuries", "total_injuries", "injuries"),
    ):
        total = values.get(total_key) or values.get(reported_key)
        if not isinstance(total, int) or total <= 0:
            continue
        category_counts: dict[str, list[int]] = {"male": [], "female": []}
        for key, category in categories.items():
            if key == ExtractionCategoryKey.casualty_demographics:
                continue
            casualties = category.casualties
            if casualties is None:
                continue
            for gender in ("male", "female"):
                count = getattr(casualties, f"{gender}_{suffix}")
                if isinstance(count, int) and count > 0:
                    category_counts[gender].append(count)
        male_covers_total = total in category_counts["male"]
        female_covers_total = total in category_counts["female"]
        if male_covers_total == female_covers_total:
            continue
        confirmed = "male" if male_covers_total else "female"
        opposite = "female" if confirmed == "male" else "male"
        child_count = values.get(f"children_{suffix}")
        adult_count = total - child_count if isinstance(child_count, int) else total
        values[f"{confirmed}_{suffix}"] = adult_count if adult_count > 0 else None
        values[f"{opposite}_{suffix}"] = None
    return ExtractionCasualties.model_validate(values)
