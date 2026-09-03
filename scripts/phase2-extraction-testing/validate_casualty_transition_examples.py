"""Validate casualty_transitions golden examples (schema parse, no live LLM)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_casualty_transition_extraction import GOLDEN_EXAMPLES  # noqa: E402
from app.llm.services.ollama_extraction_service import _RawExtractionResponse  # noqa: E402


def main() -> int:
    parsed = 0
    for example in GOLDEN_EXAMPLES:
        response = _RawExtractionResponse.model_validate(example["payload"])
        if len(response.casualty_transitions) != example["expect_transition_count"]:
            print(
                f"FAIL {example['label']}: expected "
                f"{example['expect_transition_count']} transitions, "
                f"got {len(response.casualty_transitions)}"
            )
            return 1
        parsed += 1
    report = {
        "before_transitions_field_supported": 0,
        "after_golden_examples_parsed": parsed,
        "golden_example_count": len(GOLDEN_EXAMPLES),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
