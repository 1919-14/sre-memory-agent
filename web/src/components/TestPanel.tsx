import { CircleCheck, CircleX, Minus } from 'lucide-react'

import type { TestReport } from '../lib/api'
import { duration, plural } from '../lib/format'
import { Rule, Tag } from './primitives'

/** Compact pass/fail counters. Deliberately not a chart: the counts are the message. */
function Counters({ report }: { report: TestReport }) {
  const cells: { label: string; value: number; tone?: 'bad' | 'warn' | 'ok' | 'idle' }[] = [
    { label: 'Passed', value: report.passed, tone: 'ok' },
    { label: 'Failed', value: report.failed, tone: report.failed > 0 ? 'bad' : 'idle' },
    { label: 'Errors', value: report.errors, tone: report.errors > 0 ? 'bad' : 'idle' },
    { label: 'Skipped', value: report.skipped, tone: 'idle' },
  ]
  return (
    <div className="grid grid-cols-2 gap-px bg-hair sm:grid-cols-4">
      {cells.map((cell) => (
        <div key={cell.label} className="bg-paper px-3 py-2">
          <div className="text-label font-black uppercase tracking-widest text-status-idle">
            {cell.label}
          </div>
          <div
            className={`mt-0.5 text-h3 font-black tabular ${
              cell.tone === 'bad'
                ? 'text-status-bad'
                : cell.tone === 'ok'
                  ? 'text-status-ok'
                  : 'text-status-idle'
            }`}
          >
            {cell.value}
          </div>
        </div>
      ))}
    </div>
  )
}

export function TestPanel({ title, report }: { title: string; report: TestReport | null }) {
  if (!report) {
    return (
      <div className="border-2 border-hair">
        <div className="border-b-2 border-hair px-3 py-2 text-label font-black uppercase tracking-widest text-status-idle">
          {title}
        </div>
        <p className="flex items-center gap-2 px-3 py-3 text-meta text-status-idle">
          <Minus size={13} strokeWidth={2.5} aria-hidden />
          This step did not run.
        </p>
      </div>
    )
  }

  const failures = report.cases.filter((item) => item.outcome === 'failed' || item.outcome === 'error')

  return (
    <div className="border-2 border-hair">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-hair px-3 py-2">
        <span className="text-label font-black uppercase tracking-widest text-ink">{title}</span>
        <div className="flex items-center gap-2">
          <Tag tone={report.exit_code === 0 ? 'ok' : 'bad'}>exit {report.exit_code}</Tag>
          <span className="font-mono text-micro text-status-idle">{duration(report.duration)}</span>
        </div>
      </div>

      <div className="p-3">
        <Counters report={report} />

        {failures.length > 0 ? (
          <>
            <Rule />
            <ul className="mt-3 space-y-2">
              {failures.slice(0, 12).map((item) => (
                <li key={item.nodeid} className="flex items-start gap-2">
                  <CircleX
                    size={13}
                    strokeWidth={2.5}
                    className="mt-0.5 shrink-0 text-status-bad"
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <div className="break-all font-mono text-micro">{item.nodeid}</div>
                    {item.message ? (
                      <p className="mt-0.5 line-clamp-2 text-micro text-status-idle">{item.message}</p>
                    ) : null}
                  </div>
                </li>
              ))}
              {failures.length > 12 ? (
                <li className="text-micro text-status-idle">
                  and {plural(failures.length - 12, 'further failure')}
                </li>
              ) : null}
            </ul>
          </>
        ) : (
          <p className="mt-3 flex items-center gap-2 text-meta text-status-ok">
            <CircleCheck size={13} strokeWidth={2.5} aria-hidden />
            All {plural(report.total, 'test')} passed.
          </p>
        )}

        {report.raw_output ? (
          <details className="mt-3">
            <summary className="cursor-pointer text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-accent">
              Raw runner output
            </summary>
            <pre className="code-surface mt-2 max-h-64 overflow-auto p-3 text-micro">
              {report.raw_output}
            </pre>
          </details>
        ) : null}
      </div>
    </div>
  )
}

/** Before/after comparison used on the sandbox page. */
export function BeforeAfter({
  before,
  after,
}: {
  before: TestReport | null
  after: TestReport | null
}) {
  const rows = [
    { label: 'Failed before', value: before?.failed ?? 0, tone: 'bad' as const },
    { label: 'Failed after', value: after?.failed ?? 0, tone: (after?.failed ?? 0) === 0 ? ('ok' as const) : ('bad' as const) },
    { label: 'Passed after', value: after?.passed ?? 0, tone: 'ok' as const },
    { label: 'Full suite', value: after?.total ?? 0, tone: 'idle' as const },
  ]
  return (
    <div className="grid grid-cols-2 gap-px bg-hair lg:grid-cols-4">
      {rows.map((row) => (
        <div key={row.label} className="bg-paper px-5 py-4">
          <div className="text-label font-black uppercase tracking-widest text-status-idle">
            {row.label}
          </div>
          <div
            className={`mt-1 text-h2 font-black tabular ${
              row.tone === 'bad' ? 'text-status-bad' : row.tone === 'ok' ? 'text-status-ok' : 'text-ink'
            }`}
          >
            {row.value}
          </div>
        </div>
      ))}
    </div>
  )
}
