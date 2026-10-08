"""Golden-fixture labeling helper: no DB, reads/writes the fixture files only."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import summary_label_helper as helper

CASE = {
    "message_id": 999001,
    "channel": "test",
    "raw_text": "ملخص الاعتداءات\nالقصف المدفعي :\n• الخيام\n",
    "posted_at": "2026-10-08 12:00:00+00:00",
    "expected": {},
    "reviewer_notes": "",
}


@pytest.fixture
def isolated_fixtures(tmp_path, monkeypatch):
    pending = tmp_path / "pending"
    approved = tmp_path / "approved"
    pending.mkdir()
    approved.mkdir()
    monkeypatch.setattr(helper, "PENDING_DIR", pending)
    monkeypatch.setattr(helper, "APPROVED_DIR", approved)
    path = pending / "999001.json"
    path.write_text(json.dumps(CASE, ensure_ascii=False), encoding="utf-8")
    return pending, approved, path


def test_proposed_expected_has_the_golden_fixture_shape():
    proposal = helper.proposed_expected(CASE["raw_text"], datetime(2026, 10, 8, 12, tzinfo=timezone.utc))
    assert set(proposal) == {"window", "items", "residual", "disposition", "leftover_tokens", "out_of_scope_lines", "auto_acceptable"}
    assert proposal["items"][0]["primary"] == "الخيام" and proposal["items"][0]["condition_id"] == 5


def test_list_pending_reads_the_directory(isolated_fixtures):
    pending, _approved, _path = isolated_fixtures
    rows = helper.list_pending()
    assert [row["message_id"] for row in rows] == [999001]


def test_show_writes_a_pending_review_proposal(isolated_fixtures, capsys):
    _pending, _approved, path = isolated_fixtures
    helper.show(999001)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "pending_review" and saved["expected"]["items"]
    assert "Wrote the parser's current proposal" in capsys.readouterr().out


def test_approve_moves_the_file_and_sets_status(isolated_fixtures):
    pending, approved, path = isolated_fixtures
    helper.show(999001)
    helper.approve(999001)
    assert not path.exists()
    moved = json.loads((approved / "999001.json").read_text(encoding="utf-8"))
    assert moved["status"] == "approved" and moved["expected"]["items"]


def test_missing_fixture_raises():
    with pytest.raises(FileNotFoundError):
        helper._fixture_path(123456789)
