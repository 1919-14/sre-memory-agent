import {
  AlertTriangle,
  Check,
  ChevronDown,
  Copy,
  Loader2,
  Plus,
  RefreshCw,
  type LucideIcon,
} from 'lucide-react'
import { type ReactNode, useId, useState } from 'react'

import { useCopy } from '../lib/hooks'

export type Variant = 'ok' | 'warn' | 'bad' | 'idle' | 'info'
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'

const VARIANT_TEXT: Record<Variant, string> = {
  ok: 'text-status-ok',
  warn: 'text-status-warn',
  bad: 'text-status-bad',
  idle: 'text-status-idle',
  info: 'text-status-info',
}

const VARIANT_BG: Record<Variant, string> = {
  ok: 'bg-status-ok',
  warn: 'bg-status-warn',
  bad: 'bg-status-bad',
  idle: 'bg-status-idle',
  info: 'bg-status-info',
}

// ── structure ─────────────────────────────────────────────────

/** A bordered surface. Borders define the grid; there is no shadow anywhere. */
export function Panel({
  children,
  className = '',
  as: Tag = 'section',
}: {
  children: ReactNode
  className?: string
  as?: 'section' | 'div' | 'article' | 'aside'
}) {
  return <Tag className={`border-2 border-ink bg-paper ${className}`}>{children}</Tag>
}

/** Numbered section label in the accent colour, with an optional rule and action. */
export function SectionHeader({
  index,
  title,
  description,
  action,
  className = '',
}: {
  index?: string
  title: string
  description?: string
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={`flex flex-wrap items-end justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        <div className="section-label">
          {index ? <span>{index}</span> : null}
          <span className="text-ink">{title}</span>
        </div>
        {description ? <p className="mt-2 max-w-2xl text-meta text-status-idle">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}

/** A single rule used to separate major sections. */
export function Rule({ heavy = false }: { heavy?: boolean }) {
  return <div aria-hidden className={heavy ? 'h-1 bg-ink' : 'h-0.5 bg-ink'} />
}

// ── actions ───────────────────────────────────────────────────

export function Btn({
  children,
  onClick,
  variant = 'primary',
  icon: Icon,
  disabled,
  type = 'button',
  size = 'md',
  title,
  className = '',
}: {
  children?: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'accent' | 'ghost'
  icon?: LucideIcon
  disabled?: boolean
  type?: 'button' | 'submit'
  size?: 'sm' | 'md'
  title?: string
  className?: string
}) {
  const base =
    'inline-flex items-center justify-center gap-2 border-2 font-bold uppercase tracking-wide transition-colors duration-150 ease-linear disabled:cursor-not-allowed disabled:opacity-40'
  const sizes = size === 'sm' ? 'px-3 py-1.5 text-label' : 'px-4 py-2.5 text-meta'
  const styles = {
    primary: 'border-ink bg-ink text-paper hover:bg-accent hover:border-accent',
    secondary: 'border-ink bg-paper text-ink hover:bg-ink hover:text-paper',
    accent: 'border-accent bg-accent text-paper hover:bg-ink hover:border-ink',
    ghost: 'border-transparent bg-transparent text-ink hover:border-ink',
  }[variant]

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${base} ${sizes} ${styles} ${className}`}
    >
      {Icon ? <Icon size={size === 'sm' ? 13 : 15} strokeWidth={2.5} aria-hidden /> : null}
      {children}
    </button>
  )
}

/** Icon-only control. Always requires a label for accessibility. */
export function IconBtn({
  icon: Icon,
  label,
  onClick,
  spin = false,
}: {
  icon: LucideIcon
  label: string
  onClick?: () => void
  spin?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="inline-flex h-9 w-9 items-center justify-center border-2 border-ink bg-paper text-ink transition-colors duration-150 ease-linear hover:bg-ink hover:text-paper"
    >
      <Icon size={15} strokeWidth={2.5} className={spin ? 'animate-spin' : undefined} aria-hidden />
    </button>
  )
}

