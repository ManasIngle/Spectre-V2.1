import React, { useState, useEffect, useCallback } from 'react';

const MLLogsView = () => {
  const [logs, setLogs] = useState([]);
  const [date, setDate] = useState('');             // empty = let backend pick today (with auto-fallback)
  const [servedDate, setServedDate] = useState(''); // what the backend actually returned
  const [requestedDate, setRequestedDate] = useState('');
  const [fellBack, setFellBack] = useState(false);
  const [availableDates, setAvailableDates] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchLogs = useCallback(async () => {
    try {
      const url = date ? `/api/ml-logs?date=${date}` : '/api/ml-logs';
      const res = await fetch(url);
      const json = await res.json();
      setLogs(json.logs || []);
      setServedDate(json.date || '');
      setRequestedDate(json.requested_date || '');
      setFellBack(!!json.fell_back);
      setAvailableDates(json.available_dates || []);
    } catch (err) {
      console.error('Failed to fetch ML logs:', err);
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => {
    fetchLogs();
    const intervalId = setInterval(fetchLogs, 15000); // refresh every 15s
    return () => clearInterval(intervalId);
  }, [fetchLogs]);

  if (loading && logs.length === 0) {
    return <div className="p-card glass" style={{ textAlign: 'center', padding: '2rem' }}>Loading Logs...</div>;
  }

  return (
    <div className="fade-in">
      {/* Date selector + status banner */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Date:</label>
        <select
          className="dropdown"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          style={{ padding: '0.3rem 0.5rem' }}
        >
          <option value="">Today (auto-fallback)</option>
          {availableDates.map(d => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        {date && (
          <button className="nav-tab" onClick={() => setDate('')} style={{ padding: '0.2rem 0.55rem', fontSize: '0.75rem' }}>
            Clear
          </button>
        )}
        <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {logs.length} row{logs.length !== 1 ? 's' : ''}
          {availableDates.length > 0 && ` · ${availableDates.length} day${availableDates.length !== 1 ? 's' : ''} of history`}
        </span>
      </div>

      {fellBack && (
        <div style={{
          padding: '0.5rem 0.75rem', borderRadius: 6, marginBottom: '0.75rem',
          background: 'rgba(0,255,255,0.06)', border: '1px solid rgba(0,255,255,0.18)',
          fontSize: '0.78rem',
        }}>
          No data for <strong>{requestedDate}</strong> yet (cron runs 09:00–15:30 IST).
          Showing most recent day with data: <strong>{servedDate}</strong>.
        </div>
      )}

      <div className="table-container" style={{ position: 'relative' }}>
        <table className="nifty-table glass">
          <thead>
            <tr>
              <th>Time</th>
              <th>Signal</th>
              <th>Confidence</th>
              <th>Spot Price</th>
              <th>Strike</th>
              <th>Option LTP</th>
              <th>Target (Nifty)</th>
              <th>Stop Loss (Nifty)</th>
              <th>LSTM Up|Down</th>
              <th>XGB Up|Down</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log, i) => {
              const isCall = log.Signal?.includes('CE') || log.Prediction === 'UP';
              const sigClass = isCall ? 'bg-success' : 'bg-danger';

              return (
                <tr key={i}>
                  <td>{log.Time}</td>
                  <td><span className={`badge ${sigClass}`}>{log.Signal || log.Prediction}</span></td>
                  <td>{parseFloat(log.Confidence || 0).toFixed(1)}%</td>
                  <td>{log.Spot}</td>
                  <td>{log.Strike} {log.OptionType}</td>
                  <td style={{ fontWeight: 700, color: isCall ? '#10b981' : '#ef4444' }}>
                    {log.Option_LTP ? `₹${parseFloat(log.Option_LTP).toFixed(2)}` : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                  </td>
                  <td style={{ color: 'var(--accent-green)' }}>{log.Target}</td>
                  <td style={{ color: 'var(--accent-red)' }}>{log.SL}</td>
                  <td style={{ fontSize: '0.8rem' }}>
                    <span style={{ color: 'var(--accent-green)' }}>{log.LSTM_Up}%</span> | <span style={{ color: 'var(--accent-red)' }}>{log.LSTM_Down}%</span>
                  </td>
                  <td style={{ fontSize: '0.8rem' }}>
                    <span style={{ color: 'var(--accent-green)' }}>{log.XGB_Up}%</span> | <span style={{ color: 'var(--accent-red)' }}>{log.XGB_Down}%</span>
                  </td>
                </tr>
              );
            })}
            {logs.length === 0 && (
              <tr><td colSpan="10" style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--text-muted)' }}>
                {availableDates.length === 0
                  ? 'No logs recorded yet — system_signals.csv is empty (cron runs 09:00–15:30 IST).'
                  : `No rows for ${servedDate || requestedDate}. Pick another date above.`}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default MLLogsView;
