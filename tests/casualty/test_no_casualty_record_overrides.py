from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def test_application_and_repair_have_no_record_specific_ids_or_override_labels():
    files = list((ROOT / "app").rglob("*.py")) + list((ROOT / "scripts" / "repair").rglob("*.py"))
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if UUID.search(text) or "reviewed proven case" in text.lower():
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
