from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.ollama_client import OllamaChatClient
from app.llm.services.ollama_presence_gate_service import OllamaPresenceGateService


SAMPLES = [
    {
        "label": "ambiguous_hospital_nearby",
        "expected": "no hospital",
        "text": "أفادت الوكالة الوطنية بأن غارة استهدفت سيارة على الطريق قرب مستشفى تبنين الحكومي من دون تسجيل إصابات داخل المستشفى.",
    },
    {
        "label": "clear_hospital_hit",
        "expected": "hospital",
        "text": "استهدفت غارة إسرائيلية مستشفى ميس الجبل الحكومي ما أدى إلى أضرار في قسم الطوارئ وإصابة ممرض.",
    },
    {
        "label": "ambiguous_cemetery_nearby",
        "expected": "no religious_cultural",
        "text": "وقع إطلاق نار قرب المقبرة في بلدة عيترون، ولم تسجل أضرار في المقبرة أو في أي موقع ديني.",
    },
    {
        "label": "clear_road_blocked",
        "expected": "road_bridge",
        "text": "سقطت قذيفة على الطريق العام بين كفركلا والعديسة ما أدى إلى قطع الطريق وتعذر مرور السيارات.",
    },
    {
        "label": "clear_press_casualty",
        "expected": "press",
        "text": "أصيب مصور صحافي أثناء تغطيته القصف على أطراف بلدة الخيام.",
    },
    {
        "label": "context_army_escort",
        "expected": "no lebanese_army",
        "text": "نقل الصليب الأحمر الجريح إلى المستشفى بمواكبة الجيش اللبناني بعد الغارة على بلدة حولا.",
    },
    {
        "label": "clear_warning",
        "expected": "warning_classification",
        "text": "صدر تحذير عاجل إلى أهالي الناقورة بضرورة إخلاء المنطقة فوراً بسبب تهديدات بقصف قريب.",
    },
    {
        "label": "no_specific_category",
        "expected": "none",
        "text": "شن الطيران الحربي غارة على أطراف بلدة عيتا الشعب من دون الإشارة إلى منشآت أو فئات محددة متضررة.",
    },
]


def _build_service() -> OllamaPresenceGateService:
    client = OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.extraction_ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    return OllamaPresenceGateService(client)


def main() -> None:
    service = _build_service()
    print(f"Ollama model: {settings.extraction_ollama_model}")
    print(f"Ollama base URL: {settings.ollama_base_url}")
    print()

    for index, sample in enumerate(SAMPLES, start=1):
        started_at = time.perf_counter()
        result = service.evaluate(sample["text"], raw_message_id=index)
        payload = {
            "categories_present": [
                category.value for category in result.categories_present
            ],
            "category_evidence": [
                evidence.model_dump(mode="json")
                for evidence in result.category_evidence
            ],
        }
        print(f"=== {index}. {sample['label']} ===")
        print(f"expected: {sample['expected']}")
        print(f"text: {sample['text']}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"elapsed_seconds: {time.perf_counter() - started_at:.2f}")
        print()


if __name__ == "__main__":
    main()
