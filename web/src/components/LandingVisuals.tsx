import {
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Database,
  FlaskConical,
  GitCompareArrows,
  ShieldCheck,
  Undo2,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import {
  CAPABILITIES,
  FIRST_INCIDENT,
  LOOP,
  PRINCIPLES,
  SIMILAR_INCIDENT,
  STACK,
  type PrincipleIcon,
} from '../lib/site'

// ── motion ────────────────────────────────────────────────────

/**
 * Reveal a block when it first enters the viewport.
 *
 * The element is present and readable in the document the whole time — this only sets an
 * attribute that CSS transitions on — so nothing on the page depends on JavaScript having
 * run, and `prefers-reduced-motion` resolves it to the final state in CSS.
 */
export function Reveal({ children, className = '' }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node || typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return undefined
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: '0px 0px -10% 0px', threshold: 0.05 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={ref} data-visible={visible} className={`reveal ${className}`}>
      {children}
    </div>
  )
}

// ── actions ───────────────────────────────────────────────────

/**
 * A call to action that is a link, not a button.
 *
 * Navigation must stay navigation: keyboard users, middle-click and "open in new tab" all
 * work, and the element announces itself as a link.
 */
export function ActionLink({
  to,
  href,
  children,
  variant = 'primary',
  icon: Icon,
  className = '',
}: {
  to?: string
  href?: string
  children: ReactNode
  variant?: 'primary' | 'secondary' | 'accent'
  icon?: LucideIcon
  className?: string
}) {
  const base =
    'inline-flex items-center justify-center gap-2 border-2 px-5 py-3 text-meta font-bold uppercase tracking-wide transition-colors duration-150 ease-linear'
  const styles = {
    primary: 'border-ink bg-ink text-paper hover:border-accent hover:bg-accent',
    secondary: 'border-ink bg-paper text-ink hover:bg-ink hover:text-paper',
    accent: 'border-accent bg-accent text-paper hover:border-ink hover:bg-ink',
  }[variant]
  const body = (
    <>
      {Icon ? <Icon size={15} strokeWidth={2.5} aria-hidden /> : null}
      {children}
    </>
  )

  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener" className={`${base} ${styles} ${className}`}>
        {body}
      </a>
    )
  }

  return (
    <Link to={to ?? '/'} className={`${base} ${styles} ${className}`}>
      {body}
    </Link>
  )
}

// ── layout ────────────────────────────────────────────────────

/** One numbered editorial section: `01. THE PROBLEM`, a heading, a lede and its content. */
export function Section({
  id,
  index,
  label,
  heading,
  lede,
  children,
  tone = 'paper',
}: {
  id?: string
  index: string
  label: string
  heading: string
  lede?: string
  children: ReactNode
  tone?: 'paper' | 'muted'
}) {
  return (
    <section
      id={id}
      className={`scroll-mt-20 border-t-2 border-ink ${tone === 'muted' ? 'bg-muted' : 'bg-paper'}`}
    >
      <div className="mx-auto w-full max-w-[1400px] px-5 py-14 sm:px-8 lg:py-20">
        <Reveal>
          <div className="flex items-baseline gap-3 text-label font-black uppercase tracking-widest">
            <span className="text-accent">{index}</span>
            <span className="text-ink">{label}</span>
          </div>
          <div className="mt-6 grid gap-x-12 gap-y-4 lg:grid-cols-12">
            <h2 className="text-balance text-h1 lg:col-span-7">{heading}</h2>
            {lede ? (
              <p className="max-w-xl text-lead text-status-idle lg:col-span-5 lg:pt-1.5">{lede}</p>
            ) : null}
          </div>
        </Reveal>
        <div className="mt-10 lg:mt-14">{children}</div>
      </div>
    </section>
  )
}

/** A labelled sub-block inside a section, e.g. a diagram with its own caption rule. */
export function BlockLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 flex items-center gap-3">
      <span className="text-label font-black uppercase tracking-widest text-status-idle">
        {children}
      </span>
      <span aria-hidden className="h-0.5 flex-1 bg-hair-strong" />
    </div>
  )
}

// ── hero ──────────────────────────────────────────────────────

