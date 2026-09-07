#!/usr/bin/env python
"""Tighter Phase 2 recon samples for Bugs 2 and 3."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

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
    apply_explicit_arabic_gender_evidence,
)

engine = create_engine(os.environ["DATABASE_URL"])


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def bug2_tight() -> None:
    print("=" * 72)
    print("BUG 2 tight sample — feminine grammatical markers")
    print("=" * 72)
    with engine.connect() as c:
        # Search الشهيدة / شهيدة / مصابة / جريحة / شهيدات / جريحات
        rows = c.execute(
            text(
                r"""
                SELECT
                  rm.id AS raw_message_id,
                  left(rm.raw_text, 420) AS raw_preview,
                  rm.raw_text,
                  rm.extraction_result->'casualties' AS extraction_casualties,
                  i.id::text AS incident_id,
                  d.male_d, d.female_d, d.male_i, d.female_i,
                  d.children_d, d.children_i
                FROM raw_messages rm
                LEFT JOIN LATERAL (
                  SELECT inc.id
                  FROM incidents inc
                  WHERE inc.raw_message_id = rm.id AND inc.is_deleted IS FALSE
                  ORDER BY inc.created_at DESC
                  LIMIT 1
                ) i ON TRUE
                LEFT JOIN incident_details d ON d.incident_id = i.id
                WHERE rm.raw_text ~ 'الشهيدة|شهيدة|مصابة|جريحة|شهيدات|جريحات|الشهيد[^ات]|شهيد[^ات]'
                  AND rm.extraction_result IS NOT NULL
                  AND (
                    rm.raw_text ~ 'الشهيدة|شهيدة|مصابة|جريحة|شهيدات|جريحات'
                    OR rm.raw_text ~ 'الشهيد[^ا]|[^ة]شهيد[^ات]'
                  )
                ORDER BY
                  CASE
                    WHEN rm.raw_text ~ 'الشهيدة|شهيدة' THEN 0
                    WHEN rm.raw_text ~ 'مصابة|جريحة|شهيدات|جريحات' THEN 1
                    ELSE 2
                  END,
                  rm.id DESC
                LIMIT 80
                """
            )
        ).mappings().all()

        feminine_rows = []
        masculine_singular = []
        for row in rows:
            t = row["raw_text"] or ""
            if re.search(r"الشهيدة|شهيدة|مصابة|جريحة|شهيدات|جريحات", t):
                feminine_rows.append(row)
            elif re.search(r"الشهيد(?![ات])|(?<![ةا])شهيد(?![اتانين])", t):
                # skip titles like "الشهيد علي شعيب" page headers if no casualty count context
                if re.search(r"(استشهاد|سقوط|سُقوط|سقط|أدى|ادى|حصيلة|غارة).{0,40}شهيد", t) or re.search(
                    r"شهيد.{0,30}(في|جراءاء|بلدة)", t
                ):
                    masculine_singular.append(row)

        print(f"feminine marker rows found in pull: {len(feminine_rows)}")
        print(f"masculine singular casualty-ish: {len(masculine_singular)}")

        def analyze(row, expected: str) -> str:
            cas = row["extraction_casualties"]
            if isinstance(cas, str):
                cas = json.loads(cas)
            text_val = row["raw_text"] or ""
            sim = apply_explicit_arabic_gender_evidence(
                text_val,
                ExtractionCasualties.model_validate(cas or {}),
            ).model_dump()

            male = row["male_d"] or (cas or {}).get("male_deaths")
            female = row["female_d"] or (cas or {}).get("female_deaths")
            male_i = row["male_i"] or (cas or {}).get("male_injuries")
            female_i = row["female_i"] or (cas or {}).get("female_injuries")

            # For feminine death markers
            if expected == "female_death":
                if (female or 0) > 0 and not (male or 0):
                    return "CORRECT"
                if (male or 0) > 0 and not (female or 0):
                    return "INCORRECT_MALE"
                if not male and not female:
                    return "MISSING_GENDER"
                return f"MIXED male={male} female={female}"
            if expected == "female_injury":
                if (female_i or 0) > 0 and not (male_i or 0):
                    return "CORRECT"
                if (male_i or 0) > 0 and not (female_i or 0):
                    return "INCORRECT_MALE"
                if not male_i and not female_i:
                    return "MISSING_GENDER"
                return f"MIXED male_i={male_i} female_i={female_i}"
            if expected == "male_death":
                if (male or 0) > 0 and not (female or 0):
                    return "CORRECT"
                if (female or 0) > 0 and not (male or 0):
                    return "INCORRECT_FEMALE"
                if not male and not female:
                    return "MISSING_GENDER"
                return f"MIXED male={male} female={female}"
            return "n/a"

        print("\n--- Feminine death/injury samples (up to 10) ---")
        counts = {"CORRECT": 0, "INCORRECT_MALE": 0, "MISSING_GENDER": 0, "OTHER": 0}
        shown = 0
        for row in feminine_rows:
            t = row["raw_text"] or ""
            if re.search(r"الشهيدة|شهيدة|شهيدات", t):
                expected = "female_death"
            elif re.search(r"مصابة|جريحة|جريحات", t):
                expected = "female_injury"
            else:
                continue
            # Skip if feminine word is only inside a longer mixed report with many people
            # Still include — but flag
            verdict = analyze(row, expected)
            key = verdict if verdict in counts else "OTHER"
            counts[key] = counts.get(key, 0) + 1
            if shown >= 10:
                continue
            shown += 1
            cas = row["extraction_casualties"]
            if isinstance(cas, str):
                cas = json.loads(cas)
            sim = apply_explicit_arabic_gender_evidence(
                t, ExtractionCasualties.model_validate(cas or {})
            ).model_dump()
            print("-" * 60)
            print(f"raw_message_id={row['raw_message_id']} expected={expected} verdict={verdict}")
            print(f"has_al_shahida={bool(re.search(r'الشهيدة', t))} has_bare_shahida={bool(re.search(r'(?<![ل])شهيدة', t))}")
            print(f"raw_preview={row['raw_preview']!r}")
            print(f"extraction={json.dumps(cas, ensure_ascii=False)}")
            print(
                f"detail male_d={row['male_d']} female_d={row['female_d']} "
                f"male_i={row['male_i']} female_i={row['female_i']}"
            )
            print(
                f"gender_evidence_would_set male_d={sim.get('male_deaths')} "
                f"female_d={sim.get('female_deaths')} male_i={sim.get('male_injuries')} "
                f"female_i={sim.get('female_injuries')}"
            )

        print(f"\nFeminine sample verdicts across {sum(counts.values())} rows: {counts}")

        # Explicit إسراء search
        print("\n--- إسراء / الشهيدة named search ---")
        named = c.execute(
            text(
                """
                SELECT rm.id, left(rm.raw_text, 500) AS preview,
                       rm.extraction_result->'casualties' AS cas,
                       d.male_d, d.female_d, d.male_i, d.female_i
                FROM raw_messages rm
                LEFT JOIN LATERAL (
                  SELECT id FROM incidents
                  WHERE raw_message_id = rm.id AND is_deleted IS FALSE
                  ORDER BY created_at DESC LIMIT 1
                ) i ON TRUE
                LEFT JOIN incident_details d ON d.incident_id = i.id
                WHERE rm.raw_text ILIKE '%إسراء%' OR rm.raw_text ILIKE '%الشهيدة%'
                ORDER BY rm.id DESC
                LIMIT 15
                """
            )
        ).mappings().all()
        for row in named:
            print("-" * 40)
            print(dump(dict(row)))


def bug3_tight() -> None:
    print("\n" + "=" * 72)
    print("BUG 3 tight sample — vague casualty quantifiers only")
    print("=" * 72)
    with engine.connect() as c:
        rows = c.execute(
            text(
                r"""
                SELECT
                  rm.id AS raw_message_id,
                  left(rm.raw_text, 420) AS raw_preview,
                  rm.raw_text,
                  rm.extraction_result->'casualties' AS extraction_casualties,
                  i.injuries, i.deaths, i.total_injuries, i.total_deaths,
                  d.children_i, d.children_d
                FROM raw_messages rm
                LEFT JOIN LATERAL (
                  SELECT *
                  FROM incidents inc
                  WHERE inc.raw_message_id = rm.id AND inc.is_deleted IS FALSE
                  ORDER BY inc.created_at DESC
                  LIMIT 1
                ) i ON TRUE
                LEFT JOIN incident_details d ON d.incident_id = i.id
                WHERE rm.extraction_result IS NOT NULL
                  AND (
                    rm.raw_text ~ 'عشرات\s+(الجرحى|الجرح|المصاب|الإصاب|الاصاب|الشهداء|القتلى|الضحايا)'
                    OR rm.raw_text ~ 'مئات\s+(الجرحى|المصاب|الإصاب|الاصاب|الشهداء|القتلى|الضحايا)'
                    OR rm.raw_text ~ 'عدد\s+من\s+(الجرحى|المصابين|الإصابات|الاصابات|الشهداء|القتلى|الضحايا|الجرح)'
                    OR rm.raw_text ~ 'كثير\s+من\s+(الجرحى|المصابين|الإصابات|الاصابات|الشهداء)'
                    OR rm.raw_text ~ 'العديد\s+من\s+(الجرحى|المصابين|الإصابات|الاصابات|الشهداء)'
                    OR rm.raw_text ~ 'بضعة\s+(جرحى|مصابين|شهداء)'
                  )
                ORDER BY rm.id DESC
                LIMIT 40
                """
            )
        ).mappings().all()

        print(f"Matched vague-casualty messages: {len(rows)}")
        fabricated = correct_null = mixed_digit = 0
        digit_near = re.compile(
            r"[0-9٠-٩]+\s*(?:جريح|جرحى|مصاب|شهيد|قتيل|إصاب|اصاب)|"
            r"(?:جريح|جرحى|مصاب|شهيد|قتيل|إصاب|اصاب)\s*[0-9٠-٩]+"
        )
        for i, row in enumerate(rows[:15]):
            t = row["raw_text"] or ""
            cas = row["extraction_casualties"]
            if isinstance(cas, str):
                cas = json.loads(cas)
            nums = {
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
            has_digit = bool(digit_near.search(t))
            if has_digit:
                verdict = "HAS_EXPLICIT_DIGIT"
                mixed_digit += 1
            elif nums or incident_nums:
                verdict = "FABRICATED"
                fabricated += 1
            else:
                verdict = "CORRECT_NULL"
                correct_null += 1
            print("-" * 60)
            print(f"[{i+1}] raw_message_id={row['raw_message_id']} verdict={verdict}")
            print(f"raw_preview={row['raw_preview']!r}")
            print(f"extraction={json.dumps(cas, ensure_ascii=False)}")
            print(f"incident_nums={incident_nums}")

        # recount all
        fabricated = correct_null = mixed_digit = 0
        for row in rows:
            t = row["raw_text"] or ""
            cas = row["extraction_casualties"]
            if isinstance(cas, str):
                cas = json.loads(cas)
            nums = {
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
            has_digit = bool(digit_near.search(t))
            if has_digit:
                mixed_digit += 1
            elif nums or incident_nums:
                fabricated += 1
            else:
                correct_null += 1
        print(
            f"\nSCOPE n={len(rows)}: fabricated={fabricated} "
            f"correct_null={correct_null} has_explicit_digit={mixed_digit}"
        )


def presence_evidence_persistence() -> None:
    print("\n" + "=" * 72)
    print("Where is category_evidence / evidence_span persisted?")
    print("=" * 72)
    with engine.connect() as c:
        # Check categories structure
        sample = c.execute(
            text(
                """
                SELECT id,
                       jsonb_typeof(extraction_result->'categories') AS cat_type,
                       left((extraction_result->'categories')::text, 400) AS cat_preview,
                       extraction_result ? 'category_evidence' AS has_top_evidence,
                       extraction_result->'presence_category_keys' AS presence_keys
                FROM raw_messages
                WHERE extraction_result IS NOT NULL
                  AND extraction_result->'categories' IS NOT NULL
                ORDER BY id DESC
                LIMIT 3
                """
            )
        ).mappings().all()
        for row in sample:
            print(dump(dict(row)))


if __name__ == "__main__":
    bug2_tight()
    bug3_tight()
    presence_evidence_persistence()
