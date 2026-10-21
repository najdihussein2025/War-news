import itertools

import pytest
from sqlalchemy import text

from app.analytics.services.status_buckets import bucket_sql, decide_bucket

STATUSES = ["verified", "auto_processed", "needs_verification", "rejected", "something_else"]


@pytest.mark.parametrize("status,deleted,counts", list(itertools.product(STATUSES, [False, True], [True, False])))
def test_truth_table(status, deleted, counts):
    expected = decide_bucket(status, deleted, counts)
    if deleted or status == "rejected":
        assert expected is None
    elif status == "needs_verification" or not counts:
        assert expected == "pending"
    elif status in ("verified", "auto_processed"):
        assert expected == "counted"
    else:
        assert expected == "pending"


def test_sql_matches_python(engine):
    case = bucket_sql("s", "d", "c")
    with engine.connect() as conn:
        for status, deleted, counts in itertools.product(STATUSES, [False, True], [True, False]):
            got = conn.execute(
                text(f"SELECT {case} FROM (SELECT CAST(:s AS text) s, CAST(:d AS boolean) d, CAST(:c AS boolean) c) t"),
                {"s": status, "d": deleted, "c": counts},
            ).scalar()
            assert got == decide_bucket(status, deleted, counts), (status, deleted, counts)
