import { useState, useEffect, useCallback, useRef } from 'react'
import './index.css'
import TraderViewTable from './components/TraderViewTable'
import Heatmap from './components/Heatmap'
import DataHealthWidget from './components/DataHealthWidget'
import OITrendingView from './components/OITrendingView'
import MarketDirectionView from './components/MarketDirectionView'
import TradeSignalsView from './components/TradeSignalsView'
import InstitutionalView from './components/InstitutionalView'
import NewsView from './components/NewsView'
import MLLogsView from './components/MLLogsView'
import CockpitView from './components/CockpitView'
import OvernightView from './components/OvernightView'
import DownloadView from './components/DownloadView'
import SimulatorView from './components/SimulatorView'
import LoginView from './components/LoginView'
import UsersAdminView from './components/UsersAdminView'
import { useAuth } from './AuthContext'

const API = ''

const ALL_TABS = [
  { key: 'cockpit',      label: 'Cockpit' },
  { key: 'signals',      label: 'Trade Signals' },
  { key: 'direction',    label: 'Market Direction' },
  { key: 'oi',           label: 'OI Trending' },
  { key: 'table',        label: 'Multitimeframe' },
  { key: 'heatmap',      label: 'Heatmap' },
  { key: 'institutional',label: 'Institutional' },
  { key: 'news',         label: 'News' },
  { key: 'simulator',    label: 'Simulator' },
  { key: 'download',     label: 'Download',  adminOnly: true },
  { key: 'overnight',    label: 'Overnight' },
]

function App() {
  const { user, role, loading: authLoading, isAdmin, logout } = useAuth()
  const [view, setView] = useState('cockpit')
  const [showUsersAdmin, setShowUsersAdmin] = useState(false)
  const TABS = ALL_TABS.filter(t => !t.adminOnly || isAdmin)

  // If a non-admin lands on (or somehow ends up on) an admin-only view, send them home
  useEffect(() => {
    if (!user) return
    const tab = ALL_TABS.find(t => t.key === view)
    if (tab && tab.adminOnly && !isAdmin) {
      setView('cockpit')
    }
  }, [view, user, isAdmin])
  const [interval, setIntervalVal] = useState('3m')
  const [data, setData] = useState([])
  const [heatmapData, setHeatmapData] = useState([])
  const [heatmapMeta, setHeatmapMeta] = useState({})
  const [loading, setLoading] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)
  const timerRef = useRef(null)

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/dashboard?interval=${interval}`)
      const json = await res.json()
      setData(json.data || [])
      setLastUpdate(new Date())
    } catch (e) {
      console.error('Dashboard fetch error:', e)
    }
  }, [interval])

  const fetchHeatmap = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/heatmap`)
      const json = await res.json()
      setHeatmapData(json.data || [])
      setHeatmapMeta({ total: json.total, requested: json.requested })
      setLastUpdate(new Date())
    } catch (e) {
      console.error('Heatmap fetch error:', e)
    }
  }, [])

  // Initial load & auto-refresh
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)

    const doFetch = async () => {
      setLoading(true)
      if (view === 'table') {
        await fetchDashboard()
      } else if (view === 'heatmap') {
        await fetchHeatmap()
      }
      // OI, cockpit, signals, direction, institutional manage their own refresh
      setLoading(false)
    }

    doFetch()

    // Auto-refresh: 30s for trader view, 3 min for heatmap, others handle themselves
    if (view !== 'oi' && view !== 'cockpit' && view !== 'signals' && view !== 'direction' && view !== 'institutional' && view !== 'overnight' && view !== 'download' && view !== 'simulator') {
      const refreshMs = view === 'table' ? 30000 : 180000
      timerRef.current = setInterval(doFetch, refreshMs)
    }

    return () => clearInterval(timerRef.current)
  }, [view, interval, fetchDashboard, fetchHeatmap])

  // Auth gate: while loading, show nothing; if not authed, show login
  if (authLoading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="loader" />
      </div>
    )
  }
  if (!user) {
    return <LoginView />
  }

  return (
    <div className="app-container">
      {showUsersAdmin && <UsersAdminView onClose={() => setShowUsersAdmin(false)} />}
      <header className="header glass">
        <div className="header-title">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="url(#grad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <defs>
              <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style={{ stopColor: '#0ff' }} />
                <stop offset="100%" style={{ stopColor: '#f0f' }} />
              </linearGradient>
            </defs>
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
          Spectre Go v1.0
        </div>

        <div className="controls-bar">
          <DataHealthWidget />

          {lastUpdate && (
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Updated: {lastUpdate.toLocaleTimeString()}
            </span>
          )}

          {/* Horizontal pill tabs */}
          <nav className="nav-tabs">
            {TABS.map(tab => (
              <button
                key={tab.key}
                className={`nav-tab${view === tab.key ? ' active' : ''}`}
                onClick={() => setView(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          {/* Interval selector only for Multitimeframe view */}
          {view === 'table' && (
            <select className="dropdown" value={interval} onChange={(e) => setIntervalVal(e.target.value)}>
              <option value="1m">1 Min</option>
              <option value="3m">3 Min</option>
              <option value="5m">5 Min</option>
              <option value="15m">15 Min</option>
              <option value="30m">30 Min</option>
              <option value="60m">1 Hour</option>
            </select>
          )}

          {loading && <div className="loader" style={{ width: 20, height: 20 }}></div>}

          {/* User chip + admin/logout */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginLeft: '0.5rem' }}>
            <span style={{
              fontSize: '0.75rem',
              padding: '0.25rem 0.6rem',
              background: 'rgba(0,0,0,0.3)',
              borderRadius: 12,
              border: '1px solid rgba(255,255,255,0.1)',
            }}>
              {user} · <span style={{ color: isAdmin ? '#0ff' : 'var(--text-muted)' }}>{role}</span>
            </span>
            {isAdmin && (
              <button
                className="nav-tab"
                onClick={() => setShowUsersAdmin(true)}
                title="Manage users"
                style={{ padding: '0.25rem 0.5rem', fontSize: '0.85rem' }}
              >⚙</button>
            )}
            <button
              className="nav-tab"
              onClick={logout}
              style={{ padding: '0.25rem 0.6rem', fontSize: '0.8rem' }}
            >Logout</button>
          </div>
        </div>
      </header>

      <main className="main-content">
        {view === 'cockpit' ? (
          <CockpitView />
        ) : view === 'table' ? (
          <TraderViewTable data={data} interval={interval} />
        ) : view === 'heatmap' ? (
          <Heatmap data={heatmapData} total={heatmapMeta.total} requested={heatmapMeta.requested} />
        ) : view === 'oi' ? (
          <OITrendingView />
        ) : view === 'direction' ? (
          <MarketDirectionView />
        ) : view === 'signals' ? (
          <TradeSignalsView />
        ) : view === 'simulator' ? (
          <SimulatorView />
        ) : view === 'download' ? (
          <DownloadView />
        ) : view === 'institutional' ? (
          <InstitutionalView />
        ) : view === 'overnight' ? (
          <OvernightView />
        ) : (
          <NewsView />
        )}
      </main>
    </div>
  )
}

export default App
