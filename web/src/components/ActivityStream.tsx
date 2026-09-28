import { useEffect, useRef } from 'react'

import type { ExecutionEvent } from '../lib/api'
import { localTime, stageLabel } from '../lib/format'
import { Empty, Tag } from './primitives'
import { Radio } from 'lucide-react'

const MARKER: Record<string, string> = {
  ok: 'bg-status-ok',
  warn: 'bg-status-warn',
  failed: 'bg-status-bad',
  running: 'bg-status-info',
  skipped: 'bg-hair-strong',
  pending: 'bg-hair-strong',
}

const MESSAGE_TONE: Record<string, string> = {
  ok: 'text-ink',
  warn: 'text-status-warn',
  failed: 'text-status-bad',
  running: 'text-ink',
  skipped: 'text-status-idle',
  pending: 'text-status-idle',
}

/**
 * The agent's own event feed.
 *
 * Follows the tail only while the reader is already at the bottom, so scrolling back to
 * read an earlier step is not undone by the next event.
 */
export function ActivityStream({
  events,
  height = '24rem',
  emptyDetail = 'Events appear here while the agent works.',
}: {
  events: ExecutionEvent[]
  height?: string
  emptyDetail?: string
}) {
  const scroller = useRef<HTMLDivElement | null>(null)
  const pinned = useRef(true)

  useEffect(() => {
    const node = scroller.current
    if (!node || !pinned.current) return
    node.scrollTop = node.scrollHeight
  }, [events.length])

  if (events.length === 0) {
    return (
      <Empty
        icon={Radio}
        title="No activity yet"
        detail={emptyDetail}
      />
    )
  }

  return (
    <div
      ref={scroller}
      onScroll={(event) => {
        const node = event.currentTarget
        pinned.current = node.scrollHeight - node.scrollTop - node.clientHeight < 24
      }}
      className="overflow-y-auto"
      style={{ height }}
      role="log"
      aria-live="polite"
      aria-label="Agent activity"
    >
      <ol className="divide-y divide-hair">
        {events.map((event) => (
          <li key={event.id} className="flex items-start gap-3 px-4 py-2.5 animate-fade-rise">
            <span className="w-16 shrink-0 pt-0.5 font-mono text-micro tabular text-status-idle">
              {localTime(event.timestamp)}
            </span>
            <span
              aria-hidden
              className={`mt-1.5 h-2 w-2 shrink-0 ${MARKER[event.status] ?? 'bg-status-idle'}`}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-label font-black uppercase tracking-widest text-ink">
                  {stageLabel(event.stage)}
                </span>
                {event.status === 'running' ? <Tag tone="info">in progress</Tag> : null}
                {event.status === 'failed' ? <Tag tone="bad">failed</Tag> : null}
                {event.status === 'warn' ? <Tag tone="warn">attention</Tag> : null}
              </div>
              <p className={`mt-0.5 text-meta ${MESSAGE_TONE[event.status] ?? 'text-ink'}`}>
                {event.message}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
