#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev",
)

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])


def j(row) -> None:
    print(json.dumps(dict(row), ensure_ascii=False, default=str))


with engine.connect() as c:
    print("=== Israa / shahida incidents ===")
    rows = c.execute(
        text(
            """
            SELECT i.id::text, i.raw_message_id, left(i.khabar, 220) AS khabar,
                   i.deaths, i.total_deaths,
                   d.male_d, d.female_d, d.male_i, d.female_i
            FROM incidents i
            LEFT JOIN incident_details d ON d.incident_id = i.id
            WHERE i.is_deleted IS FALSE
              AND (
                i.khabar LIKE '%' || :a || '%'
                OR i.khabar LIKE '%' || :b || '%'
                OR i.raw_message_id = ANY(:ids)
              )
            ORDER BY i.created_at DESC
            """
        ),
        {"a": "إسراء", "b": "الشهيدة", "ids": [4016, 4018, 4037, 4066, 2502, 2414, 2413]},
    ).mappings().all()
    for r in rows:
        j(r)

    print("\n=== feminine marker + male demo without female ===")
    bad = c.execute(
        text(
            """
            SELECT rm.id, left(rm.raw_text, 200) AS preview,
                   rm.extraction_result->'casualties' AS cas,
                   d.male_d, d.female_d, d.male_i, d.female_i
            FROM raw_messages rm
            JOIN incidents i ON i.raw_message_id = rm.id AND i.is_deleted IS FALSE
            JOIN incident_details d ON d.incident_id = i.id
            WHERE rm.raw_text ~ 'الشهيدة|شهيدة|مصابة|جريحة|شهيدات|جريحات'
              AND (
                (COALESCE(d.male_d, 0) > 0 AND COALESCE(d.female_d, 0) = 0)
                OR (
                  COALESCE(d.male_i, 0) > 0 AND COALESCE(d.female_i, 0) = 0
                  AND rm.raw_text ~ 'مصابة|جريحة|جريحات'
                )
              )
            ORDER BY rm.id DESC
            LIMIT 20
            """
        )
    ).mappings().all()
    print("n=", len(bad))
    for r in bad:
        j(r)

    print("\n=== feminine marker + any gender demo filled ===")
    anydemo = c.execute(
        text(
            """
            SELECT rm.id, left(rm.raw_text, 180) AS preview,
                   rm.extraction_result->'casualties' AS cas,
                   d.male_d, d.female_d, d.male_i, d.female_i,
                   CASE
                     WHEN COALESCE(d.female_d, 0) > 0 OR COALESCE(d.female_i, 0) > 0 THEN 'HAS_FEMALE'
                     WHEN COALESCE(d.male_d, 0) > 0 OR COALESCE(d.male_i, 0) > 0 THEN 'MALE_ONLY'
                     ELSE 'NONE'
                   END AS gender_state
            FROM raw_messages rm
            JOIN incidents i ON i.raw_message_id = rm.id AND i.is_deleted IS FALSE
            JOIN incident_details d ON d.incident_id = i.id
            WHERE rm.raw_text ~ 'الشهيدة|(?<![ل])شهيدة|مصابة|جريحة|شهيدات|جريحات'
            ORDER BY rm.id DESC
            LIMIT 25
            """
        )
    ).mappings().all()
    from collections import Counter
    print("n=", len(anydemo), Counter(r["gender_state"] for r in anydemo))
    for r in anydemo:
        j(r)

    print("\n=== عشرات الجرحى all variants ===")
    dozens = c.execute(
        text(
            """
            SELECT rm.id, left(rm.raw_text, 160) AS preview,
                   rm.extraction_result->'casualties' AS cas,
                   i.injuries, i.total_injuries, d.children_i
            FROM raw_messages rm
            LEFT JOIN LATERAL (
              SELECT * FROM incidents
              WHERE raw_message_id = rm.id AND is_deleted IS FALSE
              ORDER BY created_at DESC LIMIT 1
            ) i ON TRUE
            LEFT JOIN incident_details d ON d.incident_id = i.id
            WHERE rm.raw_text LIKE '%' || :q || '%'
              AND rm.extraction_result IS NOT NULL
            ORDER BY rm.id DESC
            """
        ),
        {"q": "عشرات الجرحى"},
    ).mappings().all()
    print("n=", len(dozens))
    for r in dozens:
        j(r)
