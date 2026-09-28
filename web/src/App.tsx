import { Suspense, lazy, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AppShell, Page } from './components/AppShell'
import { Failure, Loading } from './components/primitives'
import { ApiError } from './lib/api'
import { SystemProvider, useSystem } from './lib/system'

// Pages are split so the first paint does not carry the whole application.
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

export function App() {
  return (
    <BrowserRouter>
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
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/incidents" element={<Incidents />} />
                <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
                <Route path="/memory" element={<Memory />} />
                <Route path="/repairs" element={<Repairs />} />
                <Route path="/review" element={<Review />} />
                <Route path="/sandbox" element={<Sandbox />} />
                <Route path="/learning" element={<Learning />} />
                <Route path="/system" element={<System />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/repository" element={<Navigate to="/system" replace />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </ConnectionGate>
        </AppShell>
      </SystemProvider>
    </BrowserRouter>
  )
}
