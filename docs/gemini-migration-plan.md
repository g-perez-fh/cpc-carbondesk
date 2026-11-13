# Chatbot migration to Gemini

The user requested Gemini in place of OpenAI. This updates the earlier provider
decision; it does not change chatbot ownership or company-data boundaries.

## Shared implementation contract

- Preserve `assistant.llm.complete(instructions, messages) -> str`,
  `is_configured()`, and `LLMUnavailable` so chat and monthly summaries retain
  their existing fallback behavior.
- Use Gemini Developer API `generateContent` over HTTPX (pin 0.28.1, already
  used by the frontend). No additional provider framework or SDK is needed.
- Settings: `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.5-flash`),
  `GEMINI_TIMEOUT_SECONDS` (default 30). Keep a bounded output token budget.
- Send the key in `x-goog-api-key`, not the URL. Map assistant history to
  Gemini's `model` role; keep instructions separate as `systemInstruction`.
- Return only answer text, excluding thought parts. Provider failure, malformed,
  empty or blocked responses must reach the existing fallback safely.
- Do not send live requests, read real keys, edit `.env`, change data models,
  commit/push, restart running services, or touch unrelated presentation work.

## Worker 1 — adapter and runtime configuration

1. Replace the OpenAI wrapper in `backend/assistant/llm.py` with Gemini REST.
2. Handle expected network/HTTP/response failures without exposing API keys,
   prompts, company data or raw provider errors in logs or responses.
3. Replace provider settings in `backend/config/settings.py`, `.env.example`,
   and `compose.yaml`; pass all three settings into the backend container.
4. Replace the OpenAI SDK dependency with explicit HTTPX in
   `requirements/backend.txt` after checking for other SDK consumers.
5. Run Django check and focused lint/format checks; report changes and limits.

## Worker 2 — tests and user documentation

1. Update the autouse key-clearing fixture in `backend/conftest.py` and existing
   assistant tests to the new settings, ensuring developer keys cannot cause
   real requests during tests.
2. Add mocked HTTPX adapter tests: payload/roles/system instruction, model,
   timeout and key header; multi-part text, thought exclusion, missing key,
   timeout/connection failure, 401/429/5xx, invalid JSON, malformed/empty/blocked
   replies. Assert secret and prompt material is absent from log output.
3. Cover successful and failed chat/monthly-summary flows, conversation history,
   and retain organisation/user isolation checks.
4. Update README setup for Gemini and no-key fallback, linking official docs.
   Explain replacing old OpenAI environment variables and local Compose rebuild.
5. Run focused tests once worker 1's adapter/configuration is available. If that
   dependency is not ready, finish the assigned files and identify pending runs.

## Parent review and completion gate

- Review both diffs personally for protocol correctness, secret handling,
  scope boundaries, fallback behavior, dependency and configuration consistency.
- Correct findings, then run `.venv/bin/python backend/manage.py check`,
  `.venv/bin/python -m pytest`, `.venv/bin/python -m ruff check .`, and
  `.venv/bin/python -m ruff format --check .`.
- Validate Compose without displaying resolved environment secrets. Preserve
  existing containers and database volumes. A live Gemini test requires an
  explicitly supplied key and is not claimed by mocked verification.
- Record actual evidence and remaining limitations here after review.

## Official references

- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/models

## Completed review and evidence

Both GLM-5.3-Flash Free workers completed their assigned scopes at Max effort.
The parent reviewed the adapter, settings, dependency change, Compose wiring,
README, key-clearing fixture, and mocked tests directly.

Review corrections:

- Treat whitespace-only keys as missing and strip header-key whitespace.
- Reject blocked prompts even if candidate text is present. Reject candidate
  finish reasons other than STOP when provided, including safety stops and
  token-limit truncation; retain compatibility with omitted finish reasons.
- Bound output at 4,096 tokens to give generation more room than the former
  1,000-token limit; answers remain short through the existing prompts.
- Add candidate safety/recitation and malformed JSON-shape regressions.
- Clarify README migration variables and the scope of the no-network guarantee.

Final verification on 13 November 2026:

| Check | Result |
| --- | --- |
| `.venv/bin/python backend/manage.py check` | No issues |
| `.venv/bin/python -m pytest -q` | 301 passed in 21.50 seconds |
| `.venv/bin/python -m ruff check .` | Passed |
| `.venv/bin/python -m ruff format --check .` | 138 files already formatted |
| `docker compose config --quiet` | Passed; resolved secrets not displayed |
| `git diff --check` for migration files | Passed |

Tests used an empty GEMINI_API_KEY environment override and the autouse fixture
blocks unmocked adapter HTTP calls. The user separately requested local `.env`
preparation: existing values were preserved, missing Gemini entries added, and
Git ignore protection confirmed without displaying secrets.

Live local verification: the original `gemini-3.8-flash` returned HTTP 503
`UNAVAILABLE` with a temporary high-demand message. A direct adapter request
and the authenticated chat flow then succeeded with `gemini-3.5-flash`. The
chat test used temporary synthetic 40.00 kg CO2e of Scope 2 data, got a correct
initial answer and follow-up, and confirmed four persisted message roles; all
temporary test records were deleted. The model setting was updated in `.env`,
`.env.example`, and this README. No commit or push was made. Unrelated
presentation changes were preserved.
