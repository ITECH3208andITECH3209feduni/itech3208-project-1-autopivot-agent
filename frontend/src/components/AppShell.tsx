// Signed-in layout: fixed sidebar plus the routed view.
//
// Object-first navigation. Upload and Processing are gone as nav items — you do
// not "go to" an upload, you add a vehicle, and Processing is a state of a
// vehicle rather than a place. That leaves the nav listing the three things the
// dealership actually owns, with a count against each.

import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { api, type NavCounts } from '../api/client'
import { useIsCompact, useIsWide } from '../useMediaQuery'
import { useAuth } from '../auth/AuthContext'
import {
  C, CONTENT_MAX_WIDTH, CONTENT_MAX_WIDTH_WIDE, MONO, RADIUS_CONTROL, SANS, SIDEBAR_WIDTH, serif,
} from '../design'

type NavItem = { label: string; to: string; count?: keyof NavCounts }

const PRIMARY_NAV: NavItem[] = [
  { label: 'Overview', to: '/app' },
  { label: 'Vehicles', to: '/app/vehicles', count: 'vehicles' },
  { label: 'Backdrops', to: '/app/backdrops', count: 'backdrops' },
]

const SECONDARY_NAV: NavItem[] = [{ label: 'Settings', to: '/app/settings' }]

