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

const API = ''

function App() {
  const [view, setView] = useState('signals')
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
      // OI view manages its own refresh internally
      setLoading(false)
    }

    doFetch()

    // Auto-refresh: 30s for trader view, 3 min for heatmap, OI handles itself
    if (view !== 'oi') {
      const refreshMs = view === 'table' ? 30000 : 180000
      timerRef.current = setInterval(doFetch, refreshMs)
    }

    return () => clearInterval(timerRef.current)
  }, [view, interval, fetchDashboard, fetchHeatmap])

  return (
    <div className="app-container">
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
          Spectre v1.2
        </div>

        <div className="controls-bar">
          <DataHealthWidget />

          {lastUpdate && (
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Updated: {lastUpdate.toLocaleTimeString()}
            </span>
          )}

          <select className="dropdown" value={view} onChange={(e) => setView(e.target.value)}>
            <option value="table">📊 Multitimeframe Indicators</option>
            <option value="heatmap">🗺️ NSE Market Heatmap</option>
            <option value="oi">📈 Nifty OI Trending</option>
            <option value="direction">🎯 Market Direction</option>
            <option value="signals">🤖 Trade Signals (ML)</option>
            <option value="ml-logs">📝 ML Trade Logs (Raw)</option>
            <option value="institutional">🏦 Institutional Outlook</option>
            <option value="news">📰 Breaking News</option>
          </select>

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
        </div>
      </header>

      <main className="main-content">
        {view === 'table' ? (
          <TraderViewTable data={data} interval={interval} />
        ) : view === 'heatmap' ? (
          <Heatmap data={heatmapData} total={heatmapMeta.total} requested={heatmapMeta.requested} />
        ) : view === 'oi' ? (
          <OITrendingView />
        ) : view === 'direction' ? (
          <MarketDirectionView />
        ) : view === 'signals' ? (
          <TradeSignalsView />
        ) : view === 'ml-logs' ? (
          <MLLogsView />
        ) : view === 'institutional' ? (
          <InstitutionalView />
        ) : (
          <NewsView />
        )}
      </main>
    </div>
  )
}

export default App
