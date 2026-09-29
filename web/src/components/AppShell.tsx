import {
  Activity,
  BrainCircuit,
  Box,
  GitBranch,
  LayoutDashboard,
  Menu,
  Play,
  Settings,
  ShieldCheck,
  TrendingUp,
  TriangleAlert,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'

import { api, type SystemStatus } from '../lib/api'
import { APP_PATH, appPath } from '../lib/site'
import { degradationLabel } from '../lib/status'
import { useRefreshAfter, useSystem } from '../lib/system'
import { Btn, StatusMark, type Variant } from './primitives'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  group: 'operations' | 'system'
}

// The dashboard lives under `/app`; the addresses inside it are absolute so a shared link is
// readable and stays valid.
const NAV: NavItem[] = [
  { to: appPath(), label: 'Overview', icon: LayoutDashboard, group: 'operations' },
  { to: appPath('/incidents'), label: 'Incidents', icon: TriangleAlert, group: 'operations' },
  { to: appPath('/memory'), label: 'Memory', icon: BrainCircuit, group: 'operations' },
  { to: appPath('/repairs'), label: 'Repairs', icon: Wrench, group: 'operations' },
  { to: appPath('/review'), label: 'Review', icon: ShieldCheck, group: 'operations' },
  { to: appPath('/sandbox'), label: 'Sandbox', icon: Box, group: 'operations' },
  { to: appPath('/learning'), label: 'Learning', icon: TrendingUp, group: 'operations' },
  { to: appPath('/system'), label: 'System', icon: Activity, group: 'system' },
  { to: appPath('/settings'), label: 'Settings', icon: Settings, group: 'system' },
]

function SidebarLink({ item }: { item: NavItem }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.to === APP_PATH}
      className={({ isActive }) =>
        `nav-link ${isActive ? 'bg-ink text-paper hover:bg-ink' : 'text-ink'}`
      }
    >
      {({ isActive }) => (
        <>
          <span
            aria-hidden
            className={`h-3 w-0.5 shrink-0 ${isActive ? 'bg-accent' : 'bg-transparent'}`}
          />
          <Icon size={15} strokeWidth={2.5} aria-hidden />
          <span>{item.label.toUpperCase()}</span>
        </>
      )}
    </NavLink>
  )
}

/** One line of the top status strip. */
function StatusCell({ label, value, variant }: { label: string; value: string; variant: Variant }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 px-4 py-2.5">
      <span className="text-label font-black uppercase tracking-widest text-status-idle">{label}</span>
      <StatusMark variant={variant} label={value} />
    </div>
  )
}

