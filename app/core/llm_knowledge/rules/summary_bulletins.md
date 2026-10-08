# Summary bulletins

A summary bulletin is a structured Arabic round-up such as `ملخص الاعتداءات` or
`ملخص حتى الآن`, with action headers followed by locations. Its deterministic
parser resolves its reporting window and strict South/Nabatieh gazetteer matches.
It does not use fuzzy matching. `بين X و Y` is one item with primary X, secondary
Y and modifier `between`; `اطراف X` retains the outskirts modifier.

The parser is authoritative in Phase 1. A later LLM may only add independently
evidenced items; it must never override a parser item. Unknown headers and all
unresolved locations are collected in exactly one review task per summary.
