/**
 * Copy and configuration for the public landing page.
 *
 * Everything here is a statement about what the agent actually does, so it is kept in one
 * place and checked against the implementation. There are deliberately no metrics, customer
 * names or benchmark figures: this page describes a mechanism, not traction.
 */

export const PRODUCT = 'SRE Memory Agent'
export const TAGLINE = 'Incident recovery that remembers.'
export const EYEBROW = 'Autonomous incident recovery'
export const SUPPORTING =
  'An autonomous SRE agent that investigates software failures, recalls relevant ' +
  'experience through Hindsight, safely tests repairs, and learns from every incident.'

/** Where the application lives. `/` is the public page, everything else is a route in here. */
export const APP_PATH = '/app'

/**
 * Build a dashboard route. Links use this instead of writing `/app` by hand, so moving the
 * application to another prefix is one change rather than thirty.
 */
export function appPath(path = ''): string {
  return path ? `${APP_PATH}${path.startsWith('/') ? path : `/${path}`}` : APP_PATH
}

/**
 * The public repository.
 *
 * `VITE_GITHUB_URL` overrides it; the fallback is the repository this project is developed
 * in. Nothing on the page links to a repository that is not configured — set the variable to
 * an empty string to hide every source link.
 */
export const REPO_URL: string | null =
  ((import.meta.env.VITE_GITHUB_URL as string | undefined) ?? '').trim() ||
  'https://github.com/1919-14/sre-memory-agent'

/** The project's own documentation is its README, so that is what "Documentation" means. */
export const DOCS_URL = REPO_URL ? `${REPO_URL}#readme` : null

export const EVENT = 'HackWithHyderabad 3.0'

// ── navigation ────────────────────────────────────────────────

export const NAV_SECTIONS = [
  { to: 'how-it-works', label: 'How it works' },
  { to: 'memory', label: 'Memory' },
  { to: 'architecture', label: 'Architecture' },
]

// ── the loop ──────────────────────────────────────────────────

export interface LoopStep {
  step: string
  title: string
  /** The one-line definition. */
  description: string
  /** How this step is actually implemented, in the project's own terms. */
  detail: string
  /** True where the step reads from or writes to persistent memory. */
  memory?: boolean
}

export const LOOP: LoopStep[] = [
  {
    step: '01',
    title: 'Detect',
    description: 'Identify the incident and collect evidence.',
    detail:
      'Failing tests, stack trace, the commit diff against the last known-good commit, changed files and dependency changes.',
  },
  {
    step: '02',
    title: 'Classify',
    description: 'Determine the failure class before attempting a repair.',
    detail:
      'An error taxonomy — connection-exhaustion, dependency-drift, auth-credential and others. A failure code cannot fix is escalated instead of patched.',
  },
  {
    step: '03',
    title: 'Remember',
    description: 'Search Hindsight for relevant historical incidents and experience.',
    detail:
      'Recall scoped by error class and component, across both banks: past incidents and the repository’s standing conventions.',
    memory: true,
  },
  {
    step: '04',
    title: 'Investigate',
    description: 'Compare the current failure with historical evidence.',
    detail:
      'A comparability judgement. The same symptom with a different root cause is refused, and the refusal is explained rather than hidden.',
  },
  {
    step: '05',
    title: 'Repair',
    description: 'Generate or adapt a candidate fix.',
    detail:
      'Complete file contents, never a hand-written diff. A fix adapted from a remembered incident is tagged with the incident it came from.',
  },
  {
    step: '06',
    title: 'Review',
    description: 'Check the proposed repair against safety rules and engineering conventions.',
    detail:
      'A deterministic policy reviewer — paths, secrets, shell execution, weakened tests — plus an LLM reviewer reading remembered conventions and approaches already rejected.',
  },
  {
    step: '07',
    title: 'Verify',
    description: 'Reproduce the original failure, apply the repair in a sandbox, and run tests.',
    detail:
      'The failure is reproduced unpatched first, then the patch is applied and the targeted tests re-run, then the full suite runs.',
  },
  {
    step: '08',
    title: 'Regress',
    description: 'Check that the repair did not introduce additional failures.',
    detail:
      'Full-suite comparison against a captured baseline. New failures and flaky tests are separated, because a flake is not a regression.',
  },
  {
    step: '09',
    title: 'Recover',
    description:
      'Accept the repair when verification succeeds, or roll back/escalate when it does not.',
    detail:
      'Acceptance only follows a verified fix. Otherwise the repository is restored to the last known-good commit, or the incident is handed to a human.',
  },
  {
    step: '10',
    title: 'Learn',
    description: 'Retain the incident trajectory and outcome for future investigations.',
    detail:
      'The whole trajectory — including the approaches that failed — is written back to Hindsight in every terminal state.',
    memory: true,
  },
]

