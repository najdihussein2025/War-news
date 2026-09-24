"""LLM fallback for borderline story-revision decisions.

Uses ``rules/story_revision_prompt.md`` (stage ``story_revision``). Only called
by ``StoryRelationshipService`` for sparse reports whose embedding similarity
falls in the borderline band, never on every message.
"""

from __future__ import annotations

import json

from app.core.config import settings
from app.core.llm_knowledge.prompt_assembly import build_stage_system_prompt
from app.core.ollama_client import OllamaChatClient, OllamaChatMessage
from app.llm.dtos import StoryRelationship, StoryRelationshipClassification


def parse_story_revision_response(raw: str) -> StoryRelationshipClassification:
    payload = json.loads(raw or "{}")
    hint = payload.get("relationship_hint") if isinstance(payload, dict) else None
    keywords = payload.get("matched_keywords") if isinstance(payload, dict) else None
    matched = tuple(str(item) for item in keywords or () if str(item).strip())
    if hint == "revision" and matched:
        return StoryRelationshipClassification(
            relationship=StoryRelationship.revision,
            relationship_evidence="story_revision LLM: " + ", ".join(matched),
            matched_keywords=matched,
        )
    # No marker, no revision: the prompt forbids inferring one from numbers.
    return StoryRelationshipClassification(
        relationship=StoryRelationship.unrelated,
        relationship_evidence="story_revision LLM: no revision marker",
    )


def build_story_revision_llm_classifier(client: OllamaChatClient | None = None):
    chat_client = client or OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.extraction_ollama_model,
        timeout_seconds=settings.extraction_llm_timeout_seconds,
        max_request_retries=settings.extraction_llm_request_retries,
        retry_backoff_seconds=settings.extraction_llm_retry_backoff_seconds,
    )

    def classify(current_text: str, candidate_text: str) -> StoryRelationshipClassification:
        system = build_stage_system_prompt("story_revision", current_text)
        user = (
            "Earlier bulletin (context only):\n"
            f"{candidate_text}\n\n"
            "New bulletin to classify:\n"
            f"{current_text}"
        )
        raw = chat_client.chat(
            [
                OllamaChatMessage(role="system", content=system),
                OllamaChatMessage(role="user", content=user),
            ],
            temperature=0.0,
        )
        return parse_story_revision_response(raw)

    return classify
