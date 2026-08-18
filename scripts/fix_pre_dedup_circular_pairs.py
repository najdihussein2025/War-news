"""One-off repair for circular pre-dedup duplicate_of_id pairs.

Usage (review counts before applying):
    docker compose exec -e PYTHONPATH=/app backend python scripts/fix_pre_dedup_circular_pairs.py
    docker compose exec -e PYTHONPATH=/app backend python scripts/fix_pre_dedup_circular_pairs.py --apply
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from app.core.database import SessionLocal


FIND_CYCLES_SQL = """
SELECT
    LEAST(a.id, b.id) AS canonical_id,
    GREATEST(a.id, b.id) AS duplicate_id
FROM raw_messages a
JOIN raw_messages b
  ON a.duplicate_of_id = b.id
 AND b.duplicate_of_id = a.id
WHERE a.id < b.id
ORDER BY canonical_id;
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply fixes. Default is dry-run only.",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        pairs = session.execute(text(FIND_CYCLES_SQL)).all()
        print(f"circular_pairs_found={len(pairs)}")
        for canonical_id, duplicate_id in pairs:
            print(f"  canonical_id={canonical_id} duplicate_id={duplicate_id}")

        if not pairs:
            return

        if not args.apply:
            print("Dry run only. Re-run with --apply to fix rows.")
            return

        fixed = 0
        for canonical_id, duplicate_id in pairs:
            session.execute(
                text(
                    """
                    UPDATE raw_messages
                    SET duplicate_of_id = NULL,
                        status = 'parsed'
                    WHERE id = :canonical_id
                      AND duplicate_of_id = :duplicate_id
                    """
                ),
                {"canonical_id": canonical_id, "duplicate_id": duplicate_id},
            )
            session.execute(
                text(
                    """
                    UPDATE raw_messages
                    SET duplicate_of_id = :canonical_id,
                        status = 'duplicate'
                    WHERE id = :duplicate_id
                    """
                ),
                {"canonical_id": canonical_id, "duplicate_id": duplicate_id},
            )
            fixed += 1

        session.commit()
        print(f"fixed_pairs={fixed}")


if __name__ == "__main__":
    main()
