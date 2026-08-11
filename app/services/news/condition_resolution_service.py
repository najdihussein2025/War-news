from app.core.text_normalization import normalize_english_text
from app.models.news import Condition


def resolve_condition(action_en: str, conditions: list[Condition]) -> Condition | None:
    normalized_action = normalize_english_text(action_en)
    for condition in conditions:
        if normalize_english_text(condition.action_en) == normalized_action:
            return condition
    return None