/** Copy-to-clipboard affordance for SHAs, diffs and payloads. */
export function CopyButton({ value, label = 'Copy' }: { value: string; label?: string }) {
  const { copied, copy } = useCopy()
  const isCopied = copied === label
  return (
    <button
      type="button"
      onClick={() => copy(value, label)}
      aria-label={label}
      title={isCopied ? 'Copied' : label}
      className="inline-flex items-center gap-1.5 border-2 border-hair-strong px-2 py-1 text-label font-bold uppercase tracking-wide text-status-idle transition-colors duration-150 ease-linear hover:border-ink hover:text-ink"
    >
      {isCopied ? <Check size={11} strokeWidth={3} aria-hidden /> : <Copy size={11} strokeWidth={2.5} aria-hidden />}
      {isCopied ? 'Copied' : 'Copy'}
    </button>
  )
}

// ── status ────────────────────────────────────────────────────

/** A flat square marker plus its wording. Never a lone colour: colour is never the only signal. */
export function StatusMark({ variant, label }: { variant: Variant; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden className={`inline-block h-2 w-2 ${VARIANT_BG[variant]}`} />
      <span className={`text-meta font-bold uppercase tracking-wide ${VARIANT_TEXT[variant]}`}>
        {label}
      </span>
    </span>
  )
}

