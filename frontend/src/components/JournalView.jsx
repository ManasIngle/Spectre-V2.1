import { useEffect, useState } from 'react';
import TradeChart from './TradeChart';

const API = '';

const PnL = ({ value, suffix = '%' }) => {
    if (value == null || value === 0) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    const cls = value >= 0 ? 'val-positive' : 'val-negative';
    const sign = value > 0 ? '+' : '';
    return <span className={cls}>{sign}{value.toFixed(2)}{suffix}</span>;
};

const ReasonBadge = ({ reason }) => {
    const map = {
        TARGET: 'sig-buy',
        SL: 'sig-sell',
        TIMEOUT: 'sig-neutral',
        FLIP: 'sig-neutral',
        EOD: 'sig-neutral',
    };
    return <span className={`signal-badge ${map[reason] || 'sig-neutral'}`}>{reason}</span>;
};

const ModelChip = ({ name, signal }) => {
    const isBuy = signal && signal.includes('CE');
    const isSell = signal && signal.includes('PE');
    const cls = isBuy ? 'sig-buy' : isSell ? 'sig-sell' : 'sig-neutral';
    return (
        <span style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', margin: '0 8px' }}>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{name}</span>
            <span className={`signal-badge ${cls}`} style={{ marginTop: 2 }}>{signal || '—'}</span>
        </span>
    );
};