/** The hero rail: the loop compressed to its seven visible movements. */
export const HERO_STAGES = [
  { label: 'Detect', note: 'Collect evidence' },
  { label: 'Classify', note: 'Name the failure class' },
  { label: 'Remember', note: 'Recall Hindsight' },
  { label: 'Repair', note: 'Generate a candidate fix' },
  { label: 'Verify', note: 'Sandbox the patch' },
  { label: 'Recover', note: 'Accept, roll back or escalate' },
  { label: 'Learn', note: 'Retain the trajectory' },
]

// ── capabilities ──────────────────────────────────────────────

export const CAPABILITIES = [
  {
    title: 'Hindsight memory',
    note: 'Incident trajectories and repository conventions, retained across runs.',
  },
  {
    title: 'FastAPI',
    note: 'One service for the agent and the dashboard; steps stream over SSE as they happen.',
  },
  {
    title: 'Sandboxed repairs',
    note: 'Generated code runs in a container with no network and a non-root user.',
  },
  {
    title: 'Regression verification',
    note: 'Full-suite baseline comparison, not just the test that was failing.',
  },
  {
    title: 'Safe recovery',
    note: 'Rollback to the last known-good commit, with escalation as a valid outcome.',
  },
]

// ── memory ────────────────────────────────────────────────────

export const MEMORY_FLOW = [
  { label: 'Past incident', note: 'Symptom, root cause, every attempt, verification, outcome.' },
  { label: 'Hindsight', note: 'Two banks: this repository’s incidents and its conventions.' },
  { label: 'Relevant experience', note: 'Retrieved by error class and component, with a score.' },
  { label: 'Current incident', note: 'A different failure that looks similar — or does not.' },
  {
    label: 'Adapt / reject',
    note: 'The comparable fix is adapted; the non-comparable one is refused with a reason.',
  },
  { label: 'Verify', note: 'Evidence is a hypothesis until the sandbox reproduces and passes it.' },
]

export const FIRST_INCIDENT = [
  'Failure detected',
  'No comparable experience',
  'Investigate',
  'Generate repair',
  'Verify',
  'Recover',
  'Store outcome',
]

export const SIMILAR_INCIDENT = [
  'Failure detected',
  'Historical experience found',
  'Compare evidence',
  'Adapt previous repair',
  'Verify',
  'Recover',
  'Store outcome',
]

// ── failure handling ──────────────────────────────────────────

export const FAILURE_FLOW = [
  { label: 'Repair attempt', note: 'A candidate patch, validated before anything executes.' },
  { label: 'Verification', note: 'Reproduce unpatched, apply, re-test, run the full suite.' },
  { label: 'Failed', note: 'The original failure persists, or the full suite regresses.' },
  { label: 'Rollback', note: 'The repository is restored to the last known-good commit.' },
  { label: 'Escalate', note: 'The incident is handed to a human, with its trajectory attached.' },
]

// ── principles ────────────────────────────────────────────────

export type PrincipleIcon = 'memory' | 'review' | 'test' | 'regression' | 'recovery'

export const PRINCIPLES: {
  title: string
  note: string
  icon: PrincipleIcon
}[] = [
  {
    title: 'Memory is evidence',
    note: 'Historical solutions are evaluated before reuse, never replayed on sight.',
    icon: 'memory',
  },
  {
    title: 'Repairs are reviewed',
    note: 'A candidate change passes a policy and conventions gate before anything runs.',
    icon: 'review',
  },
  {
    title: 'Fixes are tested',
    note: 'The failure is reproduced unpatched, then patched and re-tested in a sandbox.',
    icon: 'test',
  },
  {
    title: 'Regressions matter',
    note: 'Passing the original test is not enough; the full suite is compared against a baseline.',
    icon: 'regression',
  },
  {
    title: 'Recovery is controlled',
    note: 'A failed repair rolls back rather than declaring success, and escalating is a result.',
    icon: 'recovery',
  },
]

