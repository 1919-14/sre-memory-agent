---
title: SRE Memory Agent
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Incident recovery that remembers
---

<!--
This file is the Hugging Face Space card. `deploy/huggingface/sync.sh` copies it to the root
of the Space snapshot as `README.md`; the repository's own README.md stays where it is. The
YAML block above is Space metadata and must stay at the very top of the file.
-->

# SRE Memory Agent

**Incident recovery that remembers.**

An autonomous SRE agent that investigates software failures, recalls relevant experience
through **Hindsight** memory, safely tests repairs, and learns from every incident.

This Space runs the real system — the FastAPI backend and the full React dashboard, not a
screen recording. `OPEN LIVE SYSTEM` below is the same application the repository documents.

## What it does

```
DETECT  →  CLASSIFY  →  REMEMBER  →  INVESTIGATE  →  REPAIR
                                                 ↓
LEARN  ←  RECOVER / ROLL BACK / ESCALATE  ←  REGRESS  ←  VERIFY  ←  REVIEW
```

1. **Detect** — identify the failing revision and collect evidence from the failing run.
2. **Classify** — assign a failure class before attempting any repair.
3. **Remember** — search Hindsight for comparable incidents and past repairs.
4. **Investigate** — judge whether that history actually applies to this failure.
5. **Repair** — generate or adapt a candidate fix.
6. **Review** — check the candidate against policy rules and engineering conventions.
7. **Verify** — reproduce the original failure, apply the fix, run the suite.
8. **Regress** — confirm the fix introduced no new failures.
9. **Recover** — accept the fix, or roll back and escalate when verification fails.
10. **Learn** — retain the full trajectory, including failures, for the next incident.

Memory is treated as **evidence, not truth**: a previous repair that matches on error class
is still checked against the current failure before it is reused.

## Running the demo

Open the dashboard and use **Run demo** in the header. Three scenarios from the generated
demo repository are available:

| Scenario | Expected outcome |
| --- | --- |
| `concurrency` | Repaired — pool sizing derived from worker concurrency |
| `leak` | Repaired — but *not* by reusing the pool-sizing fix, despite the identical error class |
| `auth` | Escalated — an expired credential is not a code defect |

Run `concurrency` and then `leak`: the second incident recalls the first and has to reject
it, which is the point of the whole system.

## How this Space is configured

**Every run on this Space is labelled with its mode.** The dashboard reports it; nothing is
presented as live when it is not.

- **Recorded-trajectory mode (default)** — with no LLM key configured, the demo re-renders
  real trajectories recorded from earlier live runs. The patch, review verdict and
  comparability judgement in them came from actual runs that were verified in a sandbox.
  Runs are marked `simulated`.
- **Live mode** — set `GROQ_API_KEY` in *Settings → Variables and secrets*. The agent then
  reasons live, generates patches, and grades its own work.
- **Memory runs inside this Space.** Hindsight is started in the same container
  (`hindsight-all` with embedded PostgreSQL, no Docker and no external service), with its
  database and embedding-model cache under `/data`, so what the agent learns survives a
  restart. It needs `GROQ_API_KEY`, because Hindsight extracts memories with an LLM; without
  one the agent reports memory as **unavailable** rather than pretending.
- **Or let Hindsight Cloud hold the memory.** Set `HINDSIGHT_API_KEY` (from the dashboard's
  *Connect* → *Create API Key*) and leave `HINDSIGHT_BASE_URL` unset: the agent then talks to
  `https://api.hindsight.vectorize.io` and the in-container server is skipped. That removes the
  embedded-PostgreSQL boot, the first-start model download, and the free-tier ceiling on the
  memory layer's own extraction calls. `HINDSIGHT_BASE_URL` can also point at any other
  Hindsight you run, if you would rather not use the managed one.
- **The first start is slow.** Initialising PostgreSQL and downloading the embedding models
  takes a few minutes; every start after that reuses `/data`. If the memory server is still
  starting when the API comes up, the agent connects on a later check instead of needing a
  restart.
- **Sandbox** — a Space has no Docker daemon, so generated code runs in the local
  temporary-workspace backend instead of a container. The dashboard reports this as a
  degradation. A container-isolated sandbox needs the self-hosted setup in the repository.

Incident history, the recording and model caches, and the memory database are all written
under `/data`, which a Space preserves across restarts.

On a free Groq plan the memory layer's own extraction calls share the per-minute token budget
with the agent's reasoning, so a long demo can be slow, and `reflect` (the runbook mental
model) does not fit in that budget at all. The repository's `HINDSIGHT.md` has the measured
numbers; the repair loop itself only needs retain and recall.

## Links

- **Source and full documentation** — https://github.com/1919-14/sre-memory-agent
  (setup, architecture, API reference, and the safety model)
- **API** — `/docs` for the OpenAPI schema, `/api/status` for component health

## Deploying this Space

This Space is a mirror of the `main` branch of the source repository. It is published by
`.github/workflows/hf-space-sync.yml`, which builds the dashboard on the runner and pushes a
single clean commit here. Configure it once:

1. Create a **write** access token at https://huggingface.co/settings/tokens.
2. Add it to the source repository as the secret `HF_TOKEN`
   (*Settings → Secrets and variables → Actions*).
3. Point the workflow at this Space with the repository variable `HF_SPACE`
   (`vssksn/sre-memory-agent`), or leave it unset to use the default in the workflow.

Every push to `main` then redeploys. To publish from a local checkout instead:

```bash
cd web && npm ci && npm run build && cd ..
SPACE=vssksn/sre-memory-agent HF_TOKEN=hf_xxx bash deploy/huggingface/sync.sh
```

Built for **HackWithHyderabad 3.0**.
