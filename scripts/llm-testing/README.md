# Ollama LLM Testing

This folder is a standalone, throwaway test harness for checking whether the
local Ollama model can extract structured incident data from raw Arabic news
posts before building the real production adapter.

It is not production code and should stay outside `app/`.

## Run

From PowerShell:

```powershell
cd scripts\llm-testing
.\run_test.ps1
```

The script reads Ollama settings from the project `.env`, sends each sample to
the configured `/api/chat` endpoint, prints the raw model response, and writes
all outputs to `results.txt`.

Compare `results.txt` against `answer_key.md` by hand before deciding whether
to proceed with a real `OllamaSourceProvider` adapter or any normalization
service wiring.

## Pull More Samples

Use `pull_test_samples.sql` in pgAdmin against `war_news_dev` to find harder
examples from `raw_messages`, including casualty-number posts, ambiguous
village phrasing, mixed military/security action language, and a random
fallback set. Save selected rows as UTF-8 `.txt` files under `samples/`, then
update `answer_key.md` before rerunning the harness.
