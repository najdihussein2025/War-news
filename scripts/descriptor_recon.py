"""Offline or live-DB recon for village descriptor prefix candidates."""
from __future__ import annotations

import argparse
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

PROPOSED_STRIP = ["حرش", "خراج", "اطراف"]
PROPOSED_EXCLUDE = ["وادي", "مشاع", "ضهر", "مزارع"]


def _load_reference_villages(root: Path) -> tuple[set[str], Counter[str]]:
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

    return ref_names, all_village_tokens


def _load_offline_corpus(root: Path) -> list[str]:
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
    return texts


def _load_live_corpus(limit: int) -> list[str]:
    from sqlalchemy import text

    from app.core.database import SessionLocal

    texts: list[str] = []
    with SessionLocal() as session:
        rows = session.execute(
            text(
                """
                SELECT raw_text, extraction_result
                FROM raw_messages
                WHERE status = 'parsed'
                  AND extraction_result IS NOT NULL
                ORDER BY id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).all()
        for raw_text, extraction_result in rows:
            extraction = extraction_result or {}
            village = extraction.get("village")
            if isinstance(village, list):
                texts.extend(str(item) for item in village if item)
            elif village:
                texts.append(str(village))
            if raw_text:
                texts.append(str(raw_text))
    return texts


def _analyze_phrases(texts: list[str]) -> dict[str, list[str]]:
    phrase_hits: dict[str, list[str]] = defaultdict(list)
    for text in texts:
        normalized = normalize_arabic_text(text)
        for seed in SEED_WORDS:
            if seed not in normalized:
                continue
            pattern = rf"(?:^|\s)({re.escape(seed)}(?:\s+[\u0600-\u06FFa-zA-Z0-9]+){{1,4}})"
            for match in re.finditer(pattern, normalized):
                phrase_hits[seed].append(match.group(1).strip())
    return phrase_hits


def _build_report(
    *,
    mode: str,
    ref_names: set[str],
    all_village_tokens: Counter[str],
    texts: list[str],
    phrase_hits: dict[str, list[str]],
) -> list[str]:
    lines: list[str] = [
        f"=== DESCRIPTOR CANDIDATE RECON ({mode}) ===",
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
                hits = [
                    name
                    for name in ref_names
                    if remainder in name or name in remainder
                ][:3]
                lines.append(f"      remainder after strip: {remainder!r} -> {hits}")
        lines.append(f"  RECOMMENDATION: {recommendation}")
        lines.append("")

    lines.extend(
        [
            "=== PROPOSED STRIP-LIST (pending your confirmation) ===",
            ", ".join(confirmed),
            "",
            "=== PRIOR OFFLINE PROPOSAL ===",
            f"strip: {', '.join(PROPOSED_STRIP)}",
            f"exclude (village-name prefix): {', '.join(PROPOSED_EXCLUDE)}",
            "",
            "=== DELTA VS PRIOR PROPOSAL ===",
        ]
    )

    confirmed_set = set(confirmed)
    strip_added = sorted(confirmed_set - set(PROPOSED_STRIP))
    strip_removed = sorted(set(PROPOSED_STRIP) - confirmed_set)
    exclude_now_high = sorted(
        seed
        for seed in PROPOSED_EXCLUDE
        if any(name.startswith(seed + " ") for name in ref_names)
    )
    lines.append(f"  strip-list additions: {strip_added or '(none)'}")
    lines.append(f"  strip-list removals: {strip_removed or '(none)'}")
    lines.append(
        "  prior exclude-list words that ARE registered village prefixes: "
        f"{exclude_now_high or '(none)'}"
    )
    lines.extend(
        [
            "",
            "=== KNOWN CASE: حرش عيتا الجبل ===",
        ]
    )
    for name in sorted(ref_names):
        if "عيتا الجبل" in name:
            lines.append(f"  ref_name match: {name}")

    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Scan parsed raw_messages with extraction_result from DATABASE_URL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Max raw_messages rows to scan in --live mode (default: 5000).",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ref_names, all_village_tokens = _load_reference_villages(root)

    if args.live:
        texts = _load_live_corpus(args.limit)
        mode = "live DB"
        output = root / "DESCRIPTOR_RECON_LIVE.md"
    else:
        texts = _load_offline_corpus(root)
        mode = "offline"
        output = root / "DESCRIPTOR_RECON.md"

    phrase_hits = _analyze_phrases(texts)
    lines = _build_report(
        mode=mode,
        ref_names=ref_names,
        all_village_tokens=all_village_tokens,
        texts=texts,
        phrase_hits=phrase_hits,
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
