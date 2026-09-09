from types import SimpleNamespace

from scripts.review.backfill_incident_khabar_embedding import (
    MATCHED_SQL,
    SKIPPED_SQL,
    UPDATE_SQL,
    backfill_incident_embeddings,
)


class _BackfillSession:
    def __init__(self) -> None:
        self.rows = [
            {
                "is_deleted": False,
                "incident_embedding": None,
                "raw_embedding": [0.1, 0.2, 0.3],
            },
            {
                "is_deleted": False,
                "incident_embedding": None,
                "raw_embedding": None,
            },
            {
                "is_deleted": True,
                "incident_embedding": None,
                "raw_embedding": [0.4, 0.5, 0.6],
            },
            {
                "is_deleted": False,
                "incident_embedding": [0.7, 0.8, 0.9],
                "raw_embedding": [0.9, 0.8, 0.7],
            },
        ]
        self.commit_calls = 0

    def scalar(self, statement):
        if statement is MATCHED_SQL:
            return sum(
                not row["is_deleted"]
                and row["incident_embedding"] is None
                and row["raw_embedding"] is not None
                for row in self.rows
            )
        if statement is SKIPPED_SQL:
            return sum(
                not row["is_deleted"]
                and row["incident_embedding"] is None
                and row["raw_embedding"] is None
                for row in self.rows
            )
        raise AssertionError("Unexpected scalar statement")

    def execute(self, statement):
        assert statement is UPDATE_SQL
        updated = 0
        for row in self.rows:
            if (
                not row["is_deleted"]
                and row["incident_embedding"] is None
                and row["raw_embedding"] is not None
            ):
                row["incident_embedding"] = row["raw_embedding"]
                updated += 1
        return SimpleNamespace(rowcount=updated)

    def commit(self) -> None:
        self.commit_calls += 1


def test_backfill_copies_available_embedding_and_skips_missing() -> None:
    db = _BackfillSession()

    stats = backfill_incident_embeddings(db)  # type: ignore[arg-type]

    assert stats.matched == 1
    assert stats.updated == 1
    assert stats.skipped_missing_raw_embedding == 1
    assert db.rows[0]["incident_embedding"] == [0.1, 0.2, 0.3]
    assert db.rows[1]["incident_embedding"] is None
    assert db.rows[2]["incident_embedding"] is None
    assert db.rows[3]["incident_embedding"] == [0.7, 0.8, 0.9]
    assert db.commit_calls == 1