// ── screenshots ───────────────────────────────────────────────

/**
 * Where the screenshot files are read from.
 *
 * Locally — and on any deployment that carries the files — they are served from the build's own
 * `/screenshots` directory. A Hugging Face Space does not carry binaries: `sync.sh` strips them
 * from the snapshot, and the workflow builds the dashboard with `VITE_SCREENSHOT_BASE` pointing
 * at the source repository's raw path, so the Space reads them from GitHub instead.
 */
export const SCREENSHOT_BASE: string =
  ((import.meta.env.VITE_SCREENSHOT_BASE as string | undefined) ?? '').trim() || '/screenshots'

/** Tried when this deployment does not serve the files itself. */
export const SCREENSHOT_FALLBACK_BASE: string | null = REPO_URL
  ? `${REPO_URL}/raw/main/web/public/screenshots`
  : null

export interface Screenshot {
  /** File name without the extension, under `web/public/screenshots`. */
  name: string
  /** The route the screen is served at, used as the slide's label. */
  route: string
  title: string
  caption: string
  alt: string
  width: number
  height: number
}

/**
 * The six captured screens. Each caption describes what that screen is for; the values in the
 * images are from the run that produced them, which is why the page says so next to them.
 */
export const SCREENSHOTS: Screenshot[] = [
  {
    name: 'overview',
    route: '/app',
    title: 'Overview',
    caption:
      'Dependency health, the recorded performance figures, the latest incident and the live activity stream.',
    alt: 'The dashboard overview: a status strip for the agent, memory, LLM and sandbox, a system status panel, recorded performance metrics and the live activity stream.',
    width: 1440,
    height: 681,
  },
  {
    name: 'overview-system-status',
    route: '/app — system status',
    title: 'Every dependency, and why',
    caption:
      'Hindsight memory, the LLM provider, the sandbox and the repository, each with the reason it is limited when it is — not one unexplained “degraded”.',
    alt: 'The system status panel: a card per dependency with a status word and the sentence explaining it.',
    width: 1440,
    height: 685,
  },
  {
    name: 'incidents',
    route: '/app/incidents',
    title: 'Incidents',
    caption:
      'The demonstration scenarios, the recorded trajectories available for replay, and the full history with search, outcome filter and sort.',
    alt: 'The incidents screen: scenario cards for the demonstration failures above a sortable table of past incidents.',
    width: 1440,
    height: 681,
  },
  {
    name: 'incident',
    route: '/app/incidents/:id',
    title: 'One investigation',
    caption:
      'A single incident as a numbered timeline — detected, classified, remembered, compared, repaired, reviewed, sandboxed, regression-checked, recovered, learned — with the real evidence behind each step.',
    alt: 'An incident investigation page: numbered timeline stages from detection to learning, each with its status and a summary line, above the recorded evidence.',
    width: 1440,
    height: 681,
  },
  {
    name: 'memory',
    route: '/app/memory',
    title: 'Memory',
    caption:
      'Both Hindsight banks, tag-scoped search, the conventions the review gate enforces, and the runbook the agent maintains for itself.',
    alt: 'The memory screen: the incident and convention banks, a search field, and the service runbook.',
    width: 1440,
    height: 681,
  },
  {
    name: 'learning',
    route: '/app/learning',
    title: 'Learning',
    caption:
      'Attempts per incident over time, recall versus reuse, and whether the effort each incident costs is falling as memory fills.',
    alt: 'The learning screen: attempts per incident drawn as labelled columns, with totals for memories recalled, fixes reused and approaches avoided.',
    width: 1440,
    height: 682,
  },
]

// ── stack ─────────────────────────────────────────────────────

export const STACK = [
  'React 18 · TypeScript · Vite · Tailwind',
  'FastAPI · Python 3.12 · SSE',
  'Hindsight · incident + convention memory',
  'SQLite · incident record',
  'Docker · pytest · sandboxed execution',
  'Groq · OpenAI-compatible LLM API',
]
