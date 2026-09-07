#!/usr/bin/env python
"""Phase 2 recon sampling — read-only DB probes for Bugs 1–3."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Ensure UTF-8 stdout on Windows consoles
sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev",
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from app.llm.dtos import ExtractionCasualties
from app.news.services.incident_details.casualty_gender_evidence import (
    _EXPLICIT_FORMS,
    apply_explicit_arabic_gender_evidence,
)

engine = create_engine(os.environ["DATABASE_URL"])


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def bug1() -> None:
    section("BUG 1 — note pollution / note_extra / incident_updates")
    with engine.connect() as c:
        rows = c.execute(
            text(
                """
                SELECT
                  count(*) AS total_incidents,
                  count(*) FILTER (WHERE note ILIKE '%Automated duplicate merge%') AS polluted_notes,
                  count(*) FILTER (WHERE note_extra IS NOT NULL) AS note_extra_used,
                  count(*) FILTER (WHERE note_extra_2 IS NOT NULL) AS note_extra_2_used,
                  count(*) FILTER (WHERE note ILIKE '%Origin village%') AS origin_village_notes
                FROM incidents
                WHERE is_deleted IS FALSE
                """
            )
        ).mappings().one()
        print(json.dumps(dict(rows), ensure_ascii=False, indent=2, default=str))

        sample = c.execute(
            text(
                """
                SELECT id::text, left(note, 400) AS note_preview
                FROM incidents
                WHERE is_deleted IS FALSE
                  AND note ILIKE '%Automated duplicate merge%'
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 3
                """
            )
        ).mappings().all()
        print("\nSample polluted notes:")
        for row in sample:
            print(json.dumps(dict(row), ensure_ascii=False, indent=2, default=str))

        updates = c.execute(
            text(
                """
                SELECT
                  count(*) AS pipeline_merge_rows,
                  count(*) FILTER (
                    WHERE new_values ? 'note'
                       OR old_values ? 'note'
                  ) AS merge_rows_with_note_field,
                  count(*) FILTER (
                    WHERE (new_values::text ILIKE '%raw_message_id%')
                       OR (old_values::text ILIKE '%raw_message_id%')
                  ) AS merge_rows_mentioning_raw_message_id,
                  count(*) FILTER (
                    WHERE (new_values::text ILIKE '%Automated duplicate%')
                       OR (old_values::text ILIKE '%Automated duplicate%')
                  ) AS merge_rows_with_automated_text
                FROM incident_updates
                WHERE action = 'pipeline_merge'
                """
            )
        ).mappings().one()
        print("\nincident_updates pipeline_merge coverage:")
        print(json.dumps(dict(updates), ensure_ascii=False, indent=2, default=str))

        update_sample = c.execute(
            text(
                """
                SELECT id, incident_id::text,
                       left(coalesce(old_values::text, ''), 200) AS old_preview,
                       left(coalesce(new_values::text, ''), 500) AS new_preview
                FROM incident_updates
                WHERE action = 'pipeline_merge'
                ORDER BY created_at DESC
                LIMIT 2
                """
            )
        ).mappings().all()
        print("\nSample pipeline_merge updates:")
        for row in update_sample:
            print(json.dumps(dict(row), ensure_ascii=False, indent=2, default=str))


def gender_pattern_probe() -> None:
    section("BUG 2 — definite-article / مصابة pattern probe")
    samples = [
        "الشهيدة إسراء",
        "شهيدة إسراء",
        "استشهاد الشهيدة إسراء",
        "الشهيد أحمد",
        "مصابة",
        "المصابة",
        "جريحة",
        "مصاب",
    ]
    for s in samples:
        matches = []
        for key, forms in _EXPLICIT_FORMS.items():
            for count, pat in forms:
                if pat.search(s):
                    matches.append(f"{key}@{count}")
        r = apply_explicit_arabic_gender_evidence(
            s, ExtractionCasualties(deaths=1, male_deaths=1)
        )
        print(
            f"text={s!r} matches={matches or ['NONE']} "
            f"after_apply male_d={r.male_deaths} female_d={r.female_deaths}"
        )


def _extract_gendered_hits(text: str) -> dict[str, bool]:
    return {
        "has_shahida": bool(re.search(r"شهيدة", text)),
        "has_shahid_masc": bool(re.search(r"(?<!ة)شهيد(?!ة|ات|ان|ين)", text)),
        "has_musaba_f": bool(re.search(r"مصابة|جريحة", text)),
        "has_musab_m": bool(re.search(r"مصاب(?!ة)|جريح(?!ة)", text)),
        "has_shahidat": bool(re.search(r"شهيدات", text)),
        "has_jarihat": bool(re.search(r"جريحات", text)),
    }


def bug2_sample() -> None:
    section("BUG 2 — backlog sample of gendered Arabic casualty language")
    with engine.connect() as c:
        # Prefer messages that already have extraction + materialized demographics
        rows = c.execute(
            text(
                """
                SELECT
                  rm.id AS raw_message_id,
                  left(rm.raw_text, 350) AS raw_preview,
                  rm.raw_text,
                  rm.extraction_result->'casualties' AS extraction_casualties,
                  i.id::text AS incident_id,
                  i.deaths, i.injuries,
                  d.male_d, d.female_d, d.male_i, d.female_i
                FROM raw_messages rm
                LEFT JOIN LATERAL (
                  SELECT inc.*
                  FROM incidents inc
                  WHERE inc.raw_message_id = rm.id
                    AND inc.is_deleted IS FALSE
                  ORDER BY inc.created_at DESC
                  LIMIT 1
                ) i ON TRUE
                LEFT JOIN incident_details d ON d.incident_id = i.id
                WHERE rm.raw_text ~ 'شهيدة|الشهيدة|مصابة|جريحة|شهيدات|جريحات|الشهيد|جريح|مصاب'
                  AND rm.extraction_result IS NOT NULL
                ORDER BY rm.id DESC
                LIMIT 40
                """
            )
        ).mappings().all()

        selected = []
        for row in rows:
            hits = _extract_gendered_hits(row["raw_text"] or "")
            # Prefer clearly gendered forms
            if not (
                hits["has_shahida"]
                or hits["has_musaba_f"]
                or hits["has_shahidat"]
                or hits["has_jarihat"]
                or hits["has_shahid_masc"]
                or hits["has_musab_m"]
            ):
                continue
            selected.append((row, hits))
            if len(selected) >= 12:
                break

        print(f"Pulled {len(selected)} candidate rows\n")
        correct = incorrect = ambiguous = no_demo = 0
        for row, hits in selected[:10]:
            cas = row["extraction_casualties"]
            if isinstance(cas, str):
                cas = json.loads(cas)
            expected_female = (
                hits["has_shahida"]
                or hits["has_musaba_f"]
                or hits["has_shahidat"]
                or hits["has_jarihat"]
            )
            expected_male = (
                hits["has_shahid_masc"] or hits["has_musab_m"]
            ) and not expected_female
            mixed = expected_female and (
                hits["has_shahid_masc"] or hits["has_musab_m"]
            )

            male_d = row["male_d"]
            female_d = row["female_d"]
            male_i = row["male_i"]
            female_i = row["female_i"]
            ext_male_d = (cas or {}).get("male_deaths") if cas else None
            ext_female_d = (cas or {}).get("female_deaths") if cas else None
            ext_male_i = (cas or {}).get("male_injuries") if cas else None
            ext_female_i = (cas or {}).get("female_injuries") if cas else None

            # Apply gender evidence ourselves to see if post-processor would fix
            simulated = None
            if cas:
                try:
                    simulated = apply_explicit_arabic_gender_evidence(
                        row["raw_text"] or "",
                        ExtractionCasualties.model_validate(cas),
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    simulated = {"error": str(exc)}

            verdict = "ambiguous"
            if mixed:
                verdict = "mixed_markers"
                ambiguous += 1
            elif expected_female:
                # Incorrect if male set and female null for death/injury context
                death_wrong = (
                    (hits["has_shahida"] or hits["has_shahidat"])
                    and (male_d or 0) > 0
                    and not (female_d or 0)
                ) or (
                    (hits["has_shahida"] or hits["has_shahidat"])
                    and (ext_male_d or 0) > 0
                    and not (ext_female_d or 0)
                )
                injury_wrong = (
                    (hits["has_musaba_f"] or hits["has_jarihat"])
                    and (male_i or 0) > 0
                    and not (female_i or 0)
                ) or (
                    (hits["has_musaba_f"] or hits["has_jarihat"])
                    and (ext_male_i or 0) > 0
                    and not (ext_female_i or 0)
                )
                death_right = (
                    (hits["has_shahida"] or hits["has_shahidat"])
                    and (female_d or ext_female_d or 0) > 0
                    and not (male_d or ext_male_d or 0)
                )
                injury_right = (
                    (hits["has_musaba_f"] or hits["has_jarihat"])
                    and (female_i or ext_female_i or 0) > 0
                    and not (male_i or ext_male_i or 0)
                )
                if death_wrong or injury_wrong:
                    verdict = "INCORRECT"
                    incorrect += 1
                elif death_right or injury_right:
                    verdict = "CORRECT"
                    correct += 1
                elif (
                    male_d is None
                    and female_d is None
                    and male_i is None
                    and female_i is None
                    and not any(
                        [
                            ext_male_d,
                            ext_female_d,
                            ext_male_i,
                            ext_female_i,
                        ]
                    )
                ):
                    verdict = "NO_DEMOGRAPHICS"
                    no_demo += 1
                else:
                    verdict = "partial_or_unclear"
                    ambiguous += 1
            elif expected_male:
                death_wrong = (
                    hits["has_shahid_masc"]
                    and (female_d or 0) > 0
                    and not (male_d or 0)
                )
                if death_wrong:
                    verdict = "INCORRECT"
                    incorrect += 1
                elif (male_d or ext_male_d or 0) > 0:
                    verdict = "CORRECT"
                    correct += 1
                elif (
                    male_d is None
                    and female_d is None
                    and not ext_male_d
                    and not ext_female_d
                ):
                    verdict = "NO_DEMOGRAPHICS"
                    no_demo += 1
                else:
                    verdict = "partial_or_unclear"
                    ambiguous += 1

            print("-" * 60)
            print(f"raw_message_id={row['raw_message_id']} verdict={verdict}")
            print(f"hits={hits}")
            print(f"raw_preview={row['raw_preview']!r}")
            print(f"extraction_casualties={json.dumps(cas, ensure_ascii=False)}")
            print(
                f"incident demographics male_d={male_d} female_d={female_d} "
                f"male_i={male_i} female_i={female_i}"
            )
            print(f"simulated_gender_evidence={json.dumps(simulated, ensure_ascii=False)}")

        print(
            f"\nSUMMARY n={min(10, len(selected))}: "
            f"correct={correct} incorrect={incorrect} "
            f"no_demo={no_demo} ambiguous={ambiguous}"
        )


VAGUE_RE = re.compile(
    r"عشرات|مئات|المئات|عدد\s+من|كثير\s+من|العديد\s+من|بضعة|عدة\s+(?:جرح|شهيد|مصاب|قتيل)"
)
DIGIT_RE = re.compile(r"[0-9٠-٩]+")


def _has_explicit_digit_near_casualty(text: str) -> bool:
    # crude: digit within 20 chars of casualty noun
    return bool(
        re.search(
            r"[0-9٠-٩]+\s*(?:جريح|جرحى|مصاب|شهيد|قتيل|إصاب|اصاب)",
            text,
        )
        or re.search(
            r"(?:جريح|جرحى|مصاب|شهيد|قتيل|إصاب|اصاب)\s*[0-9٠-٩]+",
            text,
        )
    )


def bug3_sample() -> None:
    section("BUG 3 — vague quantifier hallucination sample")
    with engine.connect() as c:
        rows = c.execute(
            text(
                """
                SELECT
                  rm.id AS raw_message_id,
                  left(rm.raw_text, 350) AS raw_preview,
                  rm.raw_text,
                  rm.extraction_result->'casualties' AS extraction_casualties,
                  i.id::text AS incident_id,
                  i.injuries, i.deaths, i.total_injuries, i.total_deaths,
                  d.children_i, d.children_d, d.male_i, d.female_i
                FROM raw_messages rm
                LEFT JOIN LATERAL (
                  SELECT inc.*
                  FROM incidents inc
                  WHERE inc.raw_message_id = rm.id
                    AND inc.is_deleted IS FALSE
                  ORDER BY inc.created_at DESC
                  LIMIT 1
                ) i ON TRUE
                LEFT JOIN incident_details d ON d.incident_id = i.id
                WHERE rm.raw_text ~ 'عشرات|مئات|المئات|عدد من|كثير من|العديد من|بضعة'
                  AND rm.raw_text ~ 'جرح|مصاب|شهيد|قتيل|إصاب|اصاب|ضحايا'
                  AND rm.extraction_result IS NOT NULL
                ORDER BY rm.id DESC
                LIMIT 50
                """
            )
        ).mappings().all()

        selected = []
        for row in rows:
            text_val = row["raw_text"] or ""
            if not VAGUE_RE.search(text_val):
                continue
            # Prefer vague-without-digit cases for hallucination check
            selected.append(row)
            if len(selected) >= 20:
                break

        print(f"Pulled {len(selected)} vague-casualty candidates\n")
        fabricated = correct_null = mixed = skipped = 0
        shown = 0
        for row in selected:
            text_val = row["raw_text"] or ""
            cas = row["extraction_casualties"]
            if isinstance(cas, str):
                cas = json.loads(cas)
            has_digit = _has_explicit_digit_near_casualty(text_val)
            vague_hits = VAGUE_RE.findall(text_val)

            numeric_fields = {}
            if cas:
                for k, v in cas.items():
                    if isinstance(v, int) and v > 0:
                        numeric_fields[k] = v
            incident_nums = {
                k: row[k]
                for k in (
                    "injuries",
                    "deaths",
                    "total_injuries",
                    "total_deaths",
                    "children_i",
                    "children_d",
                )
                if row[k] not in (None, 0)
            }

            # Fabrication: vague text, no explicit digit near casualty, but specific numbers filled
            if not has_digit and (numeric_fields or incident_nums):
                verdict = "FABRICATED_SPECIFIC"
                fabricated += 1
            elif not has_digit and not numeric_fields and not incident_nums:
                verdict = "CORRECT_NULL"
                correct_null += 1
            elif has_digit and (numeric_fields or incident_nums):
                # text has both vague and digits — numbers may be legitimate
                verdict = "HAS_EXPLICIT_DIGIT"
                mixed += 1
            else:
                verdict = "OTHER"
                skipped += 1

            if shown >= 15 and verdict == "HAS_EXPLICIT_DIGIT":
                continue
            if shown >= 15:
                continue
            shown += 1
            print("-" * 60)
            print(f"raw_message_id={row['raw_message_id']} verdict={verdict}")
            print(f"vague_hits={vague_hits} has_explicit_digit_near_casualty={has_digit}")
            print(f"raw_preview={row['raw_preview']!r}")
            print(f"extraction_casualties={json.dumps(cas, ensure_ascii=False)}")
            print(f"incident_nums={incident_nums}")

        print(
            f"\nSUMMARY scanned={len(selected)} shown={shown}: "
            f"fabricated={fabricated} correct_null={correct_null} "
            f"has_explicit_digit={mixed} other={skipped}"
        )

        # Broader counts without limiting print
        fabricated_all = correct_null_all = digit_all = other_all = 0
        for row in selected:
            text_val = row["raw_text"] or ""
            cas = row["extraction_casualties"]
            if isinstance(cas, str):
                cas = json.loads(cas)
            has_digit = _has_explicit_digit_near_casualty(text_val)
            numeric_fields = {
                k: v
                for k, v in (cas or {}).items()
                if isinstance(v, int) and v > 0
            }
            incident_nums = {
                k: row[k]
                for k in (
                    "injuries",
                    "deaths",
                    "total_injuries",
                    "total_deaths",
                    "children_i",
                    "children_d",
                )
                if row[k] not in (None, 0)
            }
            if not has_digit and (numeric_fields or incident_nums):
                fabricated_all += 1
            elif not has_digit and not numeric_fields and not incident_nums:
                correct_null_all += 1
            elif has_digit:
                digit_all += 1
            else:
                other_all += 1
        print(
            f"FULL SAMPLE SCOPE n={len(selected)}: "
            f"fabricated={fabricated_all} correct_null={correct_null_all} "
            f"has_explicit_digit={digit_all} other={other_all}"
        )


def evidence_span_check() -> None:
    section("BUG 3 — evidence_span usage for casualty counts")
    with engine.connect() as c:
        row = c.execute(
            text(
                """
                SELECT
                  count(*) FILTER (
                    WHERE extraction_result ? 'category_evidence'
                  ) AS with_category_evidence,
                  count(*) FILTER (
                    WHERE extraction_result::text ILIKE '%evidence_span%'
                  ) AS mention_evidence_span,
                  count(*) FILTER (
                    WHERE extraction_result->'casualties' ? 'evidence_span'
                       OR extraction_result->'casualties' ? 'injuries_evidence'
                  ) AS casualties_have_evidence_keys,
                  count(*) AS extracted_total
                FROM raw_messages
                WHERE extraction_result IS NOT NULL
                """
            )
        ).mappings().one()
        print(json.dumps(dict(row), ensure_ascii=False, indent=2, default=str))

        sample = c.execute(
            text(
                """
                SELECT id,
                       jsonb_object_keys_sample
                FROM (
                  SELECT id,
                         (
                           SELECT jsonb_agg(k)
                           FROM jsonb_object_keys(extraction_result) AS k
                         ) AS jsonb_object_keys_sample
                  FROM raw_messages
                  WHERE extraction_result IS NOT NULL
                  ORDER BY id DESC
                  LIMIT 1
                ) t
                """
            )
        ).mappings().one()
        print("Latest extraction_result top-level keys:", sample["jsonb_object_keys_sample"])


if __name__ == "__main__":
    bug1()
    gender_pattern_probe()
    bug2_sample()
    bug3_sample()
    evidence_span_check()