function SearchField() {
  const navigate = useNavigate()
  const [term, setTerm] = useState('')
  const [focused, setFocused] = useState(false)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = term.trim()
    // Searching is a navigation, not a filter on whatever page you happen to be
    // on, so it always lands on Vehicles with the query in the URL — which
    // makes a result set linkable and survivable across a refresh.
    navigate(trimmed ? `/app/vehicles?q=${encodeURIComponent(trimmed)}` : '/app/vehicles')
  }

  return (
    <form onSubmit={submit} style={{ padding: '0 10px 10px' }}>
      <input
        type="search"
        value={term}
        onChange={e => setTerm(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder="Search vehicles"
        aria-label="Search vehicles"
        style={{
          width: '100%', fontFamily: SANS, fontSize: 13, color: C.ink,
          background: C.paper, borderRadius: RADIUS_CONTROL,
          padding: '8px 12px', outline: 'none', boxSizing: 'border-box',
          border: `1px solid ${focused ? C.forest : C.lineStrong}`,
          transition: 'border-color 0.15s',
        }}
      />
      {/* A form with no submit button does not reliably submit on Enter, so
          pressing it in the search field did nothing at all. Hidden rather than
          removed: screen readers still announce a way to run the search. */}
      <button type="submit" style={{
        position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
        overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0,
      }}>
        Search
      </button>
    </form>
  )
}

function NavRow({ item, counts }: { item: NavItem; counts: NavCounts | null }) {
  const value = item.count && counts ? counts[item.count] : null

  return (
    <NavLink
      to={item.to}
      // `end` on the index route only, so a child route does not also light up
      // Overview.
      end={item.to === '/app'}
      style={({ isActive }) => ({
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 8, fontFamily: SANS, fontSize: 14, fontWeight: isActive ? 500 : 400,
        color: isActive ? C.forest : C.inkSoft,
        background: isActive ? C.forestTint : 'none',
        border: 'none', borderRadius: RADIUS_CONTROL, padding: '9px 12px',
        textAlign: 'left', width: '100%', textDecoration: 'none',
        transition: 'background 0.12s, color 0.12s',
      })}
    >
      {({ isActive }) => (
        <>
          <span>{item.label}</span>
          {value !== null && value > 0 && (
            // Mono for the numeral, per the guidelines' rule that data and
            // labels are mono and prose is not.
            <span style={{
              fontFamily: MONO, fontSize: 11,
              color: isActive ? C.forest : C.inkSoft,
              opacity: isActive ? 1 : 0.75,
            }}>
              {value}
            </span>
          )}
        </>
      )}
    </NavLink>
  )
}

export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [counts, setCounts] = useState<NavCounts | null>(null)
  const compact = useIsCompact()
  const wide = useIsWide()
  const contentMaxWidth = wide ? CONTENT_MAX_WIDTH_WIDE : CONTENT_MAX_WIDTH
  const [menuOpen, setMenuOpen] = useState(false)

  // Refreshed on every navigation so a newly created vehicle is reflected
  // without a reload. Cheap: three COUNT(*) queries against indexed columns.
  // Router state, not window.location — the latter does not change on a
  // client-side navigation, so the counts would never update.
  const { pathname } = useLocation()
  useEffect(() => {
    let cancelled = false
    api.navCounts()
      .then(next => { if (!cancelled) setCounts(next) })
      .catch(() => { /* counts are decoration; the nav works without them */ })
    return () => { cancelled = true }
  }, [pathname])

  // Any navigation closes the slide-over; leaving it open over the page the
  // user just asked for is the classic mobile-nav annoyance.
  useEffect(() => setMenuOpen(false), [pathname])

  const dealership = user?.dealership
  const sidebarVisible = !compact || menuOpen

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: C.paper }}>
      {compact && (
        <header style={{
          position: 'fixed', top: 0, left: 0, right: 0, height: 56, zIndex: 45,
          background: C.white, borderBottom: `1px solid ${C.line}`,
          display: 'flex', alignItems: 'center', gap: 12, padding: '0 16px',
        }}>
          <button
            onClick={() => setMenuOpen(open => !open)}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={menuOpen}
            style={{
              width: 36, height: 36, display: 'flex', alignItems: 'center',
              justifyContent: 'center', background: 'none', cursor: 'pointer',
              border: `1px solid ${C.line}`, borderRadius: RADIUS_CONTROL, padding: 0,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              {menuOpen ? (
                <path d="M3 3L13 13M13 3L3 13" stroke={C.ink} strokeWidth="1.5" strokeLinecap="round" />
              ) : (
                <path d="M2 4h12M2 8h12M2 12h12" stroke={C.ink} strokeWidth="1.5" strokeLinecap="round" />
              )}
            </svg>
          </button>
          <span style={{ ...serif(18), color: C.ink, letterSpacing: '-0.01em' }}>
            AutoPivot Agent
          </span>
        </header>
      )}

      {compact && menuOpen && (
        <div
          onClick={() => setMenuOpen(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(26,26,23,0.4)', zIndex: 44 }}
        />
      )}

      <aside style={{
        position: 'fixed', top: 0, left: 0, bottom: 0, width: SIDEBAR_WIDTH,
        background: C.white, borderRight: `1px solid ${C.line}`,
        display: 'flex', flexDirection: 'column', zIndex: 46,
        // Translated rather than unmounted, so the panel slides instead of
        // appearing, and its scroll position survives being closed.
        transform: sidebarVisible ? 'translateX(0)' : `translateX(-${SIDEBAR_WIDTH}px)`,
        transition: compact ? 'transform 0.2s ease' : 'none',
        boxShadow: compact && menuOpen ? '0 0 32px rgba(26,26,23,0.18)' : 'none',
      }}>
        <div style={{ padding: '20px 20px 16px' }}>
          <span style={{ ...serif(20), color: C.ink, letterSpacing: '-0.01em' }}>
            AutoPivot Agent
          </span>
        </div>

        {/* The single primary action, per the guidelines' one-solid-button rule.
            It used to appear twice — once on Overview and once on Results —
            competing with itself for the same task. */}
        <div style={{ padding: '0 10px 12px' }}>
          <button
            onClick={() => navigate('/app/upload')}
            style={{
              width: '100%', fontFamily: SANS, fontSize: 14, fontWeight: 500,
              color: C.white, background: C.forest, border: 'none',
              borderRadius: RADIUS_CONTROL, padding: '10px 14px', cursor: 'pointer',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = C.forestLift)}
            onMouseLeave={e => (e.currentTarget.style.background = C.forest)}
          >
            + New vehicle
          </button>
        </div>

        <SearchField />

        <nav style={{ flex: 1, padding: '0 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {PRIMARY_NAV.map(item => (
            <NavRow key={item.to} item={item} counts={counts} />
          ))}

          <div style={{ borderTop: `1px solid ${C.line}`, margin: '12px 2px' }} />

          {SECONDARY_NAV.map(item => (
            <NavRow key={item.to} item={item} counts={counts} />
          ))}
        </nav>

        <div style={{ borderTop: `1px solid ${C.line}`, padding: '16px 20px' }}>
          <p style={{ fontFamily: SANS, fontSize: 14, fontWeight: 500, color: C.ink, margin: '0 0 2px' }}>
            {dealership?.name ?? 'AutoPivot'}
          </p>
          <p style={{ fontFamily: SANS, fontSize: 12, color: C.inkSoft, margin: '0 0 10px' }}>
            {dealership
              ? [
                  dealership.location,
                  `${dealership.user_count} user${dealership.user_count === 1 ? '' : 's'}`,
                ].filter(Boolean).join(' · ')
              : 'Platform administrator'}
          </p>
          <button
            onClick={() => { logout(); navigate('/') }}
            style={{
              fontFamily: SANS, fontSize: 13, color: C.inkSoft, background: 'none',
              border: 'none', cursor: 'pointer', padding: 0, transition: 'color 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = C.ink)}
            onMouseLeave={e => (e.currentTarget.style.color = C.inkSoft)}
          >
            Log out
          </button>
        </div>
      </aside>

      <main style={{
        flex: 1,
        marginLeft: compact ? 0 : SIDEBAR_WIDTH,
        paddingTop: compact ? 56 + 24 : 32,
        paddingLeft: compact ? 20 : 32,
        paddingRight: compact ? 20 : 32,
        paddingBottom: 32,
        minWidth: 0,
      }}>
        {/* margin auto, not just a max-width: without it the content block
            sits hard against the sidebar and a wide monitor gets a metre of
            dead space on the right, while a laptop — narrower than the cap —
            looks correctly centred and hides the bug. */}
        <div style={{ maxWidth: contentMaxWidth, margin: '0 auto' }}>
          <Outlet />
        </div>
      </main>
    </div>
  )
}