/** The pipeline rail: numbered stages, separated by rules, with the flow made explicit. */
export function StageRail({
  nodes,
  numbered = true,
}: {
  nodes: { label: string; note?: string }[]
  numbered?: boolean
}) {
  return (
    <ol className="border-2 border-ink bg-paper lg:flex">
      {nodes.map((node, index) => {
        const last = index === nodes.length - 1
        return (
          <li
            key={node.label}
            className={`relative px-5 py-5 lg:min-w-0 lg:flex-1 ${
              index > 0 ? 'border-t-2 border-ink lg:border-l-2 lg:border-t-0' : ''
            } ${last ? '' : 'lg:pr-7'}`}
          >
            {numbered ? (
              <div className="font-mono text-micro font-bold tabular text-accent">
                {String(index + 1).padStart(2, '0')}
              </div>
            ) : null}
            <h3 className={`text-h3 ${numbered ? 'mt-2' : ''}`}>{node.label}</h3>
            {node.note ? <p className="mt-1.5 text-micro text-status-idle">{node.note}</p> : null}
            {last ? null : (
              <>
                <ChevronRight
                  size={13}
                  strokeWidth={3}
                  aria-hidden
                  className="absolute right-1.5 top-5 hidden text-status-idle lg:block"
                />
                <ChevronDown
                  size={13}
                  strokeWidth={3}
                  aria-hidden
                  className="mt-3 text-status-idle lg:hidden"
                />
              </>
            )}
          </li>
        )
      })}
    </ol>
  )
}

// ── capability strip ──────────────────────────────────────────

