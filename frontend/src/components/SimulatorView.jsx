import { useEffect, useState } from 'react';
import JournalView from './JournalView';

const API = '';

const PnLCell = ({ value }) => {
    if (value == null || value === 0) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    const cls = value >= 0 ? 'val-positive' : 'val-negative';
    const sign = value > 0 ? '+' : '';
    return <span className={cls}>{sign}{value.toFixed(2)}%</span>;
};

const ReasonBadge = ({ reason }) => {
    if (!reason) return null;
    const colorMap = {
        TARGET: 'sig-buy',
        SL: 'sig-sell',
        TIMEOUT: 'sig-neutral',
        FLIP: 'sig-neutral',
        EOD: 'sig-neutral',
        OPEN: 'sig-buy-1',
    };
    return <span className={`signal-badge ${colorMap[reason] || 'sig-neutral'}`}>{reason}</span>;
};

const SimulatorView = () => {
    const [state, setState] = useState({ open: [], closed: [] });
    const [scorecard, setScorecard] = useState([]);
    const [scorecardDays, setScorecardDays] = useState(7);
    const [tab, setTab] = useState('positions'); // positions | scorecard
    const [loading, setLoading] = useState(false);

    const fetchAll = async () => {
        setLoading(true);
        try {
            const [stateRes, scoreRes] = await Promise.all([
                fetch(`${API}/api/simulator/state`),
                fetch(`${API}/api/simulator/scorecard?days=${scorecardDays}`),
            ]);
            const stateJson = await stateRes.json();
            const scoreJson = await scoreRes.json();
            setState({ open: stateJson.open || [], closed: stateJson.closed || [] });
            setScorecard(scoreJson.data || []);
        } catch (e) {
            console.error('Simulator fetch error:', e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAll();
        const id = setInterval(fetchAll, 60000);
        return () => clearInterval(id);
    }, [scorecardDays]);

    const totalPnL = state.closed.reduce((sum, p) => sum + (p.pnl_premium_pct || 0), 0);
    const wins = state.closed.filter(p => (p.pnl_premium_pct || 0) > 0).length;
    const losses = state.closed.filter(p => (p.pnl_premium_pct || 0) < 0).length;

    return (
        <div style={{ padding: '1rem' }}>
            {/* Sub-tab nav */}
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                        className={`nav-tab${tab === 'positions' ? ' active' : ''}`}
                        onClick={() => setTab('positions')}
                    >Positions</button>
                    <button
                        className={`nav-tab${tab === 'journal' ? ' active' : ''}`}
                        onClick={() => setTab('journal')}
                    >Journal</button>
                    <button
                        className={`nav-tab${tab === 'scorecard' ? ' active' : ''}`}
                        onClick={() => setTab('scorecard')}
                    >Model Scorecard</button>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    {tab === 'scorecard' && (
                        <select
                            className="dropdown"
                            value={scorecardDays}
                            onChange={(e) => setScorecardDays(Number(e.target.value))}
                        >
                            <option value={1}>Today</option>
                            <option value={7}>Last 7 days</option>
                            <option value={30}>Last 30 days</option>
                        </select>
                    )}
                    {tab !== 'journal' && (
                        <a
                            href={`/api/simulator/${tab === 'positions' ? 'executed' : 'scorecard'}/download`}
                            className="nav-tab"
                            style={{ textDecoration: 'none' }}
                        >Download CSV</a>
                    )}
                </div>
            </div>

            {tab === 'positions' && (
                <>
                    {/* Day summary */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
                        <div className="glass" style={{ padding: '0.75rem' }}>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Open</div>
                            <div style={{ fontSize: '1.5rem' }}>{state.open.length}</div>
                        </div>
                        <div className="glass" style={{ padding: '0.75rem' }}>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Closed Today</div>
                            <div style={{ fontSize: '1.5rem' }}>{state.closed.length}</div>
                        </div>
                        <div className="glass" style={{ padding: '0.75rem' }}>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Win / Loss</div>
                            <div style={{ fontSize: '1.5rem' }}>
                                <span className="val-positive">{wins}</span> / <span className="val-negative">{losses}</span>
                            </div>
                        </div>
                        <div className="glass" style={{ padding: '0.75rem' }}>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Cumulative P&L</div>
                            <div style={{ fontSize: '1.5rem' }}>
                                <PnLCell value={totalPnL} />
                            </div>
                        </div>
                    </div>

                    {/* Open Positions */}
                    {state.open.length > 0 && (
                        <div style={{ marginBottom: '1.5rem' }}>
                            <h3 style={{ marginBottom: '0.5rem' }}>Open Positions</h3>
                            <div className="table-container glass">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Time</th>
                                            <th>Strike</th>
                                            <th>Type</th>
                                            <th>Conf</th>
                                            <th>Entry Spot</th>
                                            <th>Spot Now</th>
                                            <th>Entry Prem</th>
                                            <th>Prem Now</th>
                                            <th>Unreal P&L</th>
                                            <th>Target</th>
                                            <th>SL</th>
                                            <th>Hold Min</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {state.open.map((p, i) => (
                                            <tr key={i}>
                                                <td>{p.entry_time}</td>
                                                <td>{p.strike?.toFixed(0)}</td>
                                                <td>{p.option_type}</td>
                                                <td>{p.confidence?.toFixed(1)}%</td>
                                                <td>{p.entry_spot?.toFixed(2)}</td>
                                                <td>{p.current_spot?.toFixed(2) || '—'}</td>
                                                <td>{p.entry_premium?.toFixed(2)}</td>
                                                <td>{p.current_premium?.toFixed(2) || '—'}</td>
                                                <td><PnLCell value={p.unrealized_pct} /></td>
                                                <td>{p.target_nifty?.toFixed(1)}</td>
                                                <td>{p.sl_nifty?.toFixed(1)}</td>
                                                <td>{p.est_hold_min}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Closed Positions */}
                    <h3 style={{ marginBottom: '0.5rem' }}>Closed Today ({state.closed.length})</h3>
                    {state.closed.length === 0 ? (
                        <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                            No closed positions yet today.
                        </div>
                    ) : (
                        <div className="table-container glass">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Entry → Exit</th>
                                        <th>Strike</th>
                                        <th>Type</th>
                                        <th>Conf</th>
                                        <th>Entry Spot</th>
                                        <th>Exit Spot</th>
                                        <th>Entry Prem</th>
                                        <th>Exit Prem</th>
                                        <th>Reason</th>
                                        <th>Hold Min</th>
                                        <th>Spot P&L</th>
                                        <th>Premium P&L</th>
                                        <th>₹ P&L (lot 65)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {state.closed.map((p, i) => (
                                        <tr key={i}>
                                            <td>{p.entry_time} → {p.exit_time}</td>
                                            <td>{p.strike?.toFixed(0)}</td>
                                            <td>{p.option_type}</td>
                                            <td>{p.confidence?.toFixed(1)}%</td>
                                            <td>{p.entry_spot?.toFixed(2)}</td>
                                            <td>{p.exit_spot?.toFixed(2)}</td>
                                            <td>{p.entry_premium?.toFixed(2)}</td>
                                            <td>{p.exit_premium?.toFixed(2)}</td>
                                            <td><ReasonBadge reason={p.exit_reason} /></td>
                                            <td>{p.hold_min}</td>
                                            <td><PnLCell value={p.pnl_spot_pct} /></td>
                                            <td><PnLCell value={p.pnl_premium_pct} /></td>
                                            <td className={p.pnl_rupees >= 0 ? 'val-positive' : 'val-negative'}>
                                                {p.pnl_rupees > 0 ? '+' : ''}₹{p.pnl_rupees?.toFixed(0)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}

            {tab === 'journal' && <JournalView />}

            {tab === 'scorecard' && (
                <>
                    {scorecard.length === 0 ? (
                        <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                            No scorecard data yet — runs daily at 15:35 IST.
                        </div>
                    ) : (
                        <div className="table-container glass">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Date</th>
                                        <th>Model</th>
                                        <th>Total</th>
                                        <th>Directional</th>
                                        <th>Buy</th>
                                        <th>Sell</th>
                                        <th>NoTrade</th>
                                        <th>Dir Acc</th>
                                        <th>Avg Conf (Right)</th>
                                        <th>Avg Conf (Wrong)</th>
                                        <th>Best Hour</th>
                                        <th>Worst Hour</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {scorecard.map((r, i) => (
                                        <tr key={i}>
                                            <td>{r.date}</td>
                                            <td><strong>{r.model}</strong></td>
                                            <td>{r.total}</td>
                                            <td>{r.directional}</td>
                                            <td className="val-positive">{r.buy}</td>
                                            <td className="val-negative">{r.sell}</td>
                                            <td style={{ color: 'var(--text-muted)' }}>{r.no_trade}</td>
                                            <td>
                                                <span className={`signal-badge ${r.dir_acc_pct >= 60 ? 'sig-buy' : r.dir_acc_pct >= 50 ? 'sig-neutral' : 'sig-sell'}`}>
                                                    {r.dir_acc_pct?.toFixed(1)}%
                                                </span>
                                            </td>
                                            <td>{r.avg_conf_right?.toFixed(1)}%</td>
                                            <td>{r.avg_conf_wrong?.toFixed(1)}%</td>
                                            <td>{r.best_hour >= 0 ? `${r.best_hour}:00` : '—'}</td>
                                            <td>{r.worst_hour >= 0 ? `${r.worst_hour}:00` : '—'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}

            {loading && <div className="loader" style={{ marginTop: '1rem' }} />}
        </div>
    );
};

export default SimulatorView;
