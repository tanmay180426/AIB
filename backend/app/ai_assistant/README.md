# AI Assistant

Local-only optional LLM assistant, with deterministic calculations grounded in the selected dataset.

## Flow
1. `POST /api/insights/query` `{question, context_limit?}`
2. `context.build_context(db, role)` gathers a fixed set of real aggregates
   (no arbitrary SQL): monthly revenue, top categories, order statuses, and ML
   status. Both supported roles (analyst/admin) get this same business context;
   platform administration data and secrets are never included.
3. Supported numerical/grouped intents return first from the shared local metrics
   layer (`provider: computed`), without contacting any LLM. For other questions,
   `provider.ProviderFactory.get_provider()` selects the LLM:
   - `OllamaProvider` when `ENABLE_LLM_ASSISTANT=true` and `LLM_PROVIDER=ollama`
     (calls `${OLLAMA_BASE_URL}/api/generate`).
   - `DisabledProvider` otherwise.
4. If the LLM is unavailable, the endpoint returns a deterministic, data-grounded
   summary (`status: llm_unavailable`) instead of failing.

## Status
`GET /api/insights/status` returns the configured provider, model, whether the
provider is `reachable`, and the fallback behaviour. It never raises — a failed
probe is reported as `reachable: false`.

## Live run (local Ollama)
```powershell
ollama pull llama3.2
$env:OLLAMA_NO_CLOUD='1'          # set on the Ollama server process, then restart it
ollama serve                      # or run the Ollama desktop app
# set ENABLE_LLM_ASSISTANT=true through your existing local environment
cd backend; python -m uvicorn app.main:app --reload
```
Confirm `reachable: true` at `/api/insights/status` before asking questions.
With the flag off (default), responses come from the deterministic fallback.
The pull command is an optional initial download; it is not executed by the app.
Use an already installed model with `OLLAMA_MODEL` to avoid another download.

## Config (env)
- `ENABLE_LLM_ASSISTANT` (default false)
- `LLM_PROVIDER` (default `ollama`)
- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (default `llama3.2`)
- `LLM_TIMEOUT_SECONDS` (default 20)

Only `ollama` is allowed. `OLLAMA_BASE_URL` must be HTTP(S) on `localhost` or a
literal loopback IP, without URL credentials/query/fragment. Custom local ports
and models remain supported. Previously accepted remote/LAN URLs and unknown
provider names now fail startup clearly; use loopback for this free-only mode.
HTTP clients ignore environment proxies and do not follow redirects. A local
failure never substitutes a hosted provider. No provider API key is required.
Before generation, `/api/show` must report local model metadata without
`remote_model`/`remote_host`; cloud tags and remote aliases are refused before
the prompt/context is sent. Keep Ollama cloud features disabled on its daemon;
the FastAPI process cannot configure a separately running daemon for you.
For unsupported questions, unavailable generation returns an explicit limitation
and a computed summary (`llm_unavailable`), preserving the API response shape.

See `docs/FREE_API_AUDIT.md` at the repository root for verification and resource
limits. Local models consume disk/RAM/CPU or GPU and electricity; no claim of
zero infrastructure cost is made.

## Permission awareness
- Context scope depends on the caller's role (from the JWT).
- The LLM only ever sees the pre-computed context; it cannot query the database.