const JournalView = () => {
    const [trades, setTrades] = useState([]);
    const [days, setDays] = useState(7);
    const [date, setDate] = useState(''); // empty means use days range
    const [expandedKey, setExpandedKey] = useState(null);
    const [detail, setDetail] = useState(null);
    const [loadingList, setLoadingList] = useState(false);
    const [loadingDetail, setLoadingDetail] = useState(false);

    const tradeKey = (t) => `${t.date}|${t.entry_time}|${t.strike}|${t.option_type}`;

    const fetchList = async () => {
        setLoadingList(true);
        try {
            const url = date
                ? `${API}/api/simulator/journal?date=${date}`
                : `${API}/api/simulator/journal?days=${days}`;
            const res = await fetch(url);
            const json = await res.json();
            setTrades(json.data || []);
        } catch (e) {
            console.error('Journal list error:', e);
        } finally {
            setLoadingList(false);
        }
    };

    const fetchDetail = async (t) => {
        setLoadingDetail(true);
        setDetail(null);
        try {
            const params = new URLSearchParams({
                date: t.date,
                time: t.entry_time,
                strike: t.strike,
                type: t.option_type,
            });
            const res = await fetch(`${API}/api/simulator/journal/detail?${params}`);
            const json = await res.json();
            if (res.ok) setDetail(json);
            else setDetail({ error: json.error || 'Failed to load' });
        } catch (e) {
            setDetail({ error: e.message });
        } finally {
            setLoadingDetail(false);
        }
    };

    useEffect(() => {
        fetchList();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [days, date]);

    const onRowClick = (t) => {
        const key = tradeKey(t);
        if (expandedKey === key) {
            setExpandedKey(null);
            setDetail(null);
        } else {
            setExpandedKey(key);
            fetchDetail(t);
        }
    };

    return (
        <div style={{ padding: '0.5rem' }}>
            {/* Filters */}
            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', alignItems: 'center' }}>
                <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Range:</label>
                <select className="dropdown" value={days} onChange={(e) => { setDays(Number(e.target.value)); setDate(''); }}>
                    <option value={1}>Today</option>
                    <option value={7}>Last 7 days</option>
                    <option value={30}>Last 30 days</option>
                </select>
                <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>or Date:</label>
                <input
                    type="date"
                    className="dropdown"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    style={{ padding: '4px 8px' }}
                />
                {date && (
                    <button className="nav-tab" onClick={() => setDate('')}>Clear date</button>
                )}
                <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    {trades.length} trade{trades.length !== 1 ? 's' : ''}
                </span>
            </div>

            {trades.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    {loadingList ? 'Loading...' : 'No closed trades for this range. Trades populate as the simulator closes positions.'}
                </div>
            ) : (
                <div className="table-container glass">
                    <table>
                        <thead>
                            <tr>
                                <th></th>
                                <th>Date</th>
                                <th>Entry → Exit</th>
                                <th>Strike</th>
                                <th>Type</th>
                                <th>Conf</th>
                                <th>Reason</th>
                                <th>Hold</th>
                                <th>Spot P&L</th>
                                <th>Premium P&L</th>
                                <th>₹ P&L</th>
                            </tr>
                        </thead>
                        <tbody>
                            {trades.map((t) => {
                                const key = tradeKey(t);
                                const isOpen = expandedKey === key;
                                return (
                                    <>
                                        <tr
                                            key={key}
                                            onClick={() => onRowClick(t)}
                                            style={{ cursor: 'pointer' }}
                                            className={isOpen ? 'row-active' : ''}
                                        >
                                            <td style={{ width: 24 }}>{isOpen ? '▼' : '▶'}</td>
                                            <td>{t.date}</td>
                                            <td>{t.entry_time?.slice(0, 5)} → {t.exit_time?.slice(0, 5)}</td>
                                            <td>{t.strike?.toFixed(0)}</td>
                                            <td>{t.option_type}</td>
                                            <td>{t.confidence?.toFixed(1)}%</td>
                                            <td><ReasonBadge reason={t.exit_reason} /></td>
                                            <td>{t.hold_min?.toFixed(0)}m</td>
                                            <td><PnL value={t.pnl_spot_pct} /></td>
                                            <td><PnL value={t.pnl_premium_pct} /></td>
                                            <td className={t.pnl_rupees >= 0 ? 'val-positive' : 'val-negative'}>
                                                {t.pnl_rupees > 0 ? '+' : ''}₹{t.pnl_rupees?.toFixed(0)}
                                            </td>
                                        </tr>
                                        {isOpen && (
                                            <tr key={key + '-detail'}>
                                                <td colSpan={11} style={{ padding: '1rem', background: 'rgba(0,0,0,0.25)' }}>
                                                    <DetailPanel detail={detail} loading={loadingDetail} trade={t} />
                                                </td>
                                            </tr>
                                        )}
                                    </>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

const DetailPanel = ({ detail, loading, trade }) => {
    if (loading) return <div style={{ padding: '1rem', color: 'var(--text-muted)' }}>Loading trade detail…</div>;
    if (!detail) return null;
    if (detail.error) return <div style={{ color: 'var(--accent-sell)' }}>Error: {detail.error}</div>;

    const t = detail.trade;
    const spotMarkers = [
        { t: t.entry_time, label: 'Entry', type: 'entry' },
        { t: t.exit_time, label: 'Exit', type: 'exit' },
    ];
    const spotLines = [
        { value: t.target_nifty, label: 'Target', color: '#0f0' },
        { value: t.entry_spot, label: 'Entry', color: 'rgba(255,255,255,0.5)', dashed: false },
        { value: t.sl_nifty, label: 'SL', color: '#f44' },
    ];

    // Premium chart: best premium marker
    const bestPremTime = (() => {
        if (!detail.prem_series || detail.prem_series.length === 0) return null;
        let best = detail.prem_series[0];
        for (const p of detail.prem_series) {
            if (p.premium > best.premium) best = p;
        }
        return best.time;
    })();
    const premMarkers = [
        { t: t.entry_time, label: 'Entry', type: 'entry' },
        { t: t.exit_time, label: 'Exit', type: 'exit' },
        ...(bestPremTime ? [{ t: bestPremTime, label: 'Best', type: 'best' }] : []),
    ];
    const premLines = [
        { value: t.entry_premium, label: 'Entry', color: 'rgba(255,255,255,0.5)' },
    ];

    return (
        <div>
            {/* Summary header */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.5rem', marginBottom: '1rem', alignItems: 'center' }}>
                <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Signal</div>
                    <div style={{ fontWeight: 'bold' }}>{t.signal} {t.strike?.toFixed(0)} {t.option_type}</div>
                </div>
                <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Entry → Exit</div>
                    <div>{t.entry_time?.slice(0, 5)} → {t.exit_time?.slice(0, 5)} ({t.hold_min?.toFixed(0)}m)</div>
                </div>
                <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Reason</div>
                    <div><ReasonBadge reason={t.exit_reason} /></div>
                </div>
                <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Premium P&L</div>
                    <div style={{ fontSize: '1.1rem' }}><PnL value={t.pnl_premium_pct} /></div>
                </div>
                <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>₹ (lot 65)</div>
                    <div className={t.pnl_rupees >= 0 ? 'val-positive' : 'val-negative'}>
                        {t.pnl_rupees > 0 ? '+' : ''}₹{t.pnl_rupees?.toFixed(0)}
                    </div>
                </div>
                <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Best (post-entry)</div>
                    <div>+{((detail.best_premium - t.entry_premium) / t.entry_premium * 100).toFixed(1)}% @ +{detail.best_exit_min}m</div>
                </div>
                <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Efficiency</div>
                    <div>{detail.efficiency_pct?.toFixed(0)}%</div>
                </div>
            </div>

            {/* Charts side by side */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                <div>
                    <div style={{ fontSize: '0.85rem', marginBottom: 4, color: 'var(--text-muted)' }}>
                        Spot trajectory (entry−10m → exit+10m)
                    </div>
                    <TradeChart
                        data={detail.spot_series.map(p => ({ t: p.time, value: p.spot, phase: p.phase }))}
                        lines={spotLines}
                        markers={spotMarkers}
                        height={240}
                        width={560}
                        yLabel="Nifty Spot"
                        yFormat={(n) => n.toFixed(1)}
                    />
                </div>
                <div>
                    <div style={{ fontSize: '0.85rem', marginBottom: 4, color: 'var(--text-muted)' }}>
                        Premium trajectory ({t.option_type} {t.strike?.toFixed(0)})
                    </div>
                    <TradeChart
                        data={detail.prem_series.filter(p => p.premium > 0).map(p => ({ t: p.time, value: p.premium, phase: p.phase }))}
                        lines={premLines}
                        markers={premMarkers}
                        height={240}
                        width={560}
                        yLabel="Premium ₹"
                        yFormat={(n) => n.toFixed(2)}
                    />
                </div>
            </div>

            {/* Model agreement + metrics */}
            <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 4 }}>Model agreement at entry</div>
                    <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                        <ModelChip name="Rolling" signal={t.rolling_sig} />
                        <ModelChip name="Direction" signal={t.direction_sig} />
                        <ModelChip name="Cross" signal={t.cross_asset_sig} />
                    </div>
                </div>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: '1rem' }}>
                    <div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>MFE</div>
                        <div className="val-positive">+{detail.mfe_pct?.toFixed(2)}%</div>
                    </div>
                    <div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>MAE</div>
                        <div className="val-negative">{detail.mae_pct?.toFixed(2)}%</div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default JournalView;
