"""Offline recon for village descriptor prefix candidates."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from app.core.text_normalization import normalize_arabic_text

SEED_WORDS = [
    "حرش",
    "خراج",
    "جرود",
    "وادي",
    "اطراف",
    "أطراف",
    "محيط",
    "ضهر",
    "مزارع",
    "دوحة",
    "مشاع",
    "قرب",
    "بالقرب",
    "بجوار",
    "بجانب",
    "محاذاة",
    "امام",
    "أمام",
    "جنوب",
    "شمال",
    "شرق",
    "غرب",
    "تلة",
    "تل",
    "سهل",
    "جبل",
    "ساحل",
    "خارج",
    "ضاحية",
    "حارة",
    "حي",
    "جبانة",
]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    villages = json.loads((root / "Data/Villages.json").read_text(encoding="utf-8"))
    ref_names: set[str] = set()
    all_village_tokens: Counter[str] = Counter()

    for village in villages:
        for field in ("ref_name_ar", "acs_name"):
            name = village.get(field)
            if not name:
                continue
            normalized = normalize_arabic_text(str(name))
            ref_names.add(normalized)
            for token in normalized.split():
                all_village_tokens[token] += 1

    texts: list[str] = []
    answer_key = json.loads(
        (root / "scripts/phase2-extraction-testing/answer_key.json").read_text(
            encoding="utf-8"
        )
    )
    for item in answer_key:
        if item.get("khabar_text"):
            texts.append(item["khabar_text"])
        expected = item.get("expected") or {}
        if expected.get("village"):
            texts.append(str(expected["village"]))

    for path in (root / "scripts/phase2-extraction-testing/sample_texts").glob("*.txt"):
        texts.append(path.read_text(encoding="utf-8"))

    phrase_hits: dict[str, list[str]] = defaultdict(list)
    for text in texts:
        normalized = normalize_arabic_text(text)
        for seed in SEED_WORDS:
            if seed not in normalized:
                continue
            pattern = rf"(?:^|\s)({re.escape(seed)}(?:\s+[\u0600-\u06FFa-zA-Z0-9]+){{1,4}})"
            for match in re.finditer(pattern, normalized):
                phrase_hits[seed].append(match.group(1).strip())

    lines: list[str] = [
        "=== DESCRIPTOR CANDIDATE RECON (offline) ===",
        f"Reference villages loaded: {len(ref_names)}",
        f"Corpus texts scanned: {len(texts)}",
        "",
    ]

    confirmed: list[str] = []
    for seed in SEED_WORDS:
        examples = phrase_hits.get(seed)
        if not examples:
            continue

        unique_examples = list(dict.fromkeys(examples))[:8]
        villages_starting = [name for name in ref_names if name.startswith(seed + " ")]
        token_in_any_village = all_village_tokens.get(seed, 0)
        distinct_phrases = len(set(examples))

        if villages_starting:
            risk = "HIGH"
            recommendation = "DO NOT STRIP — registered village names start with this word"
        elif token_in_any_village > 20:
            risk = "MEDIUM"
            recommendation = "NEEDS REVIEW — token appears inside many village names"
        elif distinct_phrases >= 1:
            risk = "LOW"
            recommendation = "CONFIRMED STRIP CANDIDATE"
            confirmed.append(seed)
        else:
            risk = "LOW"
            recommendation = "NEEDS REVIEW"

        lines.extend(
            [
                f"WORD: {seed}",
                f"  distinct prefixed phrases in corpus: {distinct_phrases}",
                f"  villages whose ref_name STARTS with this word: {len(villages_starting)}",
            ]
        )
        if villages_starting[:3]:
            lines.append(f"    examples: {villages_starting[:3]}")
        lines.append(f"  token count inside any village name: {token_in_any_village}")
        lines.append(f"  strip risk: {risk}")
        lines.append("  example phrases:")
        for example in unique_examples:
            lines.append(f"    - {example}")
            remainder = example[len(seed) :].strip()
            if remainder:
                hits = [name for name in ref_names if remainder in name or name in remainder][:3]
                lines.append(f"      remainder after strip: {remainder!r} -> {hits}")
        lines.append(f"  RECOMMENDATION: {recommendation}")
        lines.append("")

    lines.extend(
        [
            "=== PROPOSED STRIP-LIST (pending your confirmation) ===",
            ", ".join(confirmed),
            "",
            "=== KNOWN CASE: حرش عيتا الجبل ===",
        ]
    )
    for name in sorted(ref_names):
        if "عيتا الجبل" in name:
            lines.append(f"  ref_name match: {name}")

    output = root / "DESCRIPTOR_RECON.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
