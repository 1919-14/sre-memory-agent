# SRE Memory Agent — Master Plan

**One-liner:** An SRE agent that investigates a failing commit, recalls how *it* fixed a similar
incident before, drafts a fix, review-gates it, verifies it in a sandbox with regression checks, and
writes the whole trajectory back to memory so the next similar failure is cheaper.

**Product category:** An SRE agent that uses accumulated incident memory to investigate, repair,
review, verify and recover from software failures. Not a chatbot. Not a general coding agent.

**Target event:** HackWithHyderabad — "AI Agents That Learn Using Hindsight." See `HACKATHON.md`.
**Memory layer reference:** `HINDSIGHT.md` (verified API behavior + integration design).

---

## 1. The Loop

```
New Commit
   ↓
CI/CD detects failure
   ↓
Collect evidence:
  • error / logs          • stack trace
  • commit diff           • changed files
  • dependency changes    • deploy + env info
  • test report           • last-known-good ref
   ↓
CLASSIFY  ← error taxonomy → picks a specialist playbook or the generic one
   ↓
HINDSIGHT: "Have I seen this failure/change pattern before?"
   │
   ├── YES → prior incident + root cause + successful fix + FAILED fixes
   │           ↓
   │      comparability check (evidence, not truth)
   │           ├── comparable   → adapt prior fix        ─┐
   │           └── not comparable → fresh fix, state why  ─┤
   └── NO ─────────────────────────────────────────────────┤
                                                            ↓
                                                  generate patch (candidate)
                                                            ↓
                                              ┌─────────────┴──────────────┐
                                              │  CODE REVIEW GATE          │
                                              │  • fixes cause, not symptom│
                                              │  • vs remembered conventions│
                                              │  • vs past rejected patterns│
                                              │  • safety / scope / secrets │
                                              └─────────────┬──────────────┘
                                                  approve   │   revise (≤ N) / reject
                                                            ↓
                                                    isolated sandbox
                                                            ↓
                                        apply patch → reproduce failure → tests
                                                            ↓
                                          ┌─────────────────┴─────────────────┐
                                          │  REGRESSION CHECK                 │
                                          │  original error gone?             │
                                          │  target test passes?              │
                                          │  full suite: new failures?        │
                                          │  unrelated blast radius?          │
                                          └─────────────────┬─────────────────┘
                                                    ┌───────┴────────┐
                                                  PASS            FAIL
                                                    │               │
                                                    │        record attempt,
                                                    │        retry if budget left
                                                    │               │
                                                    └───────┬───────┘
                                                            ↓
                                                   attempt budget check
                                                     ┌──────┴───────┐
                                            RECOVERED  │     BUDGET EXHAUSTED / INFRA-CAUSED
                                                       │              │
                                                       │     rollback plan → approval gate?
                                                       │              ↓
                                                       │     restore last known-good
                                                       │              ↓
                                                       │     notify admin (escalate)
                                                       └──────┬───────┘
                                                              ↓
                               HINDSIGHT (both loops):
                                 • incident memory: full trajectory + outcome
                                 • convention memory: review findings, rejected patterns
                                 • runbook: refreshed standing knowledge
```

**Canonical loop:** `Detect → Classify → Remember → Investigate → Fix → Review → Sandbox Test → Verify → Regress → Recover → Learn`

### Three invariants that make this a memory product

1. **Every terminal state writes memory** — success, failed attempts, rejected patches, escalations,
   *and* rollback. Memory of what did **not** work is the differentiator; most teams only store successes.
2. **The second occurrence must be visibly cheaper.** If the demo can't show occurrence 2 being
   faster/better than occurrence 1, the project fails its own thesis.
3. **Failures are classified before they are fixed.** Unclassifiable → escalate, never guess.

---

## 2. Error Coverage Architecture

You asked for an agent that handles **nearly all errors**, with Redis and config as its sharpest
suits. That is achievable, but only with the right shape. "All errors" does not come from one giant
prompt — it comes from **one generic loop plus a specialist layer on top**.

