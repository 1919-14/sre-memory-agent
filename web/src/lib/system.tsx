import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo } from 'react'

import { api, type SystemStatus } from './api'
import { useApi, useLiveStream, type LiveStream } from './hooks'

interface SystemContextValue {
  status: SystemStatus | null
  statusError: ReturnType<typeof useApi<SystemStatus>>['error']
  statusLoading: boolean
  reloadStatus: () => void
  stream: LiveStream
}

const SystemContext = createContext<SystemContextValue | null>(null)

/**
 * Holds the two pieces of state every page needs: the system status and the live event
 * stream. Both are singular resources — one poll, one `EventSource` — so they live here
 * rather than in each page.
 */
export function SystemProvider({ children }: { children: ReactNode }) {
  // The status payload already embeds metrics and learning stats, so one poll covers the
  // header, the dashboard and every health indicator.
  const status = useApi<SystemStatus>(() => api.status(), [], { pollMs: 10_000 })
  const stream = useLiveStream(true)

  // A new event is a reason to re-read status. Effect cleanup debounces a burst of events
  // into a single refresh instead of one request per event.
  const { reload } = status
  const lastEventId = stream.events.length
    ? stream.events[stream.events.length - 1].id
    : null

  useEffect(() => {
    if (!lastEventId) return undefined
    const timer = window.setTimeout(reload, 400)
    return () => window.clearTimeout(timer)
  }, [lastEventId, reload])

  const value = useMemo<SystemContextValue>(
    () => ({
      status: status.data,
      statusError: status.error,
      statusLoading: status.initial,
      reloadStatus: status.reload,
      stream,
    }),
    [status.data, status.error, status.initial, status.reload, stream],
  )

  return <SystemContext.Provider value={value}>{children}</SystemContext.Provider>
}

export function useSystem(): SystemContextValue {
  const value = useContext(SystemContext)
  if (!value) throw new Error('useSystem must be used inside SystemProvider')
  return value
}

/** Convenience: a stable callback that reloads status after a mutation. */
export function useRefreshAfter(): () => void {
  const { reloadStatus } = useSystem()
  return useCallback(() => reloadStatus(), [reloadStatus])
}