function statusCells(status: SystemStatus | null): { label: string; value: string; variant: Variant }[] {
  if (!status) {
    return [
      { label: 'Agent', value: 'Connecting', variant: 'info' },
      { label: 'Memory', value: 'Connecting', variant: 'info' },
      { label: 'LLM', value: 'Connecting', variant: 'info' },
      { label: 'Sandbox', value: 'Connecting', variant: 'info' },
    ]
  }
  // `Degraded` alone reads as a failure. It is a partial capability, so say which one is
  // missing: on a hosted Space this is usually the sandbox, which is a known and expected
  // limit rather than something broken.
  const limited = status.healthy ? '' : degradationLabel(status)
  return [
    {
      label: 'Agent',
      value: limited ? `Degraded · ${limited}` : 'Operational',
      variant: status.healthy ? 'ok' : 'warn',
    },
    {
      label: 'Memory',
      value: status.hindsight_ready ? 'Connected' : 'Unavailable',
      variant: status.hindsight_ready ? 'ok' : 'warn',
    },
    {
      label: 'LLM',
      value: status.llm_ready ? 'Connected' : 'Not configured',
      variant: status.llm_ready ? 'ok' : 'bad',
    },
    {
      label: 'Sandbox',
      value: status.sandbox_backend === 'docker' ? 'Docker' : status.sandbox_backend,
      variant: status.sandbox_backend === 'docker' ? 'ok' : 'info',
    },
  ]
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const { status, stream } = useSystem()
  const navigate = useNavigate()
  const refresh = useRefreshAfter()
  const [starting, setStarting] = useState(false)

  const running = status?.running === true
  const activeRunId = status?.active_incident_id ?? null

  /**
   * Start the demonstration incident and go straight to its live execution panel.
   *
   * While a run is already in flight the button does not sit disabled: it stays actionable and
   * takes the operator back to the run in progress, which is where the live panel is.
   */
  const runDemo = async () => {
    if (running && activeRunId) {
      navigate(appPath(`/incidents/${activeRunId}`))
      return
    }
    setStarting(true)
    try {
      const result = await api.startIncident({ scenario: 'concurrency' })
      refresh()
      navigate(appPath(`/incidents/${result.incident.id}`))
    } catch {
      // The dashboard surfaces backend errors; a failed start needs no extra banner here.
    } finally {
      setStarting(false)
    }
  }

  const streamLabel =
    stream.state === 'live'
      ? 'Live'
      : stream.state === 'connecting'
        ? 'Connecting'
        : stream.state === 'reconnecting'
          ? 'Reconnecting'
          : 'Offline'

  const streamVariant: Variant =
    stream.state === 'live' ? 'ok' : stream.state === 'closed' ? 'idle' : 'info'

  return (
    <div className="min-h-screen bg-paper swiss-noise">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:bg-ink focus:px-4 focus:py-2 focus:text-paper"
      >
        Skip to content
      </a>

      <div className="flex min-h-screen">
        {/* ── sidebar (desktop) ─────────────────────────────── */}
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r-2 border-ink bg-paper lg:flex">
          <Wordmark />
          <nav aria-label="Sections" className="flex-1 overflow-y-auto border-t-2 border-ink py-2">
            <NavGroup items={NAV.filter((item) => item.group === 'operations')} />
            <div className="mt-2 border-t-2 border-ink pt-2">
              <NavGroup items={NAV.filter((item) => item.group === 'system')} />
            </div>
          </nav>
          <div className="border-t-2 border-ink px-4 py-3">
            <div className="text-label font-black uppercase tracking-widest text-status-idle">
              Repository
            </div>
            <div className="mt-1 flex items-center gap-2 font-mono text-micro text-ink">
              <GitBranch size={11} strokeWidth={2.5} aria-hidden />
              <span className="truncate" title={status?.repo_path}>
                {status?.repo_present ? (status.repo_path.split(/[\\/]/).pop() ?? '—') : 'not found'}
              </span>
            </div>
            {status?.repo_commit ? (
              <div className="mt-1 font-mono text-micro text-status-idle">
                {status.repo_commit.slice(0, 8)}
              </div>
            ) : null}
          </div>
        </aside>

        {/* ── main column ───────────────────────────────────── */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* top bar */}
          <header className="sticky top-0 z-30 border-b-2 border-ink bg-paper">
            <div className="flex items-stretch justify-between">
              <div className="flex items-center gap-3 px-4 py-3 lg:hidden">
                <button
                  type="button"
                  onClick={() => setOpen((value) => !value)}
                  aria-label={open ? 'Close navigation' : 'Open navigation'}
                  aria-expanded={open}
                  className="inline-flex h-9 w-9 items-center justify-center border-2 border-ink"
                >
                  {open ? <X size={16} strokeWidth={2.5} aria-hidden /> : <Menu size={16} strokeWidth={2.5} aria-hidden />}
                </button>
                <span className="text-meta font-black uppercase tracking-tight">SRE Memory Agent</span>
              </div>

              <div className="hidden flex-1 divide-x-2 divide-ink lg:flex">
                {statusCells(status).map((cell) => (
                  <StatusCell key={cell.label} {...cell} />
                ))}
              </div>

              <div className="flex items-center gap-3 border-l-2 border-ink px-4 py-3">
                <div className="hidden items-center gap-2 sm:flex">
                  <span aria-hidden className={`inline-block h-2 w-2 ${streamVariant === 'ok' ? 'bg-status-ok' : streamVariant === 'idle' ? 'bg-status-idle' : 'bg-status-info'}`} />
                  <span className="text-label font-black uppercase tracking-widest text-status-idle">
                    {streamLabel}
                  </span>
                </div>
                <Btn
                  icon={Play}
                  size="sm"
                  variant="accent"
                  onClick={() => void runDemo()}
                  disabled={starting}
                  title={
                    running
                      ? 'An incident is running — open it'
                      : 'Start the concurrency scenario'
                  }
                  className={running ? 'animate-pulse-slow' : ''}
                >
                  {starting || running ? 'Running' : 'Run demo'}
                </Btn>
              </div>
            </div>

            {/* mobile navigation */}
            {open ? (
              <nav aria-label="Sections" className="animate-fade-rise border-t-2 border-ink bg-paper lg:hidden">
                <NavGroup items={NAV} onNavigate={() => setOpen(false)} />
              </nav>
            ) : null}
          </header>

          <main id="main" className="min-w-0 flex-1">
            {children}
          </main>

          <footer className="border-t-2 border-ink px-6 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3 text-micro text-status-idle">
              <span className="font-bold uppercase tracking-widest">
                SRE Memory Agent — incident recovery that remembers
              </span>
              <span className="font-mono">
                v{status?.version ?? '—'}
                {status?.hindsight_version ? ` · hindsight ${status.hindsight_version}` : ''}
              </span>
            </div>
          </footer>
        </div>
      </div>
    </div>
  )
}

function NavGroup({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  return (
    <ul>
      {items.map((item) => (
        <li key={item.to} onClick={onNavigate}>
          <SidebarLink item={item} />
        </li>
      ))}
    </ul>
  )
}

function Wordmark() {
  return (
    <div className="px-4 py-5">
      <Link to={appPath()} className="flex items-center gap-2">
        <span aria-hidden className="grid h-7 w-7 place-items-center bg-ink text-paper">
          <span className="h-3 w-3 bg-accent" />
        </span>
        <span className="text-lead font-black uppercase leading-none tracking-tighter">
          SRE Memory
          <br />
          Agent
        </span>
      </Link>
      <p className="mt-3 text-micro leading-snug text-status-idle">
        Incident recovery that remembers.
      </p>
    </div>
  )
}

/** Shared page container: enforces the horizontal rhythm across every page. */
export function Page({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={`mx-auto w-full max-w-[1400px] px-5 py-8 sm:px-8 lg:py-12 ${className}`}>{children}</div>
}
