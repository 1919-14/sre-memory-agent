import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  ApiError,
  STREAM_URL,
  api,
  type Incident,
  type IncidentSummary,
  type StreamPayload,
} from './api'

export interface AsyncState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  /** True only for the very first load, so refreshes do not blank the screen. */
  initial: boolean
  reload: () => void
  setData: (next: T | null) => void
}

/**
 * Fetch once (and optionally on an interval), tracking loading and error state.
 *
 * `deps` controls refetching; `pollMs` keeps cached figures honest without a websocket.
 */
export function useApi<T>(
  loader: () => Promise<T>,
  deps: unknown[] = [],
  options: { pollMs?: number; enabled?: boolean } = {},
): AsyncState<T> {
  const { pollMs, enabled = true } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [settled, setSettled] = useState(false)
  const [nonce, setNonce] = useState(0)

  const loaderRef = useRef(loader)
  loaderRef.current = loader

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)

    const run = async () => {
      try {
        const result = await loaderRef.current()
        if (cancelled) return
        setData(result)
        setError(null)
      } catch (cause) {
        if (cancelled) return
        setError(
          cause instanceof ApiError
            ? cause
            : new ApiError(cause instanceof Error ? cause.message : 'Unknown error', 0),
        )
      } finally {
        if (!cancelled) {
          setLoading(false)
          setSettled(true)
        }
      }
    }

    void run()
    let timer: number | undefined
    if (pollMs) {
      timer = window.setInterval(() => void run(), pollMs)
    }
    return () => {
      cancelled = true
      if (timer) window.clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, pollMs, nonce, ...deps])

  return { data, error, loading, initial: loading && !settled, reload, setData }
}

/**
 * A one-second clock, active only while something is genuinely in progress.
 *
 * Elapsed timers must be measured, not animated, so the panel reads the real wall clock and
 * simply re-renders. Ticking stops as soon as `active` goes false, which freezes the display at
 * the last real value instead of leaving it climbing past the end of the run.
 */
export function useTicker(active: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return undefined
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [active, intervalMs])

  return now
}

export type StreamState = 'connecting' | 'live' | 'reconnecting' | 'closed'

export interface LiveStream {
  events: StreamPayload[]
  state: StreamState
  /** Events for one incident, newest last. */
  forIncident: (incidentId: string | null) => StreamPayload[]
  clear: () => void
}

const MAX_BUFFERED_EVENTS = 300

/**
 * Subscribe to the server's Server-Sent Events stream.
 *
 * `EventSource` reconnects on its own, so this only mirrors its state — no manual retry
 * logic that could fight the browser's backoff.
 */
export function useLiveStream(enabled = true): LiveStream {
  const [events, setEvents] = useState<StreamPayload[]>([])
  const [state, setState] = useState<StreamState>(enabled ? 'connecting' : 'closed')

  useEffect(() => {
    if (!enabled) {
      setState('closed')
      return
    }
    let source: EventSource | null = new EventSource(STREAM_URL)

    source.onopen = () => setState('live')
    source.onerror = () => {
      // readyState CLOSED means the browser has given up; CONNECTING means it is retrying.
      setState(source?.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting')
    }
    source.onmessage = (message) => {
      if (!message.data) return
      try {
        const parsed = JSON.parse(message.data) as StreamPayload
        if (!parsed?.stage) return
        setEvents((current) => {
          // The stream replays recent events on connect; replacing by id keeps it a set.
          if (current.some((item) => item.id === parsed.id)) return current
          const next = [...current, parsed]
          return next.length > MAX_BUFFERED_EVENTS ? next.slice(-MAX_BUFFERED_EVENTS) : next
        })
      } catch {
        // A malformed frame is not worth tearing the stream down for.
      }
    }

    return () => {
      source?.close()
      source = null
    }
  }, [enabled])

  const forIncident = useCallback(
    (incidentId: string | null) =>
      incidentId ? events.filter((event) => event.incident_id === incidentId) : events,
    [events],
  )

  const clear = useCallback(() => setEvents([]), [])

  return useMemo(() => ({ events, state, forIncident, clear }), [events, state, forIncident, clear])
}

/** Copy text and report success for ~1.5s, for the code and diff copy affordances. */
export function useCopy(): { copied: string | null; copy: (value: string, key: string) => void } {
  const [copied, setCopied] = useState<string | null>(null)

  const copy = useCallback((value: string, key: string) => {
    void navigator.clipboard?.writeText(value).then(
      () => {
        setCopied(key)
        window.setTimeout(() => setCopied((current) => (current === key ? null : current)), 1500)
      },
      () => setCopied(null),
    )
  }, [])

  return { copied, copy }
}

/**
 * Load the incident list and keep one selected.
 *
 * The per-incident views (repairs, review, sandbox) each need exactly one incident in
 * focus, so the selection logic lives in one place rather than three times over.
 */
export function useSelectedIncident() {
  const list = useApi<{ incidents: IncidentSummary[] }>(() => api.incidents(50), [], {
    pollMs: 20_000,
  })
  const incidents = list.data?.incidents ?? []
  const [chosen, setChosen] = useState<string | null>(null)
  const selectedId = chosen ?? incidents[0]?.id ?? null

  const incident = useApi<Incident>(() => api.incident(selectedId as string), [selectedId], {
    enabled: Boolean(selectedId),
  })

  return {
    incidents,
    selectedId,
    select: setChosen,
    incident,
    listLoading: list.initial,
    listError: list.error,
    reloadList: list.reload,
  }
}

/** Persist a small preference (sort order, active tab) across reloads. */
export function usePersistentState<T extends string>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      return (window.localStorage.getItem(key) as T | null) ?? fallback
    } catch {
      return fallback
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(key, value)
    } catch {
      // Storage can be disabled; the preference is simply not remembered.
    }
  }, [key, value])

  return [value, setValue] as const
}