export function CapabilityStrip() {
  return (
    <section aria-label="Built with" className="border-t-2 border-ink bg-paper">
      <ul className="mx-auto grid w-full max-w-[1400px] grid-cols-1 gap-px bg-hair sm:grid-cols-2 lg:grid-cols-5">
        {CAPABILITIES.map((capability) => (
          <li key={capability.title} className="bg-paper px-5 py-5 lg:px-6">
            <h3 className="text-label font-black uppercase tracking-widest text-ink">
              {capability.title}
            </h3>
            <p className="mt-2 text-micro text-status-idle">{capability.note}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ── the loop ──────────────────────────────────────────────────

export function LoopGrid() {
  return (
    <div className="border-2 border-ink bg-paper">
      <div className="grid grid-cols-1 gap-px bg-hair sm:grid-cols-2 lg:grid-cols-5">
        {LOOP.map((step) => (
          <article key={step.step} className="flex flex-col bg-paper px-5 py-5">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-micro font-bold tabular text-accent">{step.step}</span>
              {step.memory ? (
                <span className="inline-flex items-center gap-1.5 text-label font-black uppercase tracking-widest text-ink">
                  <span aria-hidden className="h-2 w-2 bg-accent" />
                  Memory
                </span>
              ) : null}
            </div>
            <h3 className="mt-3 text-h3">{step.title}</h3>
            <p className="mt-2 text-meta text-ink">{step.description}</p>
            <p className="mt-auto border-t-2 border-hair pt-3 text-micro text-status-idle">
              {step.detail}
            </p>
          </article>
        ))}
      </div>
    </div>
  )
}

// ── the difference memory makes ───────────────────────────────

export function ComparisonColumns() {
  return (
    <div className="border-2 border-ink bg-paper">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto_1fr]">
        <IncidentColumn title="First incident" rows={FIRST_INCIDENT} />
        <div className="flex items-center justify-center border-y-2 border-ink bg-muted px-4 py-3 lg:border-x-2 lg:border-y-0 lg:px-0 lg:py-6 lg:[writing-mode:vertical-rl]">
          <span className="text-label font-black uppercase tracking-widest text-ink lg:rotate-180">
            Hindsight
          </span>
        </div>
        <IncidentColumn title="Similar incident" rows={SIMILAR_INCIDENT} />
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t-2 border-ink px-5 py-3">
        <span className="inline-flex items-center gap-2 text-label font-black uppercase tracking-widest text-status-idle">
          <span aria-hidden className="h-1.5 w-1.5 bg-status-idle" />
          Same step
        </span>
        <span className="inline-flex items-center gap-2 text-label font-black uppercase tracking-widest text-ink">
          <span aria-hidden className="h-1.5 w-1.5 bg-accent" />
          Changed by memory
        </span>
      </div>
    </div>
  )
}

function IncidentColumn({ title, rows }: { title: string; rows: string[] }) {
  return (
    <div>
      <div className="border-b-2 border-ink px-5 py-3 text-label font-black uppercase tracking-widest text-ink">
        {title}
      </div>
      <ol>
        {rows.map((row, index) => {
          const changed = row !== FIRST_INCIDENT[index] || row !== SIMILAR_INCIDENT[index]
          return (
            <li
              key={row}
              className="flex items-baseline gap-3 border-b-2 border-hair px-5 py-3 last:border-b-0"
            >
              <span className="font-mono text-micro tabular text-status-idle">
                {String(index + 1).padStart(2, '0')}
              </span>
              <span
                aria-hidden
                className={`inline-block h-1.5 w-1.5 shrink-0 ${changed ? 'bg-accent' : 'bg-status-idle'}`}
              />
              <span className={`text-meta ${changed ? 'font-bold text-ink' : 'text-status-idle'}`}>
                {row}
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

// ── architecture ──────────────────────────────────────────────

const ARCH_ROWS: { title: string; note: string; lane?: string }[] = [
  { title: 'Dashboard', note: 'React 18 + TypeScript, built to static assets and served by the API' },
  { title: 'FastAPI service', note: 'REST for reads, Server-Sent Events for the live trajectory' },
  {
    title: 'Incident engine',
    note: 'Evidence, classification, comparability, repair generation, orchestration',
    lane: 'recall',
  },
  { title: 'Review gate', note: 'Deterministic policy findings plus conventions from memory' },
  { title: 'Sandbox execution', note: 'Docker container (no network, non-root) or a temporary workspace' },
  { title: 'Verification + regression', note: 'Reproduce unpatched, apply, re-test, compare the full suite' },
  { title: 'Learning', note: 'The trajectory, including failed attempts, is written back', lane: 'retain' },
]

export function ArchitectureDiagram() {
  return (
    <div className="grid grid-cols-1 border-2 border-ink bg-paper lg:grid-cols-[1fr_17rem]">
      <ol>
        {ARCH_ROWS.map((row, index) => (
          <li
            key={row.title}
            className={`relative px-5 py-4 ${index > 0 ? 'border-t-2 border-ink' : ''}`}
          >
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-micro tabular text-status-idle">
                {String(index + 1).padStart(2, '0')}
              </span>
              <h3 className="text-meta font-black uppercase tracking-widest text-ink">{row.title}</h3>
              {row.lane ? (
                <span className="inline-flex items-center gap-1.5 text-label font-black uppercase tracking-widest text-accent">
                  <span aria-hidden className="h-2 w-2 bg-accent" />
                  {row.lane}
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 text-micro text-status-idle">{row.note}</p>
            {index < ARCH_ROWS.length - 1 ? (
              <ChevronDown
                size={12}
                strokeWidth={3}
                aria-hidden
                className="absolute -bottom-[9px] left-6 z-10 text-ink"
              />
            ) : null}
          </li>
        ))}
      </ol>

      <aside className="border-t-2 border-ink bg-muted px-5 py-5 lg:border-l-2 lg:border-t-0">
        <div className="flex items-center gap-2">
          <Database size={15} strokeWidth={2.5} aria-hidden className="text-ink" />
          <h3 className="text-meta font-black uppercase tracking-widest text-ink">
            Hindsight memory
          </h3>
        </div>
        <p className="mt-3 text-micro text-status-idle">
          Two banks per repository: the incident trajectories, and the conventions the review gate
          enforces.
        </p>
        <dl className="mt-5 space-y-3">
          <div className="border-t-2 border-hair-strong pt-3">
            <dt className="text-label font-black uppercase tracking-widest text-ink">Read</dt>
            <dd className="mt-1 text-micro text-status-idle">
              Recall before a repair is generated, and before the review gate decides.
            </dd>
          </div>
          <div className="border-t-2 border-hair-strong pt-3">
            <dt className="text-label font-black uppercase tracking-widest text-ink">Write</dt>
            <dd className="mt-1 text-micro text-status-idle">
              Retain after every terminal state — recovered, rolled back or escalated.
            </dd>
          </div>
        </dl>
        <p className="mt-5 border-t-2 border-hair-strong pt-3 text-micro text-status-idle">
          Memory Defense is enabled on the banks: secrets and personal data are redacted from
          what gets stored.
        </p>
      </aside>
    </div>
  )
}

export function StackList() {
  return (
    <div className="border-2 border-ink bg-paper">
      <div className="border-b-2 border-ink px-5 py-3 text-label font-black uppercase tracking-widest text-ink">
        In use
      </div>
      <ul className="grid grid-cols-1 gap-px bg-hair sm:grid-cols-2 lg:grid-cols-3">
        {STACK.map((item) => (
          <li key={item} className="bg-paper px-5 py-3 font-mono text-micro text-ink">
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── principles ────────────────────────────────────────────────

const PRINCIPLE_ICONS: Record<PrincipleIcon, LucideIcon> = {
  memory: BrainCircuit,
  review: ShieldCheck,
  test: FlaskConical,
  regression: GitCompareArrows,
  recovery: Undo2,
}

export function PrincipleGrid() {
  return (
    <div className="border-2 border-ink bg-paper">
      <ul className="grid grid-cols-1 gap-px bg-hair sm:grid-cols-2 lg:grid-cols-5">
        {PRINCIPLES.map((principle) => {
          const Icon = PRINCIPLE_ICONS[principle.icon]
          return (
            <li key={principle.title} className="bg-paper px-5 py-5">
              <Icon size={18} strokeWidth={2.5} aria-hidden className="text-ink" />
              <h3 className="mt-3 text-meta font-black uppercase tracking-widest text-ink">
                {principle.title}
              </h3>
              <p className="mt-2 text-micro text-status-idle">{principle.note}</p>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
