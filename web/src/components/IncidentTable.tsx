import { ArrowUpDown, Search, TriangleAlert } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { IncidentSummary } from '../lib/api'
import { errorClassNote, outcomeLabel, outcomeVariant, relativeTime, titleize } from '../lib/format'
import { appPath } from '../lib/site'
import { Empty, StatusMark, Tag } from './primitives'

type SortKey = 'created_at' | 'attempts' | 'error_class'
type OutcomeFilter = 'all' | 'recovered' | 'rolled-back' | 'escalated' | 'other'

function matchesFilter(incident: IncidentSummary, filter: OutcomeFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'other') {
    return !['recovered', 'rolled-back', 'escalated'].includes(incident.outcome ?? '')
  }
  return incident.outcome === filter
}

export function IncidentTable({
  incidents,
  compact = false,
}: {
  incidents: IncidentSummary[]
  compact?: boolean
}) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<OutcomeFilter>('all')
  const [sort, setSort] = useState<SortKey>('created_at')
  const [descending, setDescending] = useState(true)

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const filtered = incidents.filter((incident) => {
      if (!matchesFilter(incident, filter)) return false
      if (!needle) return true
      return [incident.id, incident.error_class, incident.error, incident.label]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle))
    })

    const sorted = [...filtered].sort((a, b) => {
      if (sort === 'attempts') return (a.attempts ?? 0) - (b.attempts ?? 0)
      if (sort === 'error_class') {
        return String(a.error_class ?? '').localeCompare(String(b.error_class ?? ''))
      }
      return String(a.created_at ?? '').localeCompare(String(b.created_at ?? ''))
    })

    return descending ? sorted.reverse() : sorted
  }, [incidents, query, filter, sort, descending])

  const toggleSort = (key: SortKey) => {
    if (sort === key) {
      setDescending((value) => !value)
      return
    }
    setSort(key)
    setDescending(true)
  }

  if (incidents.length === 0) {
    return (
      <Empty
        icon={TriangleAlert}
        title="No incidents recorded"
        detail="Nothing has been investigated yet. Run a demo incident to populate the history, or start one from the CLI with scripts/run_incident.py."
      />
    )
  }

  return (
    <div>
      {/* controls */}
      <div className="flex flex-wrap items-center gap-3 border-b-2 border-ink px-4 py-3">
        <label className="relative flex min-w-[14rem] flex-1 items-center">
          <Search
            size={13}
            strokeWidth={2.5}
            className="pointer-events-none absolute left-3 text-status-idle"
            aria-hidden
          />
          <span className="sr-only">Search incidents</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by id, class or error"
            className="swiss-input pl-9"
          />
        </label>

        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter by outcome">
          {(['all', 'recovered', 'rolled-back', 'escalated', 'other'] as OutcomeFilter[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              className={`border-2 px-2.5 py-1.5 text-label font-bold uppercase tracking-wide transition-colors duration-150 ease-linear ${
                filter === key
                  ? 'border-ink bg-ink text-paper'
                  : 'border-hair-strong text-status-idle hover:border-ink hover:text-ink'
              }`}
            >
              {key === 'all' ? 'All' : key.replace('-', ' ')}
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <Empty
          icon={Search}
          title="No incidents match the current filter"
          detail="Adjust the search or choose a different outcome."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b-2 border-ink">
                <Th>Incident</Th>
                <Th>
                  <SortBtn active={sort === 'error_class'} onClick={() => toggleSort('error_class')}>
                    Classification
                  </SortBtn>
                </Th>
                <Th>Outcome</Th>
                <Th align="right">
                  <SortBtn active={sort === 'attempts'} onClick={() => toggleSort('attempts')}>
                    Attempts
                  </SortBtn>
                </Th>
                {!compact ? <Th>Run mode</Th> : null}
                <Th align="right">
                  <SortBtn active={sort === 'created_at'} onClick={() => toggleSort('created_at')}>
                    Created
                  </SortBtn>
                </Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((incident) => (
                <tr key={incident.id} className="group border-b border-hair hover:bg-muted">
                  <td className="px-4 py-3">
                    <Link
                      to={appPath(`/incidents/${incident.id}`)}
                      className="block font-mono text-micro font-bold text-ink underline-offset-4 hover:text-accent hover:underline"
                    >
                      {incident.id}
                    </Link>
                    <div className="mt-0.5 line-clamp-2 max-w-md text-micro text-status-idle">
                      {incident.error || 'No error summary recorded'}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-meta font-bold">{titleize(incident.error_class)}</div>
                    {errorClassNote(incident.error_class) ? (
                      <div className="mt-0.5 text-micro text-status-idle">
                        {errorClassNote(incident.error_class)}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <StatusMark
                      variant={outcomeVariant(incident.outcome)}
                      label={outcomeLabel(incident.outcome)}
                    />
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-meta tabular">
                    {incident.attempts ?? '—'}
                  </td>
                  {!compact ? (
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        <Tag tone={incident.run_mode === 'live' ? 'ok' : 'neutral'}>
                          {incident.run_mode ?? '—'}
                        </Tag>
                        {incident.source === 'recorded' ? (
                          <Tag tone="neutral" title="Reconstructed from a recorded trajectory">
                            recorded
                          </Tag>
                        ) : null}
                      </div>
                    </td>
                  ) : null}
                  <td className="px-4 py-3 text-right font-mono text-micro text-status-idle">
                    {relativeTime(incident.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Th({ children, align = 'left' }: { children: ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      scope="col"
      className={`px-4 py-2.5 text-label font-black uppercase tracking-widest text-status-idle ${
        align === 'right' ? 'text-right' : 'text-left'
      }`}
    >
      {children}
    </th>
  )
}

function SortBtn({
  children,
  active,
  onClick,
}: {
  children: ReactNode
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 uppercase transition-colors hover:text-ink ${
        active ? 'text-ink' : ''
      }`}
    >
      {children}
      <ArrowUpDown size={10} strokeWidth={3} aria-hidden />
    </button>
  )
}

/**
 * Selector for the per-incident pages (repairs, review, sandbox) so each of those views
 * has a concrete incident to inspect rather than a dead end.
 */
export function IncidentPicker({
  incidents,
  value,
  onChange,
}: {
  incidents: IncidentSummary[]
  value: string | null
  onChange: (id: string) => void
}) {
  if (incidents.length === 0) return null
  return (
    <label className="flex items-center gap-2">
      <span className="text-label font-black uppercase tracking-widest text-status-idle">Incident</span>
      <select
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        className="swiss-input max-w-xs font-mono"
      >
        {incidents.map((incident) => (
          <option key={incident.id} value={incident.id}>
            {incident.id} — {incident.error_class ?? 'unclassified'} — {incident.outcome ?? 'running'}
          </option>
        ))}
      </select>
    </label>
  )
}
