import json
import math
from collections import Counter, defaultdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ANSWER_KEY_PATH = SCRIPT_DIR / "answer_key.json"
RESULTS_PATH = SCRIPT_DIR / "extraction_results.json"
REPORT_PATH = SCRIPT_DIR / "scoring_report.md"

DID_KEYS = {"did", "direct_indirect", "DID", "d_id"}
CASUALTY_KEY_MAP = {
    "Total_D": "total_deaths",
    "Total_Inj": "total_injuries",
    "Death": "deaths",
    "Injuries": "injuries",
    "Male_D": "male_deaths",
    "Male_I": "male_injuries",
    "female_D": "female_deaths",
    "female_I": "female_injuries",
    "Children_D": "children_deaths",
    "Children_I": "children_injuries",
    "LA_TD": "deaths",
    "LA_TI": "injuries",
    "UN_TD": "deaths",
    "UN_TI": "injuries",
    "MUNI_TD": "deaths",
    "MUNI_TI": "injuries",
    "HosD": "deaths",
    "HosI": "injuries",
    "HCD": "deaths",
    "HCI": "injuries",
    "Emer_D": "deaths",
    "Emer_I": "injuries",
    "PressD": "deaths",
    "PressI": "injuries",
    "GBD": "deaths",
    "GBI": "injuries",
    "CarD": "deaths",
    "CarI": "injuries",
    "Moto_D": "deaths",
    "Moto_I": "injuries",
    "Con_D": "deaths",
    "Con_I": "injuries",
    "Other_D": "deaths",
    "Other_I": "injuries",
}


def load_json(path):
    if not path.exists():
        if path == RESULTS_PATH:
            return []
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def as_dict(value):
    return value if isinstance(value, dict) else {}