export function Tag({
  children,
  tone = 'neutral',
  title,
}: {
  children: ReactNode
  tone?: 'neutral' | 'accent' | Variant
  title?: string
}) {
  const styles = {
    neutral: 'border-hair-strong text-status-idle',
    accent: 'border-accent text-accent',
    ok: 'border-status-ok text-status-ok',
    warn: 'border-status-warn text-status-warn',
    bad: 'border-status-bad text-status-bad',
    idle: 'border-hair-strong text-status-idle',
    info: 'border-status-info text-status-info',
  }[tone]
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 border-2 px-2 py-0.5 font-mono text-micro font-semibold uppercase tracking-wide ${styles}`}
    >
      {children}
    </span>
  )
}

export function SeverityTag({ severity }: { severity: Severity | string }) {
  const tone: 'bad' | 'warn' | 'idle' | 'info' = (
    {
      critical: 'bad',
      high: 'bad',
      medium: 'warn',
      low: 'idle',
      info: 'info',
    } as const
  )[severity as Severity] ?? 'idle'
  return <Tag tone={tone}>{severity}</Tag>
}

// ── data display ──────────────────────────────────────────────

/** A headline figure. The number is the image; the label is the caption. */
export function Metric({
  value,
  label,
  note,
  tone = 'ink',
}: {
  value: ReactNode
  label: string
  note?: string
  tone?: 'ink' | Variant
}) {
  const toneClass = tone === 'ink' ? 'text-ink' : VARIANT_TEXT[tone]
  return (
    <div className="group px-6 py-5 transition-colors duration-150 ease-linear hover:bg-muted">
      <div className={`text-h2 font-black tabular ${toneClass}`}>{value}</div>
      <div className="mt-2 text-label font-black uppercase tracking-widest text-status-idle">
        {label}
      </div>
      {note ? <div className="mt-1.5 text-micro text-status-idle">{note}</div> : null}
    </div>
  )
}

/** Key/value line for metadata blocks. */
export function KV({
  k,
  children,
  mono = false,
  align = 'row',
}: {
  k: string
  children: ReactNode
  mono?: boolean
  align?: 'row' | 'stack'
}) {
  if (align === 'stack') {
    return (
      <div className="py-2">
        <div className="text-label font-black uppercase tracking-widest text-status-idle">{k}</div>
        <div className={`mt-1 text-meta ${mono ? 'font-mono' : ''}`}>{children}</div>
      </div>
    )
  }
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-hair py-2 last:border-b-0">
      <dt className="shrink-0 text-label font-black uppercase tracking-widest text-status-idle">{k}</dt>
      <dd className={`min-w-0 text-right text-meta break-words ${mono ? 'font-mono' : ''}`}>{children}</dd>
    </div>
  )
}

/** A tiny proportional bar. Used instead of a charting library, and only where it earns space. */
export function Bar({
  value,
  max,
  tone = 'ink',
  label,
}: {
  value: number
  max: number
  tone?: 'ink' | Variant
  label?: string
}) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0
  const fill = tone === 'ink' ? 'bg-ink' : VARIANT_BG[tone]
  return (
    <div
      role="img"
      aria-label={label ?? `${value} of ${max}`}
      className="h-2 w-full border-2 border-hair-strong bg-paper"
    >
      <div
        className={`h-full ${fill} origin-left animate-scale-in`}
        style={{ width: `${Math.round(ratio * 100)}%` }}
      />
    </div>
  )
}

// ── states ────────────────────────────────────────────────────

export function Empty({
  icon: Icon,
  title,
  detail,
  action,
}: {
  icon: LucideIcon
  title: string
  detail?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-start gap-3 px-6 py-12">
      <Icon size={20} strokeWidth={2} className="text-status-idle" aria-hidden />
      <div className="text-meta font-bold uppercase tracking-wide text-ink">{title}</div>
      {detail ? <p className="max-w-xl text-meta text-status-idle">{detail}</p> : null}
      {action}
    </div>
  )
}

/**
 * Failure state. The technical detail is one click away rather than sprayed across the
 * page: an operator needs the summary first and the cause second.
 */
export function Failure({
  title,
  message,
  detail,
  onRetry,
  retryLabel = 'Retry',
  warning = false,
}: {
  title: string
  message: string
  detail?: string
  onRetry?: () => void
  retryLabel?: string
  warning?: boolean
}) {
  const [open, setOpen] = useState(false)
  const tone = warning ? 'border-status-warn' : 'border-status-bad'
  return (
    <div className={`border-2 ${tone} bg-paper`}>
      <div className="flex items-start gap-3 px-6 py-5">
        <AlertTriangle
          size={18}
          strokeWidth={2.5}
          className={warning ? 'mt-0.5 shrink-0 text-status-warn' : 'mt-0.5 shrink-0 text-status-bad'}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div className="text-meta font-black uppercase tracking-wide text-ink">{title}</div>
          <p className="mt-1.5 text-meta text-status-idle">{message}</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {onRetry ? <Btn icon={RefreshCw} variant="secondary" size="sm" onClick={onRetry}>{retryLabel}</Btn> : null}
            {detail ? (
              <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                aria-expanded={open}
                className="inline-flex items-center gap-1.5 text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-ink"
              >
                <ChevronDown
                  size={12}
                  strokeWidth={3}
                  aria-hidden
                  className={open ? 'rotate-180 transition-transform duration-150' : 'transition-transform duration-150'}
                />
                Technical detail
              </button>
            ) : null}
          </div>
          {open && detail ? (
            <pre className="code-surface mt-4 max-h-56 overflow-auto p-4 text-micro">{detail}</pre>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export function Skeleton({ className = 'h-4 w-full' }: { className?: string }) {
  return <div className={`animate-pulse-slow bg-muted ${className}`} aria-hidden />
}

export function Loading({ label = 'Loading', rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div className="px-6 py-6" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-label font-black uppercase tracking-widest text-status-idle">
        <Loader2 size={12} strokeWidth={3} className="animate-spin" aria-hidden />
        {label}
      </div>
      <div className="mt-5 space-y-3">
        {Array.from({ length: rows }).map((_, index) => (
          <Skeleton key={index} className="h-4" />
        ))}
      </div>
    </div>
  )
}

// ── disclosure ────────────────────────────────────────────────

/** Expandable region with a rotating plus, used for timeline stages and evidence panels. */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  meta,
}: {
  summary: ReactNode
  children: ReactNode
  defaultOpen?: boolean
  meta?: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  return (
    <div>
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls={id}
          className="group flex min-w-0 flex-1 items-start gap-3 text-left"
        >
          <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center border-2 border-ink text-ink transition-colors duration-150 ease-linear group-hover:bg-accent group-hover:border-accent group-hover:text-paper">
            <Plus
              size={11}
              strokeWidth={3.5}
              aria-hidden
              className={`transition-transform duration-200 ease-swiss ${open ? 'rotate-90' : ''}`}
            />
          </span>
          <span className="min-w-0 flex-1">{summary}</span>
        </button>
        {meta ? <div className="shrink-0 pt-0.5">{meta}</div> : null}
      </div>
      {open ? (
        <div id={id} className="mt-4 animate-fade-rise border-l-2 border-hair pl-6">
          {children}
        </div>
      ) : null}
    </div>
  )
}
