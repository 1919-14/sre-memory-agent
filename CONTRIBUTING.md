# Contributing

Thanks for looking at this. This is an SRE agent that investigates failing commits, recalls
comparable past incidents through Hindsight memory, repairs the failure, verifies the repair
in an isolated sandbox, and writes what it learned back to memory.

One thing worth knowing before you start: the agent has a **review gate** that applies this
repository's conventions to every patch it proposes, and it is deliberately strict. The same
rules apply to changes made by people. If a change would be rejected for the agent, expect it
to be rejected in review.

---

## Setup

Requires Python 3.11+ and Node 18+ (Node 24 is what the dashboard is built with).

```bash
python -m venv venv

venv/Scripts/python.exe -m pip install -r requirements.txt     # Windows
# venv/bin/python -m pip install -r requirements.txt           # macOS / Linux

# build the demo repository the agent repairs (four scenario revisions)
venv/Scripts/python.exe scripts/setup_demo_repo.py

# dashboard dependencies
cd web && npm ci
```

Copy `.env.example` to `.env` for local configuration. Nothing in `.env` is committed, and no
contributor should ever need to paste a secret into an issue or a pull request.

---

## Before you open a pull request

```bash
venv/Scripts/python.exe -m pytest                  # full suite (112 tests)
venv/Scripts/python.exe -m pytest -m "not slow"    # fast loop while iterating

cd web && npx tsc --noEmit && npm run build        # dashboard must typecheck and build
```

The suite must be green. Two markers exist and are worth understanding:

| Marker | Meaning |
| --- | --- |
| `slow` | End-to-end runs against the demo repository. Deselect with `-m "not slow"` while iterating, but they must pass before a merge. |
| `live` | Requires a real Groq key and a reachable Hindsight server. **Deselected by default** — CI never needs credentials. |

`pyproject.toml` carries the pytest configuration (`--strict-markers`, asyncio auto mode) and
the ruff settings. If you have ruff installed, `python -m ruff check src tests` uses them.

---

## The rules, in the order they usually bite

These are the review gate's actual rules — they live in `config/conventions.py`, and the agent
applies them literally.

**Every fix must be provable by a test that fails before the change and passes after it.** A
change that makes an existing test pass without a test that demonstrates the bug is not
finished. This is the rule the whole system is built to enforce on itself.

**Never weaken or delete a test to make a suite pass.** `assert True`, `pytest.skip`,
`@pytest.mark.xfail` on a failing test, and loosened assertions are all rejected — by the
policy reviewer and by us. Fix the code, or explain why the test was wrong.

**Never let a failure pass silently.** The sandbox executor encodes two invariants: if the
failure does not reproduce unpatched, the agent must not claim a fix, and a test run that
executed zero tests must never be read as a success. Any change that introduces a new way for
"nothing happened" to look green will be sent back.

**Resource limits belong in configuration, never inline.** Pool sizes, timeouts and retry
counts live in `app/config.py` (demo service) or `src/sre_agent/config.py` (the agent).

**Derive sizing from the thing that consumes it; do not hardcode it.** The demo repository's
canonical bug is exactly this: worker concurrency raised while the Redis pool size was
replaced with a constant. Configuration changes are not an acceptable fix unless the value
itself was wrong.

**Catch specific exceptions.** A bare `except:` is rejected, and so is
`except Exception: pass` — swallowed errors hide production failures.

**No credentials, tokens or environment-specific URLs in code.** An expired credential is not
a code defect; rotate the token rather than extending an expiry constant to make a test pass.

**Keep the change minimal.** No drive-by reformatting, renaming, reordering imports or
refactoring unrelated code in the same change. It makes the diff unreviewable and the agent
cannot review it either.

**No new dependencies without a justification.** Say what it buys and why the standard library
or an existing dependency will not do.

**Migrations and CI workflow files are out of scope for automated fixes.** Changes there are
reviewed by a human, always.

---

## Working on the memory layer

Memory is treated as evidence, not truth, and the interface is deliberately narrow: one module
talks to Hindsight, and everything else consumes plain domain objects.

If you change memory behaviour, these are the invariants that keep recall honest:

- **Tags are the filter, metadata is provenance.** `error-class:`, `component:`, `service:`,
  `outcome:` and `test:` scope recall. Incident ids, commit SHAs and run ids go in metadata,
  because identifiers in the tag space turn recall into exact lookup.
- **`outcome:` is deliberately absent from recall query tags.** Failed incidents must stay
  recallable — remembering what did not work is half the value.
- **Retain is idempotent on `document_id`.** Re-running an incident must update it, not
  duplicate it.
- **Terminal states write memory**, including rollbacks and escalations. If you add a terminal
  state, add its retain.
- **Never fabricate a verdict when memory is unavailable.** If Hindsight is unreachable, or a
  mental model is still being generated, the run is reported as degraded with the reason
  attached. A placeholder string is not content.

Adding a tag or a convention means updating `HINDSIGHT.md` and `config/conventions.py`
respectively, then re-seeding the convention bank from it: `config/conventions.py` is the
source the API reads, and `POST /api/memory/seed` pushes it into Hindsight (run
`scripts/serve.py` and call it, or use the dashboard's *Memory* page). Keep each convention
concrete and mechanically checkable — a rule the reviewer cannot verify becomes noise.

---

## Working on the dashboard

`web/` is React + TypeScript, built to `web/dist` and served by FastAPI at `/`, with the
dashboard under `/app`.

The design system is Swiss International and it is not negotiable: zero border radius, black
borders instead of shadows, uppercase heavy headings, a single accent colour (`#FF3000`) used
only to signal. Use the primitives in `web/src/components/primitives.tsx` and the Tailwind
tokens rather than one-off values. `prefers-reduced-motion` must be respected by any new
animation.

Two conventions that matter more than they look:

- **Never show something as live that is not.** Provenance (live vs replayed, degraded vs
  clean) is carried through every response and rendered. Empty states are honest empty states.
- **Read the real API.** No mock JSON, no placeholder metrics, no invented numbers.

Icons come from Lucide. No emoji in the interface.

---

## Pull requests

- Keep the subject short and specific — the history reads like `fix docker sandbox errors` or
  `landing page at /, dashboard moved under /app, with six real captures of the running
  system`. Say what changed and why; avoid "update" and "fix stuff".
- Say **what you verified**, not just what you changed. For a bug fix, paste the failing test
  before and after. For a memory change, include what was retained and what came back on
  recall.
- One concern per pull request. If you find an unrelated bug, open a separate change.
- Update the docs the change invalidates: `README.md` for behaviour, `HINDSIGHT.md` for memory,
  `PROJECT.md` for design.

---

## Reporting bugs and security issues

Open an issue with the error class, the failing test output, and the configuration that
produced it. Redact tokens and DSNs from anything you paste — Memory Defense redacts on the way
into memory, but that is not a reason to paste a secret into an issue.

For a security problem, please do not open a public issue. Contact a maintainer directly and
give us a chance to fix it first.

---

## Authors and license

Built by **Team Valmiki**:

- Ram Shukla
- V S S K Sai Narayana
- Barkha Rathi
- Anuj Sharma
- Alok Kumar

Contributions are accepted under the MIT License — see [`LICENSE`](LICENSE).
