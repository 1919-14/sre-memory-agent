import { ArrowUpRight, BookOpen, Github, Menu, Play, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { InstanceStrip, MemoryPreview, ProductPreview } from '../components/LandingPreview'
import { ScreenshotSlideshow } from '../components/LandingSlides'
import {
  ActionLink,
  ArchitectureDiagram,
  BlockLabel,
  CapabilityStrip,
  ComparisonColumns,
  LoopGrid,
  PrincipleGrid,
  Reveal,
  Section,
  StackList,
  StageRail,
} from '../components/LandingVisuals'
import { Panel } from '../components/primitives'
import {
  APP_PATH,
  DOCS_URL,
  EYEBROW,
  FAILURE_FLOW,
  HERO_STAGES,
  MEMORY_FLOW,
  NAV_SECTIONS,
  PRODUCT,
  REPO_URL,
  SUPPORTING,
  TAGLINE,
} from '../lib/site'

/**
 * The public page at `/`.
 *
 * It is deliberately not a second dashboard: it explains the mechanism, shows the real
 * interface reading the real deployment, and hands the visitor to the application. Nothing
 * here is a fabricated metric — the live panels are the product, and where there is nothing
 * to show the page says so.
 */
export default function Landing() {
  return (
    <div id="top" className="min-h-screen bg-paper swiss-noise">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:bg-ink focus:px-4 focus:py-2 focus:text-paper"
      >
        Skip to content
      </a>

      <LandingNav />

      <main id="main">
        <Hero />
        <CapabilityStrip />

        <Section
          index="01."
          label="The problem"
          heading="Most incident automation forgets."
          lede="A failure may be resolved today, only for the same class of incident to appear again weeks later."
        >
          <div className="grid gap-10 lg:grid-cols-12">
            <div className="space-y-5 lg:col-span-6">
              <p className="max-w-2xl text-lead text-ink">
                Traditional automation can execute a predefined runbook. What is harder to reuse
                systematically is the investigation itself: which approaches were tried and
                rejected, what the root cause turned out to be, and why the accepted fix was
                accepted at all.
              </p>
              <p className="max-w-2xl text-meta text-status-idle">
                The evidence of a resolved incident does exist — it is simply spread across the
                alert, the pull request and the memory of whoever was on call. The next engineer
                to meet the same failure re-derives all of it.
              </p>
            </div>

            <div className="lg:col-span-6">
              <BlockLabel>What a resolved incident leaves behind</BlockLabel>
              <ul className="border-2 border-ink bg-paper">
                {[
                  { left: 'Symptom, stack trace, failing tests', right: 'The alert that fired' },
                  { left: 'Root cause and the accepted fix', right: 'The pull request' },
                  {
                    left: 'Approaches that were tried and failed',
                    right: 'Nowhere the next run can read',
                  },
                ].map((row, index) => (
                  <li
                    key={row.left}
                    className={`flex flex-wrap items-baseline justify-between gap-x-8 gap-y-1 px-5 py-4 ${
                      index > 0 ? 'border-t-2 border-hair' : ''
                    }`}
                  >
                    <span className="text-meta text-ink">{row.left}</span>
                    <span className="text-label font-black uppercase tracking-widest text-status-idle">
                      {row.right}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Section>

        <Section
          id="how-it-works"
          index="02."
          label="The loop"
          heading="From failure to learned recovery."
          lede="Ten steps, in order. A review gate and a sandbox sit between a proposed repair and anything being accepted."
        >
          <LoopGrid />
          <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-2xl text-meta text-status-idle">
              Steps 03 and 10 are the only ones that touch persistent memory: recall before the
              repair, retention after the outcome.
            </p>
            <Link
              to={`${APP_PATH}/incidents`}
              className="inline-flex items-center gap-1.5 text-label font-bold uppercase tracking-widest text-ink transition-colors duration-150 ease-linear hover:text-accent"
            >
              Follow the loop on a real incident
              <ArrowUpRight size={12} strokeWidth={3} aria-hidden />
            </Link>
          </div>
        </Section>

        <Section
          id="memory"
          index="03."
          label="Memory"
          heading="Give incident response a memory."
          lede="When a new failure appears, the agent searches previous incidents, evaluates whether the historical experience applies, and uses it as evidence for the current repair."
          tone="muted"
        >
          <BlockLabel>How a memory becomes evidence</BlockLabel>
          <StageRail nodes={MEMORY_FLOW} numbered={false} />

          <div className="mt-8 grid gap-6 lg:grid-cols-12 lg:gap-8">
            <div className="border-2 border-accent bg-paper p-6 lg:col-span-5">
              <p className="text-label font-black uppercase tracking-widest text-accent">
                Product principle
              </p>
              <p className="mt-3 text-h2">Memory is evidence, not truth.</p>
              <p className="mt-4 text-meta text-status-idle">
                A recalled repair is a hypothesis about this incident. It is accepted only after
                the comparability check and the sandbox agree — and a refusal is recorded and
                shown, not silently discarded.
              </p>
            </div>

            <div className="lg:col-span-7">
              <BlockLabel>What is actually stored</BlockLabel>
              <ul className="border-2 border-ink bg-paper">
                {[
                  {
                    title: 'Incident memory',
                    note: 'Evidence, root cause, every attempt including the ones that failed, verification and outcome.',
                  },
                  {
                    title: 'Convention memory',
                    note: 'The repository’s standing rules, review findings, and approaches already rejected.',
                  },
                  {
                    title: 'The runbook',
                    note: 'A standing answer to which failure modes recur here and which fixes actually worked.',
                  },
                ].map((row, index) => (
                  <li
                    key={row.title}
                    className={`px-5 py-4 ${index > 0 ? 'border-t-2 border-hair' : ''}`}
                  >
                    <h3 className="text-meta font-black uppercase tracking-widest text-ink">
                      {row.title}
                    </h3>
                    <p className="mt-1.5 text-micro text-status-idle">{row.note}</p>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Section>

        <Section
          index="04."
          label="The difference"
          heading="The second incident is different."
          lede="Memory changes what happens next only when the historical experience is comparable. When it is not, the agent says so and starts over."
        >
          <ComparisonColumns />
          <div className="mt-8 grid gap-6 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <Panel className="p-6">
                <h3 className="text-meta font-black uppercase tracking-widest text-ink">
                  The case that keeps the agent honest
                </h3>
                <p className="mt-3 max-w-2xl text-meta text-status-idle">
                  The demonstration service fails twice with the same message — a connection pool
                  exhausted — for two different reasons: one revision hardcodes a pool size, the
                  next leaks a connection on the retry path. A memory agent that replays its
                  previous fix gets the second incident wrong, so the agent recalls the first
                  repair, judges it non-comparable, refuses it with a reason, and generates a new
                  one.
                </p>
              </Panel>
            </div>
            <div className="lg:col-span-5">
              <Panel className="h-full p-6">
                <h3 className="text-meta font-black uppercase tracking-widest text-ink">
                  Recorded on that judgement
                </h3>
                <ul className="mt-3 space-y-3">
                  {[
                    'Whether a prior incident was comparable, and at what confidence',
                    'Which fields matched and which argued against reuse',
                    'The approaches already shown to fail, carried into the next repair',
                  ].map((line) => (
                    <li key={line} className="flex items-start gap-2 text-micro text-status-idle">
                      <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 bg-accent" />
                      {line}
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>
          </div>
        </Section>

        <Section
          index="05."
          label="Failure"
          heading="A failed repair is not a successful repair."
          lede="The agent does not treat a generated patch as correct because it was generated. Repairs are tested against the original failure and checked for regressions — and when one fails, the system rolls back rather than declaring success."
          tone="muted"
        >
          <BlockLabel>When verification says no</BlockLabel>
          <StageRail nodes={FAILURE_FLOW} />

          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            <Panel className="p-6">
              <h3 className="text-meta font-black uppercase tracking-widest text-ink">
                What stops a bad patch
              </h3>
              <ul className="mt-4 space-y-4">
                {[
                  {
                    title: 'Deterministic validation',
                    note: 'Path allowlist and denylist, traversal rejection, size caps, secret detection — before anything executes.',
                  },
                  {
                    title: 'The review gate',
                    note: 'Critical findings block execution: hardcoded credentials, shell execution, destructive operations, skipped or weakened tests.',
                  },
                  {
                    title: 'Reproduce first',
                    note: 'The failure must reproduce unpatched, so a fix cannot be “verified” by a test run that executed nothing.',
                  },
                ].map((item) => (
                  <li key={item.title} className="border-t-2 border-hair pt-4 first:border-t-0 first:pt-0">
                    <h4 className="text-meta font-black uppercase tracking-widest text-ink">
                      {item.title}
                    </h4>
                    <p className="mt-1.5 text-micro text-status-idle">{item.note}</p>
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel className="p-6">
              <h3 className="text-meta font-black uppercase tracking-widest text-ink">
                What happens when it fails anyway
              </h3>
              <ul className="mt-4 space-y-4">
                {[
                  {
                    title: 'Rollback',
                    note: 'The repository is restored to the last known-good commit, optionally behind an administrator approval.',
                  },
                  {
                    title: 'Escalation',
                    note: 'A failure no patch can fix — an expired credential, an infrastructure outage — is handed to a human instead of being patched.',
                  },
                  {
                    title: 'Retention',
                    note: 'The failed attempt is written to memory, so the next run does not repeat it.',
                  },
                ].map((item) => (
                  <li key={item.title} className="border-t-2 border-hair pt-4 first:border-t-0 first:pt-0">
                    <h4 className="text-meta font-black uppercase tracking-widest text-ink">
                      {item.title}
                    </h4>
                    <p className="mt-1.5 text-micro text-status-idle">{item.note}</p>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
        </Section>

        <Section
          index="06."
          label="The live system"
          heading="Watch it recover an incident."
          lede="Run a controlled incident and follow the complete investigation in real time — from detection and memory recall to repair, verification, regression testing and recovery."
        >
          <Panel className="grid gap-8 p-6 lg:grid-cols-12 lg:p-8">
            <div className="lg:col-span-7">
              <h3 className="text-h2">Run it, do not take our word for it.</h3>
              <p className="mt-4 max-w-xl text-lead text-status-idle">
                The dashboard runs the incident against the demonstration service and streams
                every step over SSE as it happens. There is no recorded video and no scripted
                replay behind this button.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <ActionLink to={APP_PATH} icon={Play}>
                  Run live demo
                </ActionLink>
                <ActionLink to={`${APP_PATH}/memory`} variant="secondary">
                  Inspect memory instead
                </ActionLink>
              </div>
            </div>
            <ol className="lg:col-span-5">
              {[
                {
                  title: 'Run the scenario once',
                  note: 'A cold memory bank: the agent investigates, repairs and verifies, then stores the trajectory.',
                },
                {
                  title: 'Run the same failure again',
                  note: 'Recall fires. The panel shows whether the earlier repair was reused, adapted or refused.',
                },
                {
                  title: 'Compare the two runs',
                  note: 'Attempts, duration and memories reused are computed from stored incidents, never estimated.',
                },
              ].map((step, index) => (
                <li key={step.title} className="flex gap-4 py-4 first:pt-0">
                  <span className="font-mono text-micro font-bold tabular text-accent">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <div>
                    <h4 className="text-meta font-black uppercase tracking-widest text-ink">
                      {step.title}
                    </h4>
                    <p className="mt-1.5 text-micro text-status-idle">{step.note}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Panel>
        </Section>

        <Section
          index="07."
          label="Memory, recorded"
          heading="What the agent remembers."
          lede="Read straight from the running deployment: the banks, the counters and the records themselves. If nothing has been stored yet, this section says that instead of showing something that was not."
          tone="muted"
        >
          <Reveal>
            <MemoryPreview />
          </Reveal>
        </Section>

        <Section
          id="architecture"
          index="08."
          label="Architecture"
          heading="One service, one memory layer, one sandbox."
          lede="The dashboard is static assets served by the API at the same origin. The agent runs in the service; generated code never runs anywhere but the sandbox."
        >
          <BlockLabel>How the parts connect</BlockLabel>
          <ArchitectureDiagram />
          <div className="mt-8">
            <BlockLabel>In use</BlockLabel>
            <StackList />
          </div>
        </Section>

        <Section
          index="09."
          label="Principles"
          heading="Built around verification."
          lede="Five properties the loop is designed to preserve, in the order a repair passes through them."
          tone="muted"
        >
          <PrincipleGrid />
        </Section>

        <Section
          index="10."
          label="The product"
          heading="Six screens, captured from a running deployment."
          lede="The product is the interface, so these are captures of the dashboard itself, labelled with the route each one comes from. The values in them belong to the run that produced them; the live panels above read the deployment you are looking at."
        >
          <Reveal>
            <ScreenshotSlideshow />
          </Reveal>
          <p className="mt-6 max-w-3xl text-micro text-status-idle">
            Captured at 1917×907 and published at 1440px wide.
            <code className="mx-1 font-mono">web/scripts/capture-screenshots.mjs</code>
            re-captures them from any deployment — including the remaining screens of an
            investigation: repairs, review, sandbox and regression.
          </p>
        </Section>

        <Section
          index="11."
          label="The record"
          heading="The record, not a rendering of it."
          lede="Every panel below is rendered live from an incident stored on this deployment, using the same components the dashboard uses — the real diff, the real test reports, the real retrieved memory."
          tone="muted"
        >
          <Reveal>
            <ProductPreview />
          </Reveal>
        </Section>

        <FinalCta />
      </main>

      <LandingFooter />
    </div>
  )
}

// ── navigation ────────────────────────────────────────────────

function LandingNav() {
  const [open, setOpen] = useState(false)

  return (
    <header className="sticky top-0 z-40 border-b-2 border-ink bg-paper">
      <div className="mx-auto flex w-full max-w-[1400px] items-center justify-between gap-4 px-5 sm:px-8">
        <a href="#top" className="flex shrink-0 items-center gap-2 py-3">
          <span aria-hidden className="grid h-6 w-6 place-items-center bg-ink">
            <span className="h-2.5 w-2.5 bg-accent" />
          </span>
          <span className="text-meta font-black uppercase tracking-tight">{PRODUCT}</span>
        </a>

        <div className="flex items-center gap-2">
          <nav aria-label="Page sections" className="hidden items-center lg:flex">
            {NAV_SECTIONS.map((section) => (
              <a
                key={section.to}
                href={`#${section.to}`}
                className="px-4 py-3 text-meta font-bold uppercase tracking-wide text-ink transition-colors duration-150 ease-linear hover:bg-muted"
              >
                {section.label}
              </a>
            ))}
          </nav>

          {REPO_URL ? (
            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer noopener"
              className="hidden items-center gap-1.5 px-3 py-3 text-meta font-bold uppercase tracking-wide text-ink transition-colors duration-150 ease-linear hover:text-accent lg:flex"
            >
              <Github size={14} strokeWidth={2.5} aria-hidden />
              GitHub
            </a>
          ) : null}

          <Link
            to={APP_PATH}
            className="hidden items-center gap-2 border-2 border-ink bg-ink px-4 py-2 text-label font-black uppercase tracking-widest text-paper transition-colors duration-150 ease-linear hover:border-accent hover:bg-accent lg:inline-flex"
          >
            Open live system
            <ArrowUpRight size={12} strokeWidth={3} aria-hidden />
          </Link>

          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls="landing-menu"
            aria-label={open ? 'Close navigation' : 'Open navigation'}
            className="inline-flex h-9 w-9 items-center justify-center border-2 border-ink text-ink lg:hidden"
          >
            {open ? <X size={16} strokeWidth={2.5} aria-hidden /> : <Menu size={16} strokeWidth={2.5} aria-hidden />}
          </button>
        </div>
      </div>

      {open ? (
        <nav id="landing-menu" aria-label="Page sections" className="animate-fade-rise border-t-2 border-ink lg:hidden">
          <ul>
            {NAV_SECTIONS.map((section) => (
              <li key={section.to} className="border-b-2 border-hair">
                <a
                  href={`#${section.to}`}
                  onClick={() => setOpen(false)}
                  className="block px-5 py-3 text-meta font-bold uppercase tracking-wide text-ink"
                >
                  {section.label}
                </a>
              </li>
            ))}
            {REPO_URL ? (
              <li className="border-b-2 border-hair">
                <a
                  href={REPO_URL}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="block px-5 py-3 text-meta font-bold uppercase tracking-wide text-ink"
                >
                  GitHub
                </a>
              </li>
            ) : null}
            <li>
              <Link
                to={APP_PATH}
                onClick={() => setOpen(false)}
                className="block bg-ink px-5 py-3 text-meta font-bold uppercase tracking-wide text-paper"
              >
                Open live system
              </Link>
            </li>
          </ul>
        </nav>
      ) : null}
    </header>
  )
}

// ── hero ──────────────────────────────────────────────────────

function Hero() {
  return (
    <section aria-labelledby="hero-heading" className="border-b-2 border-ink">
      <div className="mx-auto w-full max-w-[1400px] px-5 sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-ink py-3">
          <span className="inline-flex items-center gap-2 text-label font-black uppercase tracking-widest text-ink">
            <span aria-hidden className="h-2 w-2 bg-accent" />
            {EYEBROW}
          </span>
          <span className="font-mono text-micro text-status-idle">SRE / incident response</span>
        </div>

        <div className="py-12 lg:py-18">
          <h1 id="hero-heading" className="max-w-5xl text-balance text-h1 sm:text-display">
            Incident recovery that remembers.
          </h1>
          <p className="mt-6 max-w-2xl text-lead text-status-idle">{SUPPORTING}</p>

          <div className="mt-8 flex flex-wrap gap-3">
            <ActionLink to={APP_PATH} icon={Play}>
              Explore live demo
            </ActionLink>
            {REPO_URL ? (
              <ActionLink href={REPO_URL} variant="secondary" icon={Github}>
                View GitHub
              </ActionLink>
            ) : null}
          </div>
          <p className="mt-4 text-micro text-status-idle">
            The demo opens the live system: incidents, memory, repairs, review, sandbox and
            learning.
          </p>
        </div>

        <div className="pb-14">
          <BlockLabel>The loop as the system runs it</BlockLabel>
          <StageRail nodes={HERO_STAGES} />
          <div className="mt-6">
            <InstanceStrip />
          </div>
        </div>
      </div>
    </section>
  )
}

// ── closing ───────────────────────────────────────────────────

function FinalCta() {
  return (
    <section className="border-t-2 border-ink bg-paper">
      <div className="mx-auto w-full max-w-[1400px] px-5 py-16 sm:px-8 lg:py-24">
        <Reveal>
          <h2 className="max-w-4xl text-balance text-h1">
            Give your incident response a memory.
          </h2>
          <p className="mt-5 max-w-2xl text-lead text-status-idle">
            Explore the live system and watch an incident move from failure to verified recovery —
            then watch the same failure meet a memory of itself.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ActionLink to={APP_PATH} icon={Play}>
              Explore live demo
            </ActionLink>
            {REPO_URL ? (
              <ActionLink href={REPO_URL} variant="secondary" icon={Github}>
                View source
              </ActionLink>
            ) : null}
          </div>
        </Reveal>
      </div>
    </section>
  )
}

function LandingFooter() {
  return (
    <footer className="border-t-2 border-ink bg-ink text-paper">
      <div className="mx-auto w-full max-w-[1400px] px-5 py-12 sm:px-8">
        <div className="grid gap-10 lg:grid-cols-12">
          <div className="lg:col-span-6">
            <div className="flex items-center gap-2">
              <span aria-hidden className="grid h-6 w-6 place-items-center bg-paper">
                <span className="h-2.5 w-2.5 bg-accent" />
              </span>
              <span className="text-meta font-black uppercase tracking-tight">{PRODUCT}</span>
            </div>
            <p className="mt-3 text-lead text-paper">{TAGLINE}</p>
            <p className="mt-4 max-w-md text-micro text-paper/70">
              Every figure on this page comes from the running deployment. Nothing here is a
              placeholder, a projection or a benchmark.
            </p>
          </div>

          <nav aria-label="Footer" className="lg:col-span-3">
            <h2 className="text-label font-black uppercase tracking-widest text-paper/70">
              This project
            </h2>
            <ul className="mt-4 space-y-3">
              <li>
                <Link
                  to={APP_PATH}
                  className="inline-flex items-center gap-1.5 text-meta font-bold uppercase tracking-wide text-paper transition-colors duration-150 ease-linear hover:text-accent"
                >
                  Live demo
                  <ArrowUpRight size={12} strokeWidth={3} aria-hidden />
                </Link>
              </li>
              {REPO_URL ? (
                <li>
                  <a
                    href={REPO_URL}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1.5 text-meta font-bold uppercase tracking-wide text-paper transition-colors duration-150 ease-linear hover:text-accent"
                  >
                    GitHub
                    <ArrowUpRight size={12} strokeWidth={3} aria-hidden />
                  </a>
                </li>
              ) : null}
              {DOCS_URL ? (
                <li>
                  <a
                    href={DOCS_URL}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1.5 text-meta font-bold uppercase tracking-wide text-paper transition-colors duration-150 ease-linear hover:text-accent"
                  >
                    <BookOpen size={13} strokeWidth={2.5} aria-hidden />
                    Documentation
                  </a>
                </li>
              ) : null}
            </ul>
          </nav>

          <div className="lg:col-span-3">
            <h2 className="text-label font-black uppercase tracking-widest text-paper/70">Built with</h2>
            <p className="mt-4 text-meta font-bold uppercase tracking-wide text-paper">
              Hindsight agent memory
            </p>
            <p className="mt-4 text-micro text-paper/70">
              Sandboxed repairs · regression verification · auditable rollback
            </p>
          </div>
        </div>
      </div>
    </footer>
  )
}
