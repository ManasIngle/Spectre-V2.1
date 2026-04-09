import React, { useState, useEffect } from 'react';

const MLLogsView = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const res = await fetch('/api/ml-logs');
        const json = await res.json();
        setLogs(json.logs || []);
      } catch (err) {
        console.error('Failed to fetch ML logs:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchLogs();
    const intervalId = setInterval(fetchLogs, 15000); // refresh every 15s
    return () => clearInterval(intervalId);
  }, []);

  if (loading && logs.length === 0) {
    return <div className="p-card glass" style={{ textAlign: 'center', padding: '2rem' }}>Loading Logs...</div>;
  }

  return (
    <div className="table-container fade-in" style={{ position: 'relative' }}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '10px' }}>
            <button 
                onClick={() => window.open('/api/ml-logs/download', '_blank')}
                style={{
                  padding: '8px 16px',
                  background: 'linear-gradient(45deg, #0d6efd, #0dcaf0)',
                  color: 'white', border: 'none', borderRadius: '4px',
                  cursor: 'pointer', fontWeight: 'bold'
                }}
            >
                📥 Download Full CSV
            </button>
        </div>
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
            <tr><td colSpan="10" style={{ textAlign: 'center', padding: '1rem' }}>No logs recorded for today yet.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

export default MLLogsView;
