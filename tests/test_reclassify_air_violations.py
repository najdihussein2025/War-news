import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "reclassify_air_violations.py"
    spec = importlib.util.spec_from_file_location("reclassify_air", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(row_id, condition_id, text):
    return (SimpleNamespace(id=row_id, condition_id=condition_id, khabar=text), text)


def test_dry_run_reports_changes_without_writing():
    mod = _load()
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        _row(1, 38, "مسيرة معادية تحلق فوق بنت جبيل"),
        _row(2, 38, "اباتشي تحلق فوق الناقورة"),
        _row(3, 38, "طائرة تحلق فوق صور"),
        _row(4, 36, "منطاد تجسسي فوق صور"),
    ]

    summary = mod.run(db, apply=False)

    assert dict(summary.changed) == {(38, 36): 1, (36, 34): 1}
    assert summary.unchanged == 1
    assert summary.needs_review == [3]
    db.commit.assert_not_called()