```
                    ANY failure signal
   (failing test, exception, stack trace, CI log, lint,
    type error, import error, dependency conflict, config error)
                            ↓
                    CLASSIFIER (small, fast LLM call)
              → error_class, component, confidence, evidence
                            ↓
        ┌───────────────────┴───────────────────┐
        ↓                                       ↓
  SPECIALIST PLAYBOOK                    GENERIC PLAYBOOK
  (tier-1 classes: extra tools,          (works on any reproducible
   prompts, required evidence,            failure with a code-level cause)
   class-specific memory tags)
        └───────────────────┬───────────────────┘
                            ↓
                   the SAME repair loop
        generate → review → sandbox → test → regress → recover/escalate
                            ↓
                 outcome recorded against its class
```

**Why this is the right shape:** breadth is an *architectural* property (one loop, no per-error
code paths), while depth is a *tuning* property (specialists). Adding a new error class is then a
config change, not a rewrite — which is exactly the argument to make to judges.

### Error taxonomy

| Class | Examples | Tier | Code-fixable? |
| --- | --- | --- | --- |
| `connection-exhaustion` | Redis pool exhausted, DB pool, file descriptors, thread pool | **specialist** | ✅ sizing/config |
| `config-regression` | env drift, wrong flag, missing key, bad default, precedence bug | **specialist** | ✅ |
| `dependency-drift` | breaking API change, missing pin, import error, lockfile conflict | generic+ | ✅ pin/adapt |
| `null-or-type` | `NoneType has no attribute`, `TypeError`, bad cast | generic | ✅ |
| `serialization-schema` | JSON shape, validation error, migration drift | generic | ✅ |
| `timeout-retry` | upstream slow, no backoff, retry storm, missing timeout | generic | ✅ |
| `concurrency-race` | deadlock, lost update, double processing, ordering | generic | ⚠️ sometimes |
| `build-toolchain` | toolchain mismatch, packaging, CI runner image | generic | ⚠️ sometimes |
| `test-defect` | bad assertion, flaky test, missing fixture | generic | ✅ |
| `auth-credential` | expired token, 403, missing scope, rotated secret | **escalate** | ❌ needs a human |
| `infrastructure` | DNS, disk full, region outage, OOM-killed host | **escalate** | ❌ |
| `unknown` | classifier below confidence threshold | **escalate** | ❌ by definition |

**The honest, winnable claim:** *the agent classifies any failure, repairs every code-fixable class
autonomously, and correctly escalates what code cannot fix.* Do **not** claim "fixes all errors" —
judges punish overclaiming far harder than they reward ambition, and a correct escalation is itself a
strong demo moment ("the agent knows what it must not touch").

**Escalation is a first-class outcome, not a failure.** `outcome ∈ {recovered, rolled-back, escalated,
no-failure-detected}`.

### Specialist contract

Each specialist adds **only these four things** — everything else is shared:

1. **Class-specific evidence collection** (Redis: pool size, worker count, active/max connections, timeouts)
2. **Class-specific tools** (e.g. `inspect_connection_pool_config()`, `diff_config_against_baseline()`)
3. **Class-specific prompt + required-evidence list** (the fix is rejected at review if evidence is missing)
4. **Class-specific memory tags** so recall generalizes within the class

Recommended order: `connection-exhaustion` (Redis) → `config-regression` → `dependency-drift` →
rest generic. Redis and config are your depth; everything else inherits the generic loop for breadth.

---

## 3. The Three Memory Loops

All three use Hindsight; they are separate namespaces so they can't contaminate each other.

| Loop | Bank / namespace | Retains | Read by |
| --- | --- | --- | --- |
| **Incident memory** | `sre:<repo>` | Evidence → root cause → every attempt (incl. failures) → verification → resolution → outcome | Recall before fixing; `reflect` for cross-incident patterns |
| **Convention / review memory** | `sre:<repo>:conventions` | Review findings, rejected patterns, team standards, recurring nits | The **review gate**, before approving any patch |
| **Runbook knowledge** | mental model on `sre:<repo>` | Standing answer: recurring failure modes + which fixes are verified | Agent startup (DB read, no LLM call); projected to `data/runbook/<service>.md` |

