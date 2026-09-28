# Hindsight — Verified Reference & Integration Design

Everything here is drawn from Hindsight's own README and API docs (v0.10.x, as of 2026-09).
Where something is uncertain or version-dependent it says so.

**Links:** [Docs](https://hindsight.vectorize.io/) · [GitHub](https://github.com/vectorize-io/hindsight) ·
[Hindsight Cloud](https://ui.hindsight.vectorize.io) · [Agent memory primer](https://vectorize.io/what-is-agent-memory)

---

## 1. What Hindsight actually is

An **agent memory system** whose stated goal is agents that *learn*, not just remember. It is explicitly
positioned against plain RAG and knowledge graphs. It reports state-of-the-art results on LongMemEval
(independently reproduced by Virginia Tech's Sanghani Center and The Washington Post; live numbers at
`benchmarks.hindsight.vectorize.io`). MIT licensed, in production at Fortune 500 enterprises.

### Memory types (important — this shapes recall)

| Type | Meaning | SRE analogue |
| --- | --- | --- |
| `world` | Objective facts about the world | "the Redis pool is configured to 20 connections" |
| `experience` | The agent's own events | "I applied a pool-size patch and tests passed" |
| `observation` | Consolidated, evidence-backed beliefs | "raising worker concurrency without raising the pool causes exhaustion" |

Memories are stored as entities + relationships + time series with sparse/dense vectors, **not as raw text** —
retain is LLM-extracted, so what you send is decomposed into facts.

### The three operations

| Op | Purpose | Our use |
| --- | --- | --- |
| **retain** | Write memories | Store each incident trajectory + outcome |
| **recall** | Retrieve structured facts | "Have I seen this failure before?" |
| **reflect** | Reason *over* memories (disposition-aware) | Cross-incident root-cause synthesis, "what should I try?" |
| **observations** | Background consolidation of related facts | Recurring failure-mode beliefs, with proof counts |
| **mental models / knowledge pages** | Standing answers to a question, kept fresh in the background; reading one is a **plain DB read — no retrieval, no LLM call** | A self-maintained service runbook the agent boots with |

> Mental models are the highest-leverage, least-copied feature for our use case: the agent can boot with
> an accumulated runbook instead of rediscovering it every session. Strong demo material.

### Memory banks

A bank is an isolated memory store — one brain per user/agent/project, with **strict isolation, no
cross-bank leakage**. Banks carry background context and **disposition traits** (skepticism, literalism,
empathy) that shape how `reflect` reasons. Banks can be created from declarative **bank templates**.

**Memory Defense** — opt-in, per-bank policy that scans every retain for secrets/PII against ~45 patterns
and either redacts (`[REDACTED:github_token]`) or blocks before storage. **Enable this for our agent** —
we're ingesting production logs and stack traces.

---

## 2. Running Hindsight

### Option A — Hindsight Cloud (zero ops)
Managed, usage-based, 99.9% SLA, dashboard + backups. Point clients at `https://api.hindsight.vectorize.io`
with an API key. Promo code **`MEMHACK99`** gives $50 credits — **applied in the billing section AFTER
registering**, not at signup.

### Option B — Docker (recommended for local dev)

```bash
export OPENAI_API_KEY=sk-xxx   # or provider key
docker run -it --pull always --name hindsight --restart unless-stopped \
  -p 8888:8888 -p 9999:9999 \
  -e HINDSIGHT_API_LLM_API_KEY=$OPENAI_API_KEY \
  -v hindsight-data:/home/hindsight/.pg0 \
  ghcr.io/vectorize-io/hindsight:latest
# API: http://localhost:8888   UI: http://localhost:9999
```

The server's own extraction LLM is provider-agnostic (25+ providers) — **set it to Groq** so the memory
layer and the agent share one free-tier key:

```
HINDSIGHT_API_LLM_PROVIDER=groq
HINDSIGHT_API_LLM_API_KEY=<groq key>
```

Options: Docker w/ external PostgreSQL (`docker/docker-compose`), bare metal (`pip install hindsight-api`),
Helm/Kubernetes, or **embedded** (`pip install hindsight-all`) which runs the server in-process — useful for
a hackathon because there's no separate service to keep alive. On Intel Macs use `hindsight-all-slim`.

### Option C — MCP
Every server ships an MCP endpoint, one per bank, enabled by default:
`http://localhost:8888/mcp/{bank_id}/` — exposes retain/recall/reflect as tools.

---

## 3. Clients

```bash
pip install hindsight-client -U      # Python  (also: npm @vectorize-io/hindsight-client, Go)
```

```python
from hindsight_client import Hindsight
client = Hindsight(base_url="http://localhost:8888")   # + api_key for Cloud
```

> The embedded example in the README imports `HindsightServer, HindsightClient` from `hindsight` instead.
> **Verify the class name and signatures against the installed version** before wiring it in — don't trust
> our transcription.

### Retain parameters (verified)

| Param | Notes |
| --- | --- |
| `content` | **Required.** Raw text; chunked → LLM fact extraction. Never stored verbatim. |
| `context` | Short source label ("ci failure", "incident postmortem") injected into the extraction prompt. **Docs call consistent `context` "one of the highest-leverage things you can do to improve memory quality."** |
| `timestamp` | When the event happened. ISO 8601, omit (defaults to now), or `"unset"` for timeless reference material. Enables temporal recall. |
| `metadata` | Arbitrary string key/values. Used as extraction context **and returned with every recalled memory — but NOT used as a recall filter.** For client-side enrichment/provenance (commit SHA, incident URL). Null values are dropped. |
| `document_id` | Makes retain **idempotent**: re-retaining the same ID deletes the old doc + memories and reprocesses. Omit → random UUID → duplicates on re-run. |
| `update_mode` | `"replace"` (default) or `"append"` — append concatenates new content onto the existing document, skipping unchanged chunks. Use append for a growing incident timeline. |
| `tags` / `document_tags` | **Visibility scoping for recall.** The filter mechanism. Conventions: `user:<id>`, `session:<id>`, `topic:<name>`. Bank exposes a list-tags endpoint with memory counts. |
| `entities` | Names to guarantee are recognized/merged into the knowledge graph (optional `type`). |
| `resolve_entities` | `false` → treat supplied names as authoritative, no fuzzy merging. |
| `observation_scopes` | Which observations this memory contributes to: `combined` (default), `shared`, `per_tag`, `all_combinations`, `custom`. Scope matching is `all_strict`, so scopes stay isolated. |

Also available: `retain_batch(...)` (recommended for throughput) and `retain_files(...)` for PDF/DOCX/
images/audio → text (always async, returns `operation_ids`).

Response: `success`, `bank_id`, `items_count`, `async`, `usage` (tokens, sync only).

### Recall parameters (verified)

| Param | Notes |
| --- | --- |
| `query` | **Required.** Drives all four strategies. **Hard limit: 500 tokens** — longer queries are rejected. |
| `types` | `world` / `experience` / `observation`. Omitted = all. Each type runs the full pipeline → narrowing cuts cost. |
| `prefer_observations` | When observation is included alongside raw types, drop the raw facts an observation supersedes and backfill with next-best. Disabled by default. |
| `budget` | `low` / `mid` (default) / `high`. Depth + breadth. `high` for "find indirect connections". |
| `max_tokens` | Default **4096**. Only `text` counts toward it. Hindsight thinks in tokens, not result counts. A query that matched never returns empty — worst case the top fact comes back over budget. `max_tokens=0` = "no facts, chunks only". |
| `query_timestamp` | Anchor for relative time expressions + recency scoring. Matters for replaying history. |
| `temporal_window` | `{start, end}` explicit ISO bounds. **Ranks, does not filter** — results outside the window still come back. Compares the memory's own event dates, not storage time. |
| `include.chunks` | Return raw source chunks each fact was extracted from (own token budget, default 8192). Great for "show the log line". |
| `include.source_facts` | With `types=[observation]`, return the facts each observation was built from, plus `source_fact_ids`. **This is how you prove an observation is evidence-backed.** |
| `include.entities` | On by default; `null` skips the JOIN and reduces payload. |
| `tags` + `tags_match` | See below. |

**Retrieval pipeline:** four strategies run in parallel — **semantic** (vector), **keyword** (BM25),
**graph** (entity/temporal/causal links), **temporal** (time-range). Results are merged with reciprocal
rank fusion, re-ranked by a cross-encoder, then trimmed to the token budget.

**Returned per fact:** `id`, `text`, `type`, `context`, `metadata`, `tags`, `entities`,
`occurred_start`, `occurred_end`, `mentioned_at`, `document_id`, `chunk_id`.

### `tags_match` modes — get this right

| Mode | Untagged memories | Matches |
| --- | --- | --- |
| `any` (default) | included | has ≥1 of the given tags |
| `any_strict` | excluded | has ≥1 of the given tags |
| `all` | included | has all given tags |
| `all_strict` | excluded | has all given tags |
| `exact` | excluded | tag set exactly equals the given tags |

⚠️ **Empty-tag gotchas:** an omitted/null/`[]` tag list with any mode except `exact` means *no filter at
all*. With `exact`, an empty list selects only untagged/global memories. Over MCP, to target the untagged
scope you must pass **both** `tags: []` and `tags_match: "exact"`.

---

## 4. Integration Design for SRE Memory Agent

### Bank strategy

| Concept | Value |
| --- | --- |
| Bank id | `sre:<repo-slug>` — e.g. `sre:redis-worker-app`. One brain per repo/environment. Don't use guessable global strings. |
| Bank template | `sre-incident` — background context ("you are an SRE agent; memories are incident reports") + disposition traits (high **skepticism**, so `reflect` challenges weak evidence). |
| Memory Defense | **ON.** Logs and traces contain tokens, DSNs, PII. |
| Cross-env | Prefer separate banks over tags for hard isolation between prod/staging. |

### Tag schema (the recall filter)

```
service:payments-api        service:worker
error-class:connection-exhaustion   error-class:null-deref   error-class:config-regression
component:redis             component:postgres      component:http-client
env:prod                    env:ci
outcome:recovered           outcome:rolled-back     outcome:escalated   outcome:fix-failed
version:v2.4.0
```

Keep `error-class:` aligned with the classifier taxonomy in `PROJECT.md` §2 — that single convention is
what makes recall generalize across *incidents* while staying scoped to a *failure class*. Add new
classes by adding a tag, never by adding a code path.

Provenance that must **not** be a tag (metadata only, because it fragments the tag space and defeats
generalization): `incident_id`, `commit`, `pr_url`, `run_id`, `timestamp`.

Query tags by *failure class*, not by incident id, so recall generalizes:
`recall(bank, query=<current error + diff summary>, tags=["service:worker","error-class:connection-exhaustion"], tags_match="any")`
Untagged memories stay visible under `any`, which is useful for global policy knowledge.

### What we retain per incident

Narrated text (not a raw diff dump) + `context` + `document_id` + tags + metadata. Retain is
LLM-extracted, so structure is what produces reusable facts:

```python
client.retain(
    bank_id=f"sre:{repo}",
    context="incident postmortem: production failure and recovery",
    document_id=incident.id,                 # idempotent upsert
    timestamp=incident.detected_at,
    tags=[
        f"service:{incident.service}",
        f"error-class:{incident.error_class}",
        f"component:{incident.component}",
        f"env:{incident.env}",
        f"outcome:{incident.outcome}",
        f"version:{incident.version}",
    ],
    metadata={                               # provenance for the UI only
        "incident_id": incident.id,
        "commit": incident.commit_sha,
        "pr_url": incident.pr_url or "",
        "attempts": str(len(incident.attempts)),
        "duration_s": str(incident.duration_s),
    },
    content=f"""
    INCIDENT {incident.id} ({incident.env}, {incident.detected_at.isoformat()})
    Symptom: {incident.error_message}
    Stack: {incident.stack_trace[:2000]}
    Change under suspicion: commit {incident.commit_sha[:8]} by {incident.author}
      files: {', '.join(incident.changed_files)}
      diff summary: {incident.diff_summary}
    Root cause: {incident.root_cause}
    Attempts:
    {attempt_lines}      # e.g. "1. raise request timeout -> FAILED: original error persisted"
                         #      "2. raise Redis pool 20->64, cap worker concurrency -> SUCCESS"
    Verification: {incident.verification}
    Final resolution: {incident.final_resolution}
    Outcome: {incident.outcome}
    """,
)
```

For a long-running incident, keep appending the timeline with
`document_id=incident.id, update_mode="append"`.

### Recall → decision

```
1. Build the query from the CURRENT symptom only (error class + message + diff summary).
   Keep it well under the 500-token cap.
2. recall(bank, query, tags=[service, error-class], tags_match="any",
          types=["world","experience","observation"],
          prefer_observations=True, budget="mid", max_tokens=3000,
          include_source_facts=True)
3. Comparability check (the LLM judges, the code decides):
   - same error class?           required
   - same component/service?     required
   - overlapping changed files?  strong signal
   - version drift?              downgrade confidence
   → returns {comparable: bool, confidence: 0-1, reason: str, prior_incident_id}
4. comparable=True  → adapt the prior successful fix (never apply it verbatim)
   comparable=False → generate a fresh fix, and SAY WHY it was rejected
5. Always feed the FAILED attempts of prior incidents into the fix generator as
   explicit "do not repeat these" constraints.
6. reflect(bank, "What are the recurring failure modes for <service> and which fixes actually
   worked?") for the cross-incident view — use it for the runbook page, not the hot path.
```

### Knowledge page / mental model (the runbook)

Define one standing question per bank:

> *"What are the recurring failure modes in this service, which fixes have been verified, and which
> fixes have failed?"*

Read it at agent startup — it's a DB read, no LLM call, no retrieval — and project it to
`data/runbook/<service>.md` so it's visible as a real file in the repo. Refresh happens in the
background as the bank learns.

### Gotchas to design around

1. **Metadata ≠ filter.** Use tags. (Most common integration mistake.)
2. **Observations consolidate in the background.** Don't retain and then immediately depend on
   consolidated knowledge. **Pre-seed the bank before demoing** and let consolidation settle.
3. **Retain costs an LLM call per chunk** — latency and rate limits. Batch where possible, keep
   incident narratives concise, and remember Groq's free-tier limits when seeding.
4. **Recall query ≤ 500 tokens.** Don't paste a whole stack trace into the query.
5. **"A query that matched never returns empty."** Absence of results ≠ absence of a match. Don't
   write logic that assumes an empty list means "no prior knowledge"; check relevance instead.
6. **`temporal_window` ranks, doesn't filter.** If you need a hard time bound, filter client-side.
7. **Bank ids are not auth.** For a multi-tenant story, layer a permission tag in addition to the bank.
8. **Don't scatter provenance into tags.** Tags are for scoping/visibility; per-incident identifiers belong
   in `metadata`. A tag space polluted with unique ids turns recall back into exact lookup.
9. **Recall quality tracks retain quality.** Because retain is LLM-extracted, a vague incident narrative
   produces vague facts. Once the fix loop works, spend 30 minutes improving the retain template — it is
   usually a bigger win than tuning retrieval.

---

## 5. Install the docs skill while coding

```bash
npx skills add https://github.com/vectorize-io/hindsight --skill hindsight-docs
```

Gives the coding agent instant access to Hindsight docs inside the repo — worth doing before writing
the memory module, since API details have moved between versions.

---

## 6. Second Memory Loop — Conventions & Review Feedback

The review gate (§4 of `PROJECT.md`) needs its own memory. Two things live here: the team's standing
rules, and the patterns the reviewer has already rejected.

**Bank:** `sre:<repo>:conventions` (separate bank = strict isolation, no contamination of incident recall).

### Standing rules → `world` facts

Retain once at setup, tag `kind:convention`:

```python
client.retain(
    bank_id=f"sre:{repo}:conventions",
    context="engineering conventions for this repository",
    document_id="conventions-core",        # stable id -> re-running is idempotent
    timestamp="unset",                     # timeless reference material, not an event
    tags=["kind:convention", "component:config", "language:python"],
    content="""
    Repo conventions (authoritative):
    - Configuration is read through settings.py. Direct os.environ access is rejected in review.
    - Redis pool size must be derived from worker count, never hardcoded.
    - Bare `except:` is rejected; catch specific exception types.
    - Retry logic must use exponential backoff. Fixed sleep was rejected in PR #212 and PR #233.
    - Migrations and CI workflow files are out of scope for automated fixes.
    """,
)
```

`timestamp="unset"` is the documented flag for timeless reference material — it prevents the extractor
from inventing event dates for what is really a policy document.

### Rejected patterns → `experience` facts, written automatically

Every `reject` verdict (and every patch that failed review twice) is retained so the generator stops
proposing it. This is the memory payoff for the review gate — without it, the reviewer just nags.

```python
client.retain(
    bank_id=f"sre:{repo}:conventions",
    context="code review outcome: patch rejected before execution",
    document_id=f"review-{review.id}",
    timestamp=review.created_at,
    tags=["kind:rejected-pattern", f"error-class:{incident.error_class}", f"component:{incident.component}"],
    metadata={"incident_id": incident.id, "commit": incident.commit_sha, "severity": review.max_severity},
    content=f"""
    Review verdict: {review.verdict}
    Patch under review: {review.patch_summary}
    Finding: {review.summary}
    Rule violated: {review.rule}
    Reviewer guidance: {review.guidance}
    """,
)
```

### How the review gate reads it

```python
# 1. Hard rules the patch must not violate.
rules = client.recall(
    bank_id=f"sre:{repo}:conventions",
    query=f"conventions that apply to changes in {patch_files}",
    tags=["kind:convention"],
    types=["world"],
    budget="mid",
)

# 2. Has this exact approach already been rejected, or already failed in production?
rejected = client.recall(
    bank_id=f"sre:{repo}:conventions",
    query=f"was this fix approach previously rejected or did it fail? {patch_summary}",
    tags=["kind:rejected-pattern", f"error-class:{incident.error_class}"],
    tags_match="any",
    types=["experience", "observation"],
    prefer_observations=True,
    include_source_facts=True,
)
```

Then feed both into the reviewer prompt as **hard constraints with citations**, and into the generator
prompt as explicit *do-not-propose* items.

### The demo payoff

Session 1: the generator proposes `time.sleep(5)` retries; review rejects it citing PR #212/#233.
Session 2 (after the convention is retained): the generator proposes exponential backoff on the first
try because recall surfaced the prior rejection. Same agent, no code change, different behavior — that
is a second, independent demonstration of memory changing behavior, and it's cheap to produce.

### Gotchas specific to this loop

- Keep conventions in their **own bank**; convention facts tagged into the incident bank would show up in
  incident recall under `tags_match="any"` and pollute root-cause reasoning.
- Conventions written with `timestamp="unset"` won't participate meaningfully in temporal recall — that's
  correct and intended.
- Don't let the agent silently promote its own opinion to a convention. Only retain a convention from an
  explicit human act (setup seed, or an approval-gate action), or the agent will drift to its own tastes.

---

## 7. Verified against the installed SDK (`hindsight-client`)

The questions below were answered by introspecting the actually-installed package rather than
by reading docs, and `src/sre_agent/memory/store.py` is written to the real signatures.

| Question | Answer |
| --- | --- |
| Import + class name | `from hindsight_client import Hindsight` (also `HindsightClient`); embedded server is `from hindsight import HindsightServer, HindsightClient` |
| Explicit bank creation? | Yes — `client.create_bank(bank_id=..., ...)`; also `update_bank_config` / `get_bank_config` and bank **templates** (`sre-incident`) |
| `retain` signature | `retain(bank_id, content, context=..., timestamp=<datetime, not str>, tags=[...], metadata=...)` — it takes a real `datetime` |
| `recall` | `recall(bank_id, query, budget=..., max_tokens=..., types=[...], tags=[...], tags_match=...)`; results expose a `final` relevance score (there is no `score` field) |
| `reflect` | `reflect(bank_id, query, ...)` **and it accepts `response_schema`** for structured output — used for the comparability judgement |
| Memory Defense | `memory_defense` is a free-form dict on the bank config, not a typed model. Applied defensively and the result is reported as observed, never assumed. |
| Other capabilities present | `observations`, mental models, knowledge pages, `export`/`import`, webhooks, per-bank MCP endpoint |

### Running Hindsight locally: two real blockers

Both were hit while wiring the memory layer. They are **environment/plan limits, not application
defects**, and the agent reports either one as a degraded run rather than pretending memory worked.

**1. `service_tier` rejected by Groq.** Hindsight sends `service_tier: auto` on its own
retain/reflect calls. Groq returns HTTP 400 (`"service_tier" "auto" is not available for this
org`) on plans that do not include it. Fixes applied: `HINDSIGHT_API_LLM_GROQ_SERVICE_TIER=on_demand`
(verified to work for `reflect`), plus `HINDSIGHT_API_RETAIN_LLM_EXTRA_BODY` /
`HINDSIGHT_API_CONSOLIDATION_LLM_EXTRA_BODY` for the per-task paths. In testing the extraction
path still sent `auto` despite the documented override — a Hindsight-side quirk to track upstream.

**2. Free-tier token ceiling.** A free Groq plan allows ~8,000 tokens/minute. A single
`reflect` call requested **5,179 tokens** against a budget already at 6,843, so it cannot fit —
retrying does not help, because each attempt consumes from the same window. Options, in order of preference:

1. **Hindsight Cloud** — `HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io` plus
   `HINDSIGHT_API_KEY`. Not subject to your local Groq plan's ceiling. (`MEMHACK99` credits are
   applied in the billing section *after* registering.)
2. **Local Docker** — `docker run -p 8888:8888 -p 9999:9999 ghcr.io/vectorize-io/hindsight:latest`
   pointed at a paid Groq tier or a different extraction provider.
3. **Embedded** (`hindsight-all`, `scripts/start_hindsight.py`) — works, but bundling the embedding
   and Postgres binaries pulls ~1.7 GB into the venv and needs a generous first-start timeout
   (`HINDSIGHT_START_TIMEOUT=300`). Good for offline development, heavy for a demo laptop.

The app degrades cleanly in every one of these cases: incidents are still classified, repaired,
reviewed, tested and rolled back correctly; they are simply marked `degraded` with the reason, and
the memory write is retried rather than silently dropped.

---

## 8. Verified against a real server

Run against `ghcr.io/vectorize-io/hindsight:latest` (API v0.10.1, embedded PostgreSQL +
pgvector, local embeddings and reranker) with `scripts/verify_memory.py`:

| Operation | Result |
| --- | --- |
| Server startup | Healthy in ~25s; migrations complete; logs `Connection verified: groq/openai/gpt-oss-120b` |
| `create_bank` | Both banks created (`sre:demo-repo`, `sre:demo-repo:conventions`) |
| Memory Defense | `{"action": "redact", "enabled": true}`, `audit_log_enabled: true` — read back from the server, not assumed |
| `retain` | `success=True items=1`; a 3,475-character incident report extracted into searchable facts |
| `recall` | 6 memories with real scores (1.098, 1.096, 1.062, 1.058) covering root cause, symptom, lesson and repair |
| Convention bank | 2 conventions retained and recalled by tag |
| `reflect` | **Fails** — requests 5,179 tokens against an 8,000 TPM free-tier ceiling |
| Runbook mental model | Created; background content generation also hits the ceiling |

A live incident run then recalled prior memories and retained its own trajectory, so the
learning loop is confirmed end to end. Two behaviours were fixed as a result of this run:

- **Quota is retried, not lost.** Hindsight reports rate limiting as HTTP 500 with the
  provider message embedded. `MemoryStore._call` now waits the window the provider asks for
  and retries; this observed-and-recovered twice on real incident writes during testing.
- **An unfinished mental model no longer reads as content.** Hindsight serves
  `Generating content...` while it builds a model; that placeholder was being returned as the
  runbook. An unfinished model now reads as an empty runbook, and a missing model (404) is a
  normal state rather than an error.

### Still open

- [ ] Consolidation latency — how long between `retain` and usable `observations`
- [ ] Whether the upstream `retain` service-tier pass-through is a known issue (worth a report)
- [ ] A provider with enough TPM to run `reflect`, or Hindsight Cloud, to exercise the runbook
- [ ] Async client end-to-end (the current loop is synchronous; fine at this scale)
