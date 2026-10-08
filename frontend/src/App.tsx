
import { Navigate, Route, BrowserRouter as Router, Routes, useLocation, useParams } from 'react-router-dom'
import { useEffect, type ReactNode } from 'react'

import AppShell from './components/AppShell'
import Guidelines from './Guidelines'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { api } from './api/client'
import { C, SANS, serif } from './design'
import ComingSoonPage from './pages/ComingSoonPage'
import DashboardPage from './pages/DashboardPage'
import ChangePasswordPage from './pages/ChangePasswordPage'
import LandingPage from './pages/LandingPage'
import NotFoundPage from './pages/NotFoundPage'
import PlatformAdminPage from './pages/PlatformAdminPage'
import DealershipUsersPage from './pages/DealershipUsersPage'
import BackdropsView from './views/BackdropsView'
import ProcessingView from './views/ProcessingView'
import ResultsView from './views/ResultsView'
import UploadView from './views/UploadView'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

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
  if (user.must_change_password && location.pathname !== '/app/change-password') {
    return <Navigate to="/app/change-password" replace />
  }
  return <>{children}</>
}

function AppHome() {
  const { user } = useAuth()
  return user?.role === 'platform_admin' ? <Navigate to="/app/platform" replace /> : <DashboardPage />
}

function RequirePlatformAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  useEffect(() => {
    if (user && user.role !== 'platform_admin') {
      void api.platformDealerships().catch(() => undefined)
    }
  }, [user])

  if (user?.role === 'platform_admin') return <>{children}</>
  return (
    <div role="alert" style={{ padding: 24, background: C.white, color: C.ink, fontFamily: SANS }}>
      Your account does not have access to platform administration.
    </div>
  )
}

function RequireDealershipAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  useEffect(() => {
    if (user && user.role !== 'dealership_admin') {
      void api.dealershipUsers().catch(() => undefined)
    }
  }, [user])
  if (user?.role === 'dealership_admin') return <>{children}</>
  return <div role="alert" style={{ padding: 24, background: C.white, color: C.ink, fontFamily: SANS }}>
    Your account does not have access to dealership user management.
  </div>
}

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
          <Route path="/" element={<ComingSoonPage />} />
          <Route path="/preview" element={<LandingPage />} />
          <Route path="/guidelines" element={<Guidelines />} />

          <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route index element={<AppHome />} />
            <Route path="change-password" element={<ChangePasswordPage />} />
            <Route path="platform" element={<RequirePlatformAdmin><PlatformAdminPage /></RequirePlatformAdmin>} />
            <Route path="users" element={<RequireDealershipAdmin><DealershipUsersPage /></RequireDealershipAdmin>} />
            <Route path="vehicles" element={<ResultsView />} />
            <Route path="vehicles/:listingId" element={<ResultsView />} />
            <Route path="upload" element={<UploadView />} />
            <Route path="processing" element={<ProcessingView />} />
            <Route path="processing/:listingId" element={<ProcessingView />} />
            <Route path="backdrops" element={<BackdropsView />} />
            <Route path="settings" element={<Placeholder title="Settings" />} />

            <Route path="results" element={<Navigate to="/app/vehicles" replace />} />
            <Route path="results/:listingId" element={<RedirectToVehicle />} />
            <Route path="admin" element={<Navigate to="/app/settings" replace />} />
          </Route>

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Router>
    </AuthProvider>
  )
}
