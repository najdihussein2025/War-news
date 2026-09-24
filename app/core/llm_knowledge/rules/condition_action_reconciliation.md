# Condition/action reconciliation

When extracting conflict incidents, preserve the most specific action phrase
grounded in the bulletin text. The action text and evidence span drive the
primary condition candidate.

Source-provided event metadata, such as CNRS `event_subtype`, is a secondary
hint. It must not overwrite a specific text-grounded action such as `تمشيط`,
`قنابل مضيئة`, tank fire, warning raid, or feigned raid.

If the bulletin contains multiple village-local actions, emit scoped
`sub_events` so each village is matched against its own action. Use root
`action_description` only as a fallback summary when the message has one
condition.

If the action cannot be identified from the bulletin text, leave the extracted
action empty rather than rounding to a generic bucket. The matching layer may
use source metadata as a review-required fallback.
