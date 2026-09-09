"""Run the real Tier-1 model against a five-village casualty bulletin."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings
from app.core.ollama_client import OllamaChatClient
from app.llm.services.ollama_extraction_service import OllamaExtractionService


BULLETIN = """الرمادية قضاء صور: شهيد و15 جريحا
كفرمان قضاء النبطية: شهيدان
النبطية الفوقا: 3 جرحى من بينهم سيدة
ميفدون قضاء النبطية: 4 جرحى
عين التينة: جريح سوري الجنسية"""

EXPECTED = {
    "الرمادية": (1, 15),
    "كفرمان": (2, None),
    "النبطية الفوقا": (None, 3),
    "ميفدون": (None, 4),
    "عين التينة": (None, 1),
}


def main() -> int:
    summary = {"processed": 1, "succeeded": 0, "failed": 0}
    client = OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.extraction_ollama_model,
        timeout_seconds=settings.extraction_llm_timeout_seconds,
        max_request_retries=settings.extraction_llm_request_retries,
        retry_backoff_seconds=settings.extraction_llm_retry_backoff_seconds,
    )
    try:
        result = OllamaExtractionService(client).extract_tier1(BULLETIN)
        actual = {
            entry.village: (entry.deaths, entry.injuries)
            for entry in result.village_roles
            if entry.role.value == "target"
        }
        print(
            json.dumps(
                {
                    "model": result.model,
                    "village_roles": [
                        entry.model_dump(mode="json")
                        for entry in result.village_roles
                    ],
                    "message_casualties": result.casualties.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if actual != EXPECTED:
            raise AssertionError(f"expected={EXPECTED!r}, actual={actual!r}")
        summary["succeeded"] = 1
    except Exception as exc:
        summary["failed"] = 1
        print(f"validation_error={type(exc).__name__}: {exc}")

    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
