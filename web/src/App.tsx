import { Suspense, lazy, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppShell, Page } from './components/AppShell'
import { Failure, Loading } from './components/primitives'
import { ApiError } from './lib/api'
import { APP_PATH, appPath } from './lib/site'
import { SystemProvider, useSystem } from './lib/system'

// Pages are split so the first paint does not carry the whole application.
const Landing = lazy(() => import('./pages/Landing'))
const Overview = lazy(() => import('./pages/Overview'))
const Incidents = lazy(() => import('./pages/Incidents'))
const IncidentDetail = lazy(() => import('./pages/IncidentDetail'))
const Memory = lazy(() => import('./pages/Memory'))
const Repairs = lazy(() => import('./pages/Repairs'))
const Review = lazy(() => import('./pages/Review'))
const Sandbox = lazy(() => import('./pages/Sandbox'))
const Learning = lazy(() => import('./pages/Learning'))
const System = lazy(() => import('./pages/System'))
const Settings = lazy(() => import('./pages/Settings'))
const NotFound = lazy(() => import('./pages/NotFound'))

/**
 * The backend is a hard dependency of every page, so an unreachable API is reported once
 * here rather than as ten separate failures.
 *
 * This gate wraps the dashboard only: the public landing page must render whether or not the
 * API answers, so it is mounted outside this component.
 */
function ConnectionGate({ children }: { children: ReactNode }) {
  const { statusError, statusLoading, reloadStatus } = useSystem()

  if (statusLoading) {
    return (
      <Page>
        <Loading label="Contacting the agent" rows={6} />
      </Page>
    )
  }

  if (statusError) {
    const unreachable = statusError instanceof ApiError && statusError.status === 0
    return (
      <Page>
        <Failure
          title={unreachable ? 'Backend unreachable' : 'The agent reported a problem'}
          message={
            unreachable
              ? 'The dashboard could not reach the API. Start it with `python scripts/serve.py` and the pages will populate themselves.'
              : statusError.message
          }
          detail={statusError.detail}
          onRetry={reloadStatus}
        />
      </Page>
    )
  }

  return <>{children}</>
}

/** The dashboard: the shell, the live status and one page, mounted under `/app`. */
function Dashboard({ children }: { children: ReactNode }) {
  return (
    <SystemProvider>
      <AppShell>
        <ConnectionGate>
          <Suspense
            fallback={
              <Page>
                <Loading label="Loading section" rows={5} />
              </Page>
            }
          >
            {children}
          </Suspense>
        </ConnectionGate>
      </AppShell>
    </SystemProvider>
  )
}

/** The dashboard's routes. Written absolute so the paths in the address bar are literal. */
const DASHBOARD_ROUTES: { path: string; element: ReactNode }[] = [
  { path: appPath(), element: <Overview /> },
  { path: appPath('/incidents'), element: <Incidents /> },
  { path: appPath('/incidents/:incidentId'), element: <IncidentDetail /> },
  { path: appPath('/memory'), element: <Memory /> },
  { path: appPath('/repairs'), element: <Repairs /> },
  { path: appPath('/review'), element: <Review /> },
  { path: appPath('/sandbox'), element: <Sandbox /> },
  { path: appPath('/learning'), element: <Learning /> },
  { path: appPath('/system'), element: <System /> },
  { path: appPath('/settings'), element: <Settings /> },
  { path: appPath('/repository'), element: <Navigate to={appPath('/system')} replace /> },
]

/**
 * Routes the dashboard answered before the landing page took `/`.
 *
 * They are redirected rather than dropped: an incident URL that was shared last week still
 * resolves to the same incident, it has simply moved under `/app`.
 */
const LEGACY_ROUTES = [
  '/incidents',
  '/incidents/*',
  '/memory',
  '/repairs',
  '/review',
  '/sandbox',
  '/learning',
  '/system',
  '/settings',
  '/repository',
]

function LegacyLink() {
  const location = useLocation()
  return <Navigate to={`${APP_PATH}${location.pathname}${location.search}`} replace />
}

/**
 * Shown while the landing chunk loads. The page itself is lazy, so this is the first paint.
 *
 * It repeats the landing page's own header — same bar, same paddings, same wordmark — so the
 * swap when the chunk arrives is a fill-in rather than a flash of a different page.
 */
function RouteFallback() {
  return (
    <div className="min-h-screen bg-paper swiss-noise">
      <div className="border-b-2 border-ink">
        <div className="mx-auto flex w-full max-w-[1400px] items-center justify-between gap-4 px-5 py-3 sm:px-8">
          <span className="flex items-center gap-2">
            <span aria-hidden className="grid h-6 w-6 place-items-center bg-ink">
              <span className="h-2.5 w-2.5 bg-accent" />
            </span>
            <span className="text-meta font-black uppercase tracking-tight">SRE Memory Agent</span>
          </span>
          <span
            role="status"
            className="flex items-center gap-2 text-label font-black uppercase tracking-widest text-status-idle"
          >
            <span aria-hidden className="h-2 w-2 animate-pulse-slow bg-accent" />
            Loading
          </span>
        </div>
      </div>
    </div>
  )
}

export function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          {/* The public entry point. */}
          <Route path="/" element={<Landing />} />
          <Route path="/landing" element={<Navigate to="/" replace />} />

          {LEGACY_ROUTES.map((path) => (
            <Route key={path} path={path} element={<LegacyLink />} />
          ))}

          {DASHBOARD_ROUTES.map((route) => (
            <Route
              key={route.path}
              path={route.path}
              element={<Dashboard>{route.element}</Dashboard>}
            />
          ))}

          {/* An unknown path inside the application is a dashboard 404, not a redirect. */}
          <Route
            path={`${APP_PATH}/*`}
            element={
              <Dashboard>
                <NotFound />
              </Dashboard>
            }
          />

          {/* Anything else belongs to the public page. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