**Why a second loop is worth the hours:** it makes memory central in *two* places instead of one, it
matches the "Code Review Agent that learns your team's standards" pattern from the problem statement,
and it gives the demo a second before/after: the reviewer stops repeating the same feedback.

---

## 4. Code Review Gate (new stage)

Runs **between** patch generation and sandbox execution. A rejected patch never executes — which is
both a safety property and a token saver.

**Structured verdict:** `{verdict: approve|revise|reject, findings: [{severity, file, line, rule, message}], summary}`

Reviewer checklist:

1. **Cause vs symptom** — does the patch fix the root cause, or silence the error?
2. **Remembers conventions** — violates any standing rule from convention memory?
3. **Repeats rejected patterns** — matches a fix that was previously rejected (that's the memory payoff)
4. **Safety** — path allowlist, size caps, no destructive ops, no secrets/tokens, no debug leftovers
5. **Scope creep** — unrelated edits, reformatting noise, drive-by refactors
6. **Provability** — can the reproduction test demonstrate the fix?

**Loop control:** `revise` sends findings back to the generator (≤ `MAX_REVIEW_CYCLES`, default 2) and
does **not** consume a repair attempt — it never executed. `reject` records the pattern in convention
memory so the generator stops proposing it.

**Two reviewers beat one** if budget allows: a deterministic *policy reviewer* (pure code: paths, size,
secrets regex, forbidden imports) plus an LLM *conventions reviewer*. The policy reviewer can't be
talked out of a rule by a persuasive diff, and it costs nothing. This split is also trivially
demoable — show the deterministic block firing.

---

## 5. Regression Detection (new stage)

Verification is not "the target test passes" — it's "nothing else broke."

| Check | Detail |
| --- | --- |
| Original error resolved | Re-run the exact reproduction; the original exception must be gone |
| Target test passes | The specific failing test from the incident |
| No new failures | Full suite against a **baseline** captured from last-known-good: `new_failures ⊆ ∅` |
| Blast radius | Changed symbols used elsewhere; removed public API; changed defaults/schemas |
| Flake guard | Re-run newly-failing tests N times to distinguish regression from flake |

Store the whole comparison per attempt: `baseline_passed`, `after_passed`, `new_failures[]`.
A fix that resolves the incident but adds a failure is a **failed** attempt — that distinction is what
separates this from a script that just runs pytest.

Note the interaction with memory: a patch that *worked* but caused a regression must be retained as a
failure **with its regression evidence**, so the class-specific recall can say
"the pool-size bump worked here but broke the connection-count assertion in `test_pool_metrics.py`".

---

## 6. Rollback (controlled production action)

Rollback is a **tool with a plan**, never an autonomous `git reset`.

```
create_rollback_plan()   → what reverts, which files, blast radius, what memory stays
        ↓
approval gate            → REQUIRE_APPROVAL_FOR_ROLLBACK=true in the demo
        ↓
execute_rollback()       → restore last known-good ref (never touches working tree)
        ↓
notify_admin()           → escalation record
        ↓
retain outcome=rolled-back with the full trajectory
```

**Critically: a rollback still writes memory.** The value of a rolled-back incident is that the agent
now knows an entire family of fixes *doesn't* work for this failure — that is exactly the knowledge
that stops it wasting the next incident's budget.

Also add a **dry-run rollback preview** so judges can see the plan before it executes.

---

## 7. Winning Modifications

Ranked by expected judge impact. `[25%]` etc. = the judging criterion it targets.

### Tier 1 — do these or lose

**M1. Make the learning curve a *measurable* number, not a claim. `[Innovation 30% + Hindsight 25%]`**
Eval harness over 6–10 seeded incidents: recall hit rate, attempts-to-fix, wall-clock per incident.
Run each seeded incident twice — **cold bank** (`--no-memory`) vs **warm bank** — and put the two
columns side by side. This single artifact is the strongest possible answer to "does the agent clearly
improve over time?"

**M2. Use tags for incident scoping — not metadata. `[Hindsight 25% + Tech 20%]`**
Documented behavior: **`metadata` is NOT a recall filter**; it's returned for client-side use.
Visibility filtering is done with **tags** (`tags` + `tags_match`). Most teams will retain with metadata
and then wonder why retrieval is imprecise. See `HINDSIGHT.md` §3.

**M3. Show memory being *rejected*, not just used. `[Innovation 30%]`**
The agent must refuse a historical fix when it isn't comparable, and refuse a patch that review memory
says was already rejected. Render both refusals in the UI with the reason. "Memory as evidence, not
truth" is the most novel behavior in the project — make it visible.

**M4. Never lose the demo. `[UX 15%]`**
Build `--replay` from hour one: every run records its trajectory (tool calls, patches, review verdicts,
test output) to `data/runs/<incident_id>.json`; replay renders it identically without LLM/Hindsight
calls. Keep one pre-verified flagship trajectory. If the network or Groq rate limit dies in front of
judges, you switch to replay and the story survives intact.

**M5. Pre-seed the bank before you demo. `[Tech 20%]`**
Hindsight consolidates facts into **observations in the background after retain** — you cannot retain
and then immediately rely on consolidated knowledge. Seed 3–4 historical incidents *before* judging and
let consolidation settle.

### Tier 2 — cheap, high signal

**M6. Enable Hindsight Memory Defense. `[Impact 10% + Tech 20%]`**
Our inputs are production logs and stack traces — exactly what leaks credentials and PII. One flag
turns "we dump prod logs into a vector store" into a defensible security posture. Say it out loud in
the video; SRE-minded judges will notice.

**M7. Use `reflect` and mental models, not just `recall`. `[Hindsight 25%]`**
`retain` + `recall` is the shallow integration everyone builds. Add `reflect` for cross-incident
root-cause synthesis, and a **mental model** — a standing answer the bank keeps fresh, read at startup
with no retrieval and no LLM call. Project it to `data/runbook/<service>.md` as a real file the agent
maintains about itself. Very strong visual moment.

**M8. Surface evidence: recall scores + source facts. `[Hindsight 25% + UX 15%]`**
Recall returns structured facts with `type`, `metadata`, `tags`, `entities`, and timestamps, and
observations can return their supporting source facts. Render the trail:
`INC-001 → "raising worker concurrency exhausted the pool" → superseded fix "raise timeout" (FAILED) → fix "raise pool size" (SUCCESS, 3/3 tests)`.
Evidence-backed memory is the difference between "it remembered" and "it *knew*".

**M9. Deterministic policy reviewer beside the LLM reviewer. `[Tech 20% + Impact 10%]`**
Pure code: path allowlist, size caps, secret regex, forbidden imports, debug leftovers. Zero cost,
zero hallucination, and a great demo beat when it hard-blocks a plausible-looking patch.

**M10. Staleness and temporal awareness. `[Innovation 30%]`**
Memory about a service that's been rewritten is dangerous. Recall supports temporal positioning and
returns `occurred_start` / `mentioned_at`. Annotate recalled incidents with age, downgrade confidence
on stale or cross-version matches. Cheap, reads as maturity.

**M11. Triage and escalation as a showcase, not an apology. `[Innovation 30% + Impact 10%]`**
Ship a seeded incident that is *not* code-fixable (expired credential / infra outage) and show the
agent correctly refusing to patch code and escalating instead. Counter-intuitive, but it's the single
most credible thing you can show a senior judge — it proves the agent understands its own limits.

**M12. Constrain the LLM's patch surface. `[Tech 20%]`**
Unified-diff only, path allowlist/denylist, line caps, pydantic-validated patch object, and
"reproduce the failure before fixing" as a precondition. Validation before execution is both a real
safety property and easy to show.

### Tier 3 — polish, only if hours remain

**M13. Attempt ledger as first-class data.** Per attempt: patch, rationale, review verdict, test output,
did the original error persist, did a new error appear, regression evidence. This is what makes
"don't repeat failed fixes" mechanical rather than vibes.

**M14. Approval gate for destructive actions.** Rollback/deploy/DB ops go through a controlled tool that
can require admin approval. Flip it on in the demo to show the human-in-the-loop path.

**M15. Retain quality.** Retain a *narrated* incident with a stable `document_id` (idempotent upsert)
rather than dumping raw diffs. Retain is LLM-extracted, so narrative structure is what produces
reusable facts. See `HINDSIGHT.md` §4.

**M16. Fix-diff explanation in plain English.** One paragraph the on-call engineer can paste into the
incident channel. Cheap, and it makes the whole thing feel like a product rather than a prototype.

---

## 8. Scope Control

**12 hours. Breadth of *coverage* must not become breadth of *scope*.**

| Priority | Items |
| --- | --- |
| **P0 — must work** | Hindsight connect · Groq connect · evidence collection · classifier · recall · fix generation · review gate (policy + LLM) · sandbox exec · regression check · retry budget · rollback · retain (both loops) · **replay mode** · **seed script** |
| **P1 — important** | FastAPI + dashboard · incident history · visible reasoning/status · escalation path · error handling |
| **P2 — only if time** | redis + config specialists (promote to P1 the moment P0 is green) · extra classes · CI webhook · auth · deployment · fancy UI · multi-agent |

**Sequencing rule:** breadth (generic loop over many classes) lands *after* one class works end-to-end
with review + regression + rollback. A generic loop that only half-works is worse than one specialist
that fully works — you can always widen a proven loop, never rescue a broken one.

### Not building
Generic chatbot · general-purpose coding agent · Kubernetes platform · observability platform ·
CI/CD replacement · unrestricted-shell autonomous prod system.

---

## 9. Demo Script

| Time | Beat | On screen |
| --- | --- | --- |
| 0:00 | **The problem.** Same class of failure, twice. | Cold-bank run: full investigation, ~40s, LLM thinking out loud |
| 0:40 | **The failure nobody remembers.** Rollback, alert. | `BUDGET EXHAUSTED → ROLLED BACK`, rollback plan preview |
| 1:00 | **Memory write.** The trajectory goes in — including what failed. | Retain call + the incident document it builds |
| 1:20 | **Same failure, new commit. Watch the clock.** | Warm-bank run: recall fires, prior fix adapted, ~8s |
| 2:00 | **Review says no.** Two refusals back to back. | Policy reviewer blocks a path violation → conventions reviewer flags a previously-rejected pattern |
| 2:30 | **It knows what it can't fix.** Escalation. | `auth-credential → escalate, no patch attempted` |
| 2:50 | **What it learned.** | Self-written runbook page + cold vs warm metrics table |
| 3:10 | **One takeaway.** | Talking head |

**Value must be obvious in 60 seconds.** Open on the contrast, not the architecture diagram.

---

## 10. Architecture

```
                  ┌────────────────┐
                  │ Git Repository │
                  └────────┬───────┘
                           ↓
                  ┌────────────────┐        ┌──────────────────┐
                  │ Failure / CI   │───────→│ FastAPI +        │
                  └────────┬───────┘        │ Dashboard        │
                           ↓                │ (live status)    │
                  ┌────────────────┐        └──────────────────┘
                  │  SRE Agent     │────────────────┘
                  │  orchestrator  │
                  └────────┬───────┘
       ┌───────────┬───────┴────────┬────────────┬───────────┐
       ↓           ↓                ↓            ↓           ↓
 ┌──────────┐ ┌──────────┐  ┌────────────┐ ┌──────────┐ ┌─────────┐
 │Classifier│ │ Git      │  │ HINDSIGHT  │ │  Groq    │ │ Policy  │
 │(taxonomy)│ │ Analysis │  │ incidents +│ │  LLM     │ │ Reviewer│
 └──────────┘ │  tools   │  │ conventions│ │          │ │ (code)  │
              └──────────┘  └────────────┘ └──────────┘ └─────────┘
       └───────────┴───────┬────────┴────────────┴───────────┘
                           ↓
                  ┌────────────────┐       ┌──────────────┐
                  │ Fix Generator  │──────→│ Review Gate  │
                  └────────────────┘       └──────┬───────┘
                                                  ↓ approve
                                          ┌────────────────┐
                                          │ Docker Sandbox │
                                          └────────┬───────┘
                                                   ↓
                                       Tests + Regression Check
                                                   ↓
                                       ┌───────────┴───────────┐
                                       ↓                       ↓
                                    PASS                    FAIL
                                       ↓                       ↓
                                    Verify            Retry / Escalate
                                       │                / Rollback
                                       └───────────┬───────────┘
                                                   ↓
                                              HINDSIGHT
                                        (incident + conventions
                                             + runbook)
```

**Module boundaries (agent logic stays out of tools):**

```
src/sre_agent/
  agent/          orchestrator, state machine, decision logic, prompts
  classify/       error taxonomy + classifier + specialist registry
  specialists/    connection_exhaustion/, config_regression/  (tools+prompt+evidence)
  review/         policy reviewer (deterministic) + conventions reviewer (LLM)
  memory/         Hindsight client wrapper ONLY (banks, tags, retain/recall/reflect,
                  redaction policy, mental models)
  llm/            Groq client, strict JSON/schema forcing, retry + repair
  tools/          git, filesystem, tests, regression, sandbox, rollback — typed tools
  sandbox/        docker execution, isolation, timeouts, resource caps
  models/         pydantic: Incident, Evidence, ErrorClass, Patch, ReviewVerdict,
                  Attempt, RegressionReport, Outcome
  api/            FastAPI routes + SSE/WebSocket live status
  seed/           synthetic incidents (incl. an infra-caused one) + pre-seed script
  replay/         trajectory recorder + replayer
data/             runs/, runbook/, agent.db
demo/             redis-worker-app  (the deliberately broken sample repo)
```

---

## 11. Safety Principle

The agent never executes arbitrary shell in production. Production-affecting actions
(rollback, deploy, infra deletion, destructive DB ops) are **controlled tools**, optionally behind
admin approval. Autonomous code generation and execution happen **only inside the sandbox**.

Sandbox defaults: no network, read-only base image, non-root user, wall-clock timeout, memory/CPU caps,
scratch copy of the repo (never the working tree).

---

## 12. Coding Principles

- Modular; agent logic separate from tools; Hindsight isolated in one module.
- No secrets in code. `.env` only (see `.env.example`). `.env` is gitignored.
- Structured logging on every tool call — it doubles as demo material.
- Validate generated patches before applying (unified diff, path allowlist, size caps).
- Pydantic-validate every LLM response; retry + repair on malformed output.
- Every attempt, review verdict, and regression result traceable and replayable.
- Fail safely: sandbox failure never touches the working tree.
- Simple working code over abstraction. Keep the project runnable at every commit.

---

## 13. Build Order

1. Skeleton + dependency config + `.env` loader + structured logging
2. Hindsight integration (`memory/`) + connect/retain/recall smoke test
3. Groq client (`llm/`) with strict structured output + retry/repair
4. Models (`Incident`, `Patch`, `Attempt`, `Outcome`) + evidence collection tools
5. Deliberately broken `demo/redis-worker-app` with a **baseline** passing suite
6. One incident end-to-end: generate → review → sandbox → test → regress → retain
7. Regression check + rollback + approval gate
8. Classifier + taxonomy; `connection-exhaustion` specialist; then `config-regression`
9. Convention memory + review gate reading from it
10. Seed script (3–4 incidents + 1 infra-caused escalation) + comparability check
11. FastAPI + minimal dashboard
12. Eval harness: cold vs warm metrics table
13. Memory Defense + runbook projection
14. Generalize: remaining classes fall through the generic loop
15. Content deliverables (`HACKATHON.md` §2) — **start the article at ~hour 8, not hour 12**

---

## 14. Success Criterion

> A new failure occurs → the agent classifies it → recalls relevant experience → drafts a fix →
> review-gates it → tests it safely with regression checks → recovers, escalates, or rolls back →
> stores what it learned → handles a future similar failure using that memory.

Measurable: the **warm-bank run beats the cold-bank run on attempts-to-fix and wall-clock time** on the
same seeded incident set, across **multiple error classes** — with `connection-exhaustion` and
`config-regression` showing the largest margins.
