// Routing. The Figma Make export switched views with useState, so there were no
// deep links, a refresh dropped you back on the landing page, and the browser's
// back button did nothing.

import { Navigate, Route, BrowserRouter as Router, Routes, useLocation, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'

import AppShell from './components/AppShell'
import Guidelines from './Guidelines'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { C, SANS, serif } from './design'
import ComingSoonPage from './pages/ComingSoonPage'
import DashboardPage from './pages/DashboardPage'
import LandingPage from './pages/LandingPage'
import NotFoundPage from './pages/NotFoundPage'
import BackdropsView from './views/BackdropsView'
import ProcessingView from './views/ProcessingView'
import ResultsView from './views/ResultsView'
import UploadView from './views/UploadView'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  // Waiting on the stored token to be validated. Redirecting here would bounce
  // a signed-in user to the landing page on every refresh.
  if (loading) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: C.paper, fontFamily: SANS, fontSize: 14, color: C.inkSoft,
      }}>
        Loading…
      </div>
    )
  }

  if (!user) return <Navigate to="/" replace state={{ from: location }} />
  return <>{children}</>
}

/** Carries the listing id across the Results → Vehicles rename. */
function RedirectToVehicle() {
  const { listingId } = useParams()
  return <Navigate to={`/app/vehicles/${listingId}`} replace />
}

function Placeholder({ title }: { title: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ ...serif(40), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.02em' }}>{title}</p>
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0 }}>
          This view is not built yet.
        </p>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          {/* The coming-soon page is the public face; the landing page is
              reachable at /preview until the pipeline can back up its claims. */}
          <Route path="/" element={<ComingSoonPage />} />
          <Route path="/preview" element={<LandingPage />} />
          {/* The living style guide the brand guidelines reference. */}
          <Route path="/guidelines" element={<Guidelines />} />

          <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route index element={<DashboardPage />} />
            <Route path="vehicles" element={<ResultsView />} />
            <Route path="vehicles/:listingId" element={<ResultsView />} />
            {/* Upload and Processing are reachable but not in the nav: one is
                an action, the other a state of a vehicle. */}
            <Route path="upload" element={<UploadView />} />
            <Route path="processing" element={<ProcessingView />} />
            <Route path="processing/:listingId" element={<ProcessingView />} />
            <Route path="backdrops" element={<BackdropsView />} />
            <Route path="settings" element={<Placeholder title="Settings" />} />

            {/* The nav used to call these Results and Admin. Redirected rather
                than dropped so older links keep working. */}
            <Route path="results" element={<Navigate to="/app/vehicles" replace />} />
            <Route path="results/:listingId" element={<RedirectToVehicle />} />
            <Route path="admin" element={<Navigate to="/app/settings" replace />} />
          </Route>

          {/* A designed 404 rather than a silent redirect, which would drop a
              signed-in user onto the public page as if they had been logged out. */}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Router>
    </AuthProvider>
  )
}
