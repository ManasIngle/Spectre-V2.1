import React, { useState, useEffect, useCallback } from 'react';

/* ── helpers ── */
const fmt2 = v => (v == null || isNaN(v)) ? '—' : Number(v).toFixed(2);
const fmt0 = v => (v == null || isNaN(v)) ? '—' : Number(v).toFixed(0);

const sigColor = type => type === 'CE' ? '#10b981' : type === 'PE' ? '#ef4444' : '#94a3b8';

/* ── Mini sparkline (LTP over time) ── */
const Sparkline = ({ points, color }) => {
    if (!points || points.length < 2) return <div style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}>—</div>;
    const ltps = points.map(p => p.ltp).filter(v => v > 0);
    if (ltps.length < 2) return <div style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}>no data</div>;
    const min = Math.min(...ltps);
    const max = Math.max(...ltps);
    const range = (max - min) || 1;
    const W = 120, H = 32;
    const path = points
        .map((p, i) => {
            const x = (i / (points.length - 1)) * W;
            const y = H - ((p.ltp - min) / range) * H;
            return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
        })
        .join(' ');
    return (
        <svg width={W} height={H} style={{ display: 'block' }}>
            <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
    );
};

/* ── Strike card ── */
const StrikeCard = ({ block }) => {
    const color = sigColor(block.option_type);
    const points = block.points || [];
    const ltps = points.map(p => p.ltp).filter(v => v > 0);
    const first = ltps[0] ?? 0;
    const last  = ltps[ltps.length - 1] ?? 0;
    const max   = ltps.length ? Math.max(...ltps) : 0;
    const min   = ltps.length ? Math.min(...ltps) : 0;
    const pnl   = first > 0 ? ((last - first) / first) * 100 : 0;
    const pnlColor = pnl > 1 ? '#10b981' : pnl < -1 ? '#ef4444' : '#94a3b8';

    return (
        <div className="cpanel" style={{ borderTop: `3px solid ${color}` }}>
            <div className="cpanel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 700 }}>{block.strike} {block.option_type}</span>
                <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', fontWeight: 400 }}>
                    suggested {block.first_suggested_at} · conf {block.suggestion_confidence?.toFixed(1)}%
                </span>
            </div>
            <div className="cpanel-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.4rem' }}>
                    <Stat label="First" value={fmt2(first)} />
                    <Stat label="Now"   value={fmt2(last)} color={color} />
                    <Stat label="High"  value={fmt2(max)} color="#10b981" />
                    <Stat label="Low"   value={fmt2(min)} color="#ef4444" />
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>LTP path</span>
                    <Sparkline points={points} color={color} />
                    <span style={{ fontSize: '0.78rem', fontWeight: 700, color: pnlColor, marginLeft: 'auto' }}>
                        {pnl > 0 ? '+' : ''}{pnl.toFixed(2)}%
                    </span>
                </div>

                <details style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                    <summary style={{ cursor: 'pointer' }}>Per-minute table ({points.length} pts)</summary>
                    <div style={{ maxHeight: 200, overflowY: 'auto', marginTop: '0.4rem' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.65rem' }}>
                            <thead>
                                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                                    <th style={{ padding: '2px 4px', textAlign: 'left' }}>Time</th>
                                    <th style={{ padding: '2px 4px', textAlign: 'right' }}>+min</th>
                                    <th style={{ padding: '2px 4px', textAlign: 'right' }}>Spot</th>
                                    <th style={{ padding: '2px 4px', textAlign: 'right' }}>LTP</th>
                                </tr>
                            </thead>
                            <tbody>
                                {points.map((p, i) => (
                                    <tr key={i} style={{ borderBottom: '1px solid rgba(42,49,67,0.3)' }}>
                                        <td style={{ padding: '2px 4px' }}>{p.time}</td>
                                        <td style={{ padding: '2px 4px', textAlign: 'right' }}>{p.min_since}</td>
                                        <td style={{ padding: '2px 4px', textAlign: 'right' }}>{fmt0(p.spot)}</td>
                                        <td style={{ padding: '2px 4px', textAlign: 'right', color: p.ltp > 0 ? color : 'var(--text-muted)' }}>{fmt2(p.ltp)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </details>
            </div>
        </div>
    );
};

const Stat = ({ label, value, color }) => (
    <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-color)', borderRadius: 6, padding: '0.3rem', textAlign: 'center' }}>
        <div style={{ fontSize: '0.55rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
        <div style={{ fontSize: '0.78rem', fontWeight: 700, color: color || 'var(--text-primary)', marginTop: 1 }}>{value}</div>
    </div>
);

/* ── Main ── */
const OptionArrayView = () => {
    const [data, setData]    = useState(null);
    const [err,  setErr]     = useState(null);
    const [last, setLast]    = useState(null);

    const fetchData = useCallback(async () => {
        try {
            const res = await fetch('/api/option-array/today');
            const json = await res.json();
            setData(json);
            setErr(null);
            setLast(new Date());
        } catch (e) {
            setErr(e.message);
        }
    }, []);

    useEffect(() => {
        fetchData();
        const id = setInterval(fetchData, 60000); // refresh every 60s — matches cron cadence
        return () => clearInterval(id);
    }, [fetchData]);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {data?.date ? `Date: ${data.date}` : 'Loading…'} · per-minute LTP for every strike the model suggested today
                </div>
                {last && (
                    <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>
                        Updated {last.toLocaleTimeString()} · refresh 60s
                    </div>
                )}
            </div>

            {err && (
                <div style={{ padding: '0.75rem 1rem', borderRadius: 8, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)', fontSize: '0.8rem', color: '#ef4444' }}>
                    {err}
                </div>
            )}

            {!data?.strikes?.length && !err && (
                <div className="cpanel">
                    <div className="cpanel-body" style={{ color: 'var(--text-muted)', fontSize: '0.85rem', padding: '1rem', textAlign: 'center' }}>
                        No strikes suggested yet today. Cards will appear here as the model produces signals.
                    </div>
                </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '0.7rem' }}>
                {data?.strikes?.map((blk, i) => (
                    <StrikeCard key={`${blk.strike}-${blk.option_type}-${i}`} block={blk} />
                ))}
            </div>
        </div>
    );
};

export default OptionArrayView;