def numeric(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not math.isnan(float(value)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def expected_categories(sample):
    return set(as_dict(as_dict(sample.get("expected")).get("categories")).keys())


def model_categories(result):
    parsed = result.get("parsed_json_or_null")
    parsed = as_dict(parsed)
    if parsed.get("is_relevant") is False:
        return set()
    return set(as_dict(parsed.get("categories")).keys())


def find_expected_did(category_payload):
    fields = as_dict(category_payload.get("fields"))
    for key, value in fields.items():
        if key.lower().endswith(("did", "d_id")) and isinstance(value, str) and value in {"D", "ID"}:
            return value
    return None


def find_model_did(category_payload):
    if not isinstance(category_payload, dict):
        return None
    for key in DID_KEYS:
        value = category_payload.get(key)
        if isinstance(value, str) and value.upper() in {"D", "ID"}:
            return value.upper()
    return None


def expected_casualties_from_fields(fields):
    output = {}
    for key, value in as_dict(fields).items():
        mapped = CASUALTY_KEY_MAP.get(key)
        number = numeric(value)
        if mapped and number is not None:
            output[mapped] = max(output.get(mapped, 0), number)
    return output


def compare_casualties(expected, actual):
    exact = 0
    close = 0
    mismatches = []
    actual = as_dict(actual)
    for key, expected_value in expected.items():
        actual_value = numeric(actual.get(key))
        if actual_value is None:
            mismatches.append(f"{key}: expected {expected_value:g}, got missing")
            continue
        if actual_value == expected_value:
            exact += 1
        elif abs(actual_value - expected_value) <= 1:
            close += 1
            mismatches.append(f"{key}: expected {expected_value:g}, got {actual_value:g} (close)")
        else:
            mismatches.append(f"{key}: expected {expected_value:g}, got {actual_value:g}")
    return exact, close, mismatches


def main():
    answer_key = load_json(ANSWER_KEY_PATH)
    results = load_json(RESULTS_PATH)
    answers_by_id = {str(item["sample_id"]): item for item in answer_key}
    results_by_id = {str(item["sample_id"]): item for item in results}
    common_ids = sorted(set(answers_by_id) & set(results_by_id), key=lambda value: int(value) if value.isdigit() else value)

    valid_json = 0
    category_truth_counts = Counter()
    category_stats = defaultdict(Counter)
    did_stats = Counter()
    casualty_stats = Counter()
    worst_samples = []

    for sample in answer_key:
        category_truth_counts.update(expected_categories(sample))

    for sample_id in common_ids:
        expected = answers_by_id[sample_id]
        result = results_by_id[sample_id]
        parsed = as_dict(result.get("parsed_json_or_null"))
        if parsed:
            valid_json += 1

        exp_categories = expected_categories(expected)
        got_categories = model_categories(result)
        correct = exp_categories & got_categories
        missed = exp_categories - got_categories
        false_added = got_categories - exp_categories

        for category in correct:
            category_stats[category]["correct"] += 1
        for category in missed:
            category_stats[category]["missed"] += 1
        for category in false_added:
            category_stats[category]["false_added"] += 1

        did_mismatches = []
        casualty_mismatches = []
        expected_payloads = as_dict(as_dict(expected.get("expected")).get("categories"))
        model_payloads = as_dict(parsed.get("categories"))
        for category in correct:
            expected_did = find_expected_did(as_dict(expected_payloads.get(category)))
            model_did = find_model_did(model_payloads.get(category))
            if expected_did:
                if expected_did == model_did:
                    did_stats["match"] += 1
                else:
                    did_stats["mismatch"] += 1
                    did_mismatches.append(f"{category}: expected DID {expected_did}, got {model_did}")

            expected_casualties = expected_casualties_from_fields(as_dict(as_dict(expected_payloads.get(category)).get("fields")))
            exact, close, mismatches = compare_casualties(expected_casualties, as_dict(model_payloads.get(category)).get("casualties"))
            casualty_stats["exact"] += exact
            casualty_stats["close"] += close
            casualty_stats["mismatch"] += len([item for item in mismatches if "(close)" not in item])
            casualty_mismatches.extend(f"{category}: {item}" for item in mismatches)

        top_level_expected_casualties = {}
        for key, value in as_dict(as_dict(expected.get("expected")).get("casualties")).items():
            mapped = CASUALTY_KEY_MAP.get(key)
            number = numeric(value)
            if mapped and number is not None:
                top_level_expected_casualties[mapped] = number
        exact, close, mismatches = compare_casualties(top_level_expected_casualties, parsed.get("casualties"))
        casualty_stats["exact"] += exact
        casualty_stats["close"] += close
        casualty_stats["mismatch"] += len([item for item in mismatches if "(close)" not in item])
        casualty_mismatches.extend(f"overall: {item}" for item in mismatches)

        issue_score = len(missed) * 3 + len(false_added) * 2 + len(did_mismatches) + len(casualty_mismatches) + (0 if parsed else 5)
        if issue_score:
            worst_samples.append(
                {
                    "sample_id": sample_id,
                    "score": issue_score,
                    "expected_categories": sorted(exp_categories),
                    "returned_categories": sorted(got_categories),
                    "missed": sorted(missed),
                    "false_added": sorted(false_added),
                    "did_mismatches": did_mismatches,
                    "casualty_mismatches": casualty_mismatches[:8],
                    "valid_json": bool(parsed),
                }
            )

    lines = []
    lines.append("# Phase 2 Step B Extraction Scoring Report")
    lines.append("")
    lines.append(f"- Samples in answer key: {len(answer_key)}")
    lines.append(f"- Model results loaded: {len(results)}")
    lines.append(f"- Comparable samples: {len(common_ids)}")
    valid_pct = (valid_json / len(common_ids) * 100) if common_ids else 0
    lines.append(f"- Valid JSON outputs: {valid_json}/{len(common_ids)} ({valid_pct:.1f}%)")
    lines.append(f"- DID matches: {did_stats['match']}")
    lines.append(f"- DID mismatches: {did_stats['mismatch']}")
    lines.append(f"- Casualty exact matches: {casualty_stats['exact']}")
    lines.append(f"- Casualty close-but-not-exact matches: {casualty_stats['close']}")
    lines.append(f"- Casualty mismatches/missing: {casualty_stats['mismatch']}")
    lines.append("")
    lines.append("## Per-Category Detection")
    lines.append("")
    lines.append("| Category | Examples | Correct | Missed | False added | Precision | Recall |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for category, examples in sorted(category_truth_counts.items()):
        if examples < 3:
            continue
        stats = category_stats[category]
        correct = stats["correct"]
        missed = stats["missed"]
        false_added = stats["false_added"]
        precision = correct / (correct + false_added) if (correct + false_added) else 0
        recall = correct / (correct + missed) if (correct + missed) else 0
        lines.append(f"| {category} | {examples} | {correct} | {missed} | {false_added} | {precision:.2f} | {recall:.2f} |")

    lines.append("")
    lines.append("## Worst Samples")
    lines.append("")
    for item in sorted(worst_samples, key=lambda row: row["score"], reverse=True)[:15]:
        lines.append(f"### Sample {item['sample_id']}")
        lines.append(f"- Valid JSON: {item['valid_json']}")
        lines.append(f"- Expected categories: {', '.join(item['expected_categories']) or '(none)'}")
        lines.append(f"- Returned categories: {', '.join(item['returned_categories']) or '(none)'}")
        if item["missed"]:
            lines.append(f"- Missed: {', '.join(item['missed'])}")
        if item["false_added"]:
            lines.append(f"- False added: {', '.join(item['false_added'])}")
        if item["did_mismatches"]:
            lines.append(f"- DID mismatches: {'; '.join(item['did_mismatches'])}")
        if item["casualty_mismatches"]:
            lines.append(f"- Casualty mismatches: {'; '.join(item['casualty_mismatches'])}")
        lines.append("")

    report = "\n".join(lines).rstrip() + "\n"
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report written to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
