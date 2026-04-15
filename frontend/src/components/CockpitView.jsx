import React, { useState, useEffect, useCallback } from 'react';

/* ─── Color / format helpers ─── */
const dirColor  = v => v >= 15 ? '#10b981' : v >= 5 ? '#34d399' : v <= -15 ? '#ef4444' : v <= -5 ? '#f87171' : '#94a3b8';
const sigColor  = s => s?.includes('BUY CE') ? '#10b981' : s?.includes('BUY PE') ? '#ef4444' : '#64748b';
const fmtNum    = (v, d = 2) => v != null ? Number(v).toFixed(d) : '—';
const fmtPct    = v => v != null ? `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}%` : '—';
const scoreCol  = s => s > 20 ? '#10b981' : s < -20 ? '#ef4444' : '#f59e0b';

/* Abbreviated signal label + CSS class */
function abbrevSig(val) {
    if (!val || val === '-' || val === 'Neutral') return { label: '·', cls: 'sig-neutral' };
    const s = val.toString();
    if (s.includes('Buy+++')) return { label: 'B3', cls: 'sig-buy-3' };
    if (s.includes('Buy++'))  return { label: 'B2', cls: 'sig-buy-2' };
    if (s.includes('Buy+'))   return { label: 'B+', cls: 'sig-buy-1' };
    if (s.includes('Buy'))    return { label: 'B',  cls: 'sig-buy' };
    if (s.includes('Sell+++')) return { label: 'S3', cls: 'sig-sell-3' };
    if (s.includes('Sell++'))  return { label: 'S--', cls: 'sig-sell-2' };
    if (s.includes('Sell+'))   return { label: 'S-', cls: 'sig-sell-1' };
    if (s.includes('Sell'))    return { label: 'S',  cls: 'sig-sell' };
    return { label: '·', cls: 'sig-neutral' };
}

/* Module meta for Institutional column */
const MOD_META = {
    smart_money:       { icon: '💰', label: 'Smart Money' },
    gamma_exposure:    { icon: 'γ',  label: 'Gamma Exposure' },
    breadth:           { icon: '📡', label: 'Market Breadth' },
    volatility_regime: { icon: '⚡', label: 'Volatility' },
    momentum:          { icon: '↗',  label: 'Momentum' },
    risk_assessment:   { icon: '🛡', label: 'Risk' },
};

/* ─────────────────────────────────────────── */
/*  MAIN COMPONENT                              */
/* ─────────────────────────────────────────── */
const CockpitView = () => {
    const [signals,       setSignals]       = useState(null);
    const [direction,     setDirection]     = useState(null);
    const [institutional, setInstitutional] = useState(null);
    const [lastUpdate,    setLastUpdate]    = useState(null);

    const fetchAll = useCallback(async () => {
        const [s, d, i] = await Promise.all([
            fetch('/api/trade-signals').then(r => r.json()).catch(() => null),
            fetch('/api/market-direction').then(r => r.json()).catch(() => null),
            fetch('/api/institutional-outlook').then(r => r.json()).catch(() => null),
        ]);
        setSignals(s);
        setDirection(d);
        setInstitutional(i);
        setLastUpdate(new Date());
    }, []);

    useEffect(() => {
        fetchAll();
        const id = setInterval(fetchAll, 30000);
        return () => clearInterval(id);
    }, [fetchAll]);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {/* Refresh label */}
            {lastUpdate && (
                <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textAlign: 'right' }}>
                    Updated {lastUpdate.toLocaleTimeString()} · auto-refresh 30s
                </div>
            )}

            <div className="cockpit-grid">
                <LeftColumn  data={signals} />
                <CenterColumn data={direction} />
                <RightColumn data={institutional} />
            </div>
        </div>
    );
};

/* ═══════════════════════════════════════════ */
/*  LEFT — Trade Signal                         */
/* ═══════════════════════════════════════════ */
const LeftColumn = ({ data }) => {
    if (!data) return (
        <div className="cpanel">
            <div className="cpanel-header">Trade Signal</div>
            <div className="cpanel-body" style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Loading…</div>
        </div>
    );

    const signal   = data.signal || 'NO TRADE';
    const noTrade  = signal === 'NO TRADE';
    const color    = sigColor(signal);
    const oi       = data.oi_analysis || {};

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>

            {/* Main signal panel */}
            <div className="cpanel" style={{ borderTop: `3px solid ${color}` }}>
                <div className="cpanel-header">Trade Signal (ML)</div>
                <div className="cpanel-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>

                    {/* Big signal text */}
                    <div style={{ textAlign: 'center' }}>
                        <div style={{
                            fontSize: '1.9rem', fontWeight: 800, color,
                            fontFamily: 'var(--font-display)', lineHeight: 1.1,
                            letterSpacing: '-0.02em',
                        }}>
                            {signal}
                        </div>
                        {!noTrade && (
                            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: '0.2rem' }}>
                                NIFTY {data.strike} {data.option_type}
                            </div>
                        )}
                        <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '0.15rem' }}>
                            Valid until {data.valid_until || '—'}
                        </div>
                    </div>

                    {/* Confidence big number */}
                    <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: '2.4rem', fontWeight: 800, color, fontFamily: 'var(--font-display)', lineHeight: 1 }}>
                            {data.confidence != null ? `${Number(data.confidence).toFixed(0)}%` : '—'}
                        </div>
                        <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                            Confidence
                        </div>
                    </div>

                    {/* Level boxes */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.4rem' }}>
                        <LevelBox label="Spot"   value={fmtNum(data.nifty_spot, 0)} color="var(--text-primary)" />
                        <LevelBox label="Target" value={fmtNum(data.target_nifty, 0)} color="#10b981" />
                        <LevelBox label="SL"     value={fmtNum(data.sl_nifty, 0)} color="#ef4444" />
                    </div>

                    {/* Confirmation badges */}
                    <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                        <ConfirmBadge label="OI"     confirmed={data.oi_confirms} />
                        <ConfirmBadge label="Equity" confirmed={data.equity_confirms} />
                    </div>

                    {/* Probability mini-bars */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                        <MiniBarRow label="UP"   pct={data.prob_up}       color="#10b981" />
                        <MiniBarRow label="SIDE" pct={data.prob_sideways} color="#94a3b8" />
                        <MiniBarRow label="DOWN" pct={data.prob_down}     color="#ef4444" />
                    </div>

                    {/* Model accuracy footer */}
                    <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', textAlign: 'center', paddingTop: '0.3rem', borderTop: '1px solid var(--border-color)' }}>
                        Model accuracy: {data.model_accuracy != null ? `${Number(data.model_accuracy).toFixed(1)}%` : '—'}
                    </div>
                </div>
            </div>

            {/* OI Analysis card */}
            <div className="cpanel">
                <div className="cpanel-header">OI Analysis</div>
                <div className="cpanel-body" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.45rem 0.75rem' }}>
                    <MiniMetric label="PCR"         value={fmtNum(oi.pcr || data.pcr, 2)} />
                    <MiniMetric label="PCR Bias"    value={oi.pcr_bias || '—'} color={oi.pcr_bias === 'Bullish' ? '#10b981' : oi.pcr_bias === 'Bearish' ? '#ef4444' : undefined} />
                    <MiniMetric label="CE ΔOI"      value={oi.ce_oi_change != null ? Number(oi.ce_oi_change).toLocaleString() : '—'} color="#fca5a5" />
                    <MiniMetric label="PE ΔOI"      value={oi.pe_oi_change != null ? Number(oi.pe_oi_change).toLocaleString() : '—'} color="#6ee7b7" />
                    <MiniMetric label="Support"     value={oi.support  || data.support  || '—'} color="#10b981" />
                    <MiniMetric label="Resistance"  value={oi.resistance || data.resistance || '—'} color="#ef4444" />
                </div>
            </div>
        </div>
    );
};

/* ═══════════════════════════════════════════ */
/*  CENTER — Market Direction + TF Table        */
/* ═══════════════════════════════════════════ */
const CenterColumn = ({ data }) => {
    if (!data) return (
        <div className="cpanel">
            <div className="cpanel-header">Market Direction</div>
            <div className="cpanel-body" style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Loading…</div>
        </div>
    );

    const score  = data.score || 0;
    const dc     = dirColor(score);
    const tfs    = data.timeframes || {};
    const TF_KEYS = ['1m', '3m', '5m', '15m'];
    const SIG_COLS = ['VWAP', 'EMA_Cross', 'Alligator', 'ST_21_1', 'ST_14_2', 'ADX', 'RSI', 'MACD'];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>

            {/* Direction verdict card */}
            <div className="cpanel" style={{ borderTop: `3px solid ${dc}` }}>
                <div className="cpanel-header">Market Direction</div>
                <div className="cpanel-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', alignItems: 'center' }}>

                    {/* Score + direction */}
                    <div style={{ textAlign: 'center' }}>
                        <div style={{
                            fontSize: '2.8rem', fontWeight: 800, color: dc,
                            fontFamily: 'var(--font-display)', lineHeight: 1,
                        }}>
                            {score > 0 ? '+' : ''}{score}
                        </div>
                        <div style={{ fontSize: '1rem', fontWeight: 700, color: dc, marginTop: '0.15rem' }}>
                            {data.direction || '—'}
                        </div>
                        <div style={{
                            display: 'inline-block', marginTop: '0.35rem',
                            padding: '0.25rem 0.75rem', borderRadius: '20px',
                            fontSize: '0.72rem', fontWeight: 600,
                            background: `${dc}18`, border: `1px solid ${dc}30`, color: dc,
                        }}>
                            {data.suggested_action || '—'}
                        </div>
                    </div>

                    {/* ScoreArc SVG */}
                    <ScoreArc score={score} color={dc} />

                    {/* Stats row */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.4rem', width: '100%' }}>
                        <MiniMetric label="Nifty LTP"  value={fmtNum(data.nifty_ltp, 0)} />
                        <MiniMetric label="Confidence" value={data.confidence != null ? `${data.confidence}%` : '—'} color={dc} />
                        <MiniMetric label="Ind. Score"  value={data.indicator_score != null ? (data.indicator_score > 0 ? `+${data.indicator_score}` : `${data.indicator_score}`) : '—'}
                            color={data.indicator_score > 0 ? '#10b981' : '#ef4444'} />
                        <MiniMetric label="OI Bias"
                            value={data.oi_bias > 0 ? `+${data.oi_bias}` : `${data.oi_bias ?? '—'}`}
                            color={data.oi_bias > 0 ? '#10b981' : data.oi_bias < 0 ? '#ef4444' : '#94a3b8'} />
                    </div>
                </div>
            </div>

            {/* Multi-TF Confluence table */}
            <div className="cpanel">
                <div className="cpanel-header">Multi-TF Confluence — NIFTY</div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.7rem', textAlign: 'center' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                                <th style={{ padding: '0.35rem 0.5rem', color: 'var(--text-muted)', fontWeight: 700, textAlign: 'left', whiteSpace: 'nowrap' }}>TF</th>
                                <th style={{ padding: '0.35rem 0.4rem', color: 'var(--text-muted)', fontWeight: 700, whiteSpace: 'nowrap' }}>Score</th>
                                {SIG_COLS.map(c => (
                                    <th key={c} style={{ padding: '0.35rem 0.3rem', color: 'var(--text-muted)', fontWeight: 700, whiteSpace: 'nowrap' }}>
                                        {c.replace('EMA_Cross', 'EMAC').replace('Alligator', 'Allig').replace('ST_21_1', 'ST21').replace('ST_14_2', 'ST14')}
                                    </th>
                                ))}
                                <th style={{ padding: '0.35rem 0.3rem', color: 'var(--text-muted)', fontWeight: 700, whiteSpace: 'nowrap' }}>Mom%</th>
                            </tr>
                        </thead>
                        <tbody>
                            {TF_KEYS.map(tf => {
                                const d = tfs[tf];
                                if (!d) return (
                                    <tr key={tf} style={{ borderBottom: '1px solid rgba(42,49,67,0.4)' }}>
                                        <td style={{ padding: '0.3rem 0.5rem', textAlign: 'left', fontWeight: 700, color: 'var(--text-secondary)' }}>{tf}</td>
                                        <td colSpan={SIG_COLS.length + 2} style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}>no data</td>
                                    </tr>
                                );
                                const norm = d.normalized ?? 0;
                                const normCls = norm > 3 ? 'sig-buy-2' : norm > 0 ? 'sig-buy' : norm < -3 ? 'sig-sell-2' : norm < 0 ? 'sig-sell' : 'sig-neutral';
                                return (
                                    <tr key={tf} style={{ borderBottom: '1px solid rgba(42,49,67,0.4)' }}>
                                        <td style={{ padding: '0.3rem 0.5rem', textAlign: 'left', fontWeight: 700, color: 'var(--text-secondary)' }}>{tf}</td>
                                        <td style={{ padding: '0.3rem 0.4rem' }}>
                                            <span className={`signal-badge ${normCls}`} style={{ fontSize: '0.65rem', padding: '0.12rem 0.3rem', minWidth: 28 }}>
                                                {norm > 0 ? '+' : ''}{norm}
                                            </span>
                                        </td>
                                        {SIG_COLS.map(col => {
                                            const { label, cls } = abbrevSig(d.signals?.[col]);
                                            return (
                                                <td key={col} style={{ padding: '0.3rem 0.3rem' }}>
                                                    <span className={`signal-badge ${cls}`} style={{ fontSize: '0.65rem', padding: '0.1rem 0.28rem', minWidth: 22 }}>
                                                        {label}
                                                    </span>
                                                </td>
                                            );
                                        })}
                                        <td style={{
                                            padding: '0.3rem 0.3rem', fontWeight: 600, fontSize: '0.68rem',
                                            color: d.momentum > 0 ? '#10b981' : d.momentum < 0 ? '#ef4444' : '#94a3b8',
                                        }}>
                                            {d.momentum != null ? `${d.momentum > 0 ? '+' : ''}${d.momentum}%` : '—'}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

/* ═══════════════════════════════════════════ */
/*  RIGHT — Institutional Outlook               */
/* ═══════════════════════════════════════════ */
const RightColumn = ({ data }) => {
    if (!data) return (
        <div className="cpanel">
            <div className="cpanel-header">Institutional</div>
            <div className="cpanel-body" style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Loading…</div>
        </div>
    );

    const comp    = data.composite || {};
    const modules = data.modules   || {};
    const score   = comp.score     || 0;
    const sc      = scoreCol(score);
    const sliderPct = ((score + 100) / 200) * 100;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>

            {/* Composite verdict */}
            <div className="cpanel" style={{ borderTop: `3px solid ${sc}` }}>
                <div className="cpanel-header">Institutional Outlook</div>
                <div className="cpanel-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>

                    {/* Score + verdict */}
                    <div style={{ textAlign: 'center' }}>
                        <div style={{
                            fontSize: '2.4rem', fontWeight: 800, color: sc,
                            fontFamily: 'var(--font-display)', lineHeight: 1,
                        }}>
                            {score > 0 ? '+' : ''}{Number(score).toFixed(0)}
                        </div>
                        <div style={{ fontSize: '0.85rem', fontWeight: 700, color: sc, marginTop: '0.15rem' }}>
                            {comp.verdict || '—'}
                        </div>
                    </div>

                    {/* Score slider */}
                    <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.55rem', color: 'var(--text-muted)', marginBottom: '3px' }}>
                            <span>−100</span><span>0</span><span>+100</span>
                        </div>
                        <div className="score-slider">
                            <div style={{
                                position: 'absolute', top: '50%', left: `${sliderPct}%`,
                                transform: 'translate(-50%, -50%)',
                                width: 12, height: 12, borderRadius: '50%',
                                background: sc, border: '2px solid var(--bg-surface)',
                                boxShadow: `0 0 8px ${sc}`,
                                transition: 'left 0.5s ease',
                            }} />
                        </div>
                    </div>

                    {/* Confidence badge */}
                    <div style={{ textAlign: 'center' }}>
                        <span style={{
                            display: 'inline-block', padding: '0.2rem 0.65rem',
                            borderRadius: '20px', fontSize: '0.7rem', fontWeight: 700,
                            background: comp.confidence === 'HIGH' ? 'rgba(16,185,129,0.15)' : comp.confidence === 'MODERATE' ? 'rgba(245,158,11,0.15)' : 'rgba(239,68,68,0.15)',
                            color: comp.confidence === 'HIGH' ? '#10b981' : comp.confidence === 'MODERATE' ? '#f59e0b' : '#ef4444',
                            border: `1px solid ${comp.confidence === 'HIGH' ? '#10b98130' : comp.confidence === 'MODERATE' ? '#f59e0b30' : '#ef444430'}`,
                        }}>
                            {comp.confidence || 'N/A'} CONFIDENCE
                        </span>
                    </div>

                    {/* Module rows */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                        {Object.entries(MOD_META).map(([key, meta]) => {
                            const mod = modules[key] || {};
                            const ms  = mod.score || 0;
                            const mc  = scoreCol(ms);
                            const bPct = ((ms + 100) / 200) * 100;
                            return (
                                <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                    <span style={{ fontSize: '0.8rem', minWidth: 18, textAlign: 'center' }}>{meta.icon}</span>
                                    <span style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', flex: 1, minWidth: 70, fontWeight: 600 }}>
                                        {meta.label}
                                    </span>
                                    <div style={{ width: 60, position: 'relative' }}>
                                        <div className="mini-bar-track">
                                            <div className="mini-bar-fill" style={{
                                                width: `${bPct}%`,
                                                background: `linear-gradient(90deg, #ef4444, #f59e0b 50%, #10b981)`,
                                                opacity: 0.7,
                                            }} />
                                        </div>
                                    </div>
                                    <span style={{ fontSize: '0.68rem', fontWeight: 700, color: mc, minWidth: 28, textAlign: 'right' }}>
                                        {ms > 0 ? '+' : ''}{Number(ms).toFixed(0)}
                                    </span>
                                    <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', minWidth: 50 }}>
                                        {mod.bias || '—'}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>

            {/* Intermarket chips */}
            {modules.intermarket?.markets && (
                <div className="cpanel">
                    <div className="cpanel-header">Intermarket</div>
                    <div className="cpanel-body" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                        {Object.entries(modules.intermarket.markets).map(([name, m]) => {
                            const c = m.change_pct > 0 ? '#10b981' : m.change_pct < 0 ? '#ef4444' : '#94a3b8';
                            const short = name
                                .replace('S&P 500 Futures', 'S&P')
                                .replace('Dollar Index', 'DXY')
                                .replace('Crude Oil', 'Oil')
                                .replace('India VIX', 'VIX');
                            return (
                                <div key={name} style={{
                                    padding: '0.28rem 0.55rem', borderRadius: '6px',
                                    background: `${c}12`, border: `1px solid ${c}28`,
                                    fontSize: '0.68rem', textAlign: 'center', minWidth: 52,
                                }}>
                                    <div style={{ fontWeight: 700, color: 'var(--text-secondary)', fontSize: '0.62rem' }}>{short}</div>
                                    <div style={{ fontWeight: 800, color: c }}>
                                        {m.change_pct > 0 ? '+' : ''}{Number(m.change_pct).toFixed(2)}%
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};

/* ─────────────────────────────────────────── */
/*  Shared sub-components                       */
/* ─────────────────────────────────────────── */

const LevelBox = ({ label, value, color }) => (
    <div style={{
        background: 'rgba(255,255,255,0.03)', borderRadius: '6px',
        padding: '0.35rem 0.4rem', textAlign: 'center',
        border: '1px solid var(--border-color)',
    }}>
        <div style={{ fontSize: '0.58rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
        <div style={{ fontSize: '0.88rem', fontWeight: 700, color: color || 'var(--text-primary)', marginTop: '0.1rem' }}>{value}</div>
    </div>
);

const ConfirmBadge = ({ label, confirmed }) => (
    <div style={{
        display: 'flex', alignItems: 'center', gap: '0.3rem',
        padding: '0.2rem 0.5rem', borderRadius: '6px', fontSize: '0.7rem', fontWeight: 600,
        background: confirmed ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.08)',
        border: `1px solid ${confirmed ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.15)'}`,
        color: confirmed ? '#10b981' : '#ef4444',
    }}>
        <span>{confirmed ? '✓' : '✗'}</span>
        <span>{label}</span>
    </div>
);

const MiniBarRow = ({ label, pct, color }) => {
    const safePct = pct != null ? Math.min(Math.max(Number(pct), 0), 100) : 0;
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', minWidth: 28 }}>{label}</span>
            <div className="mini-bar-track" style={{ flex: 1 }}>
                <div className="mini-bar-fill" style={{ width: `${safePct}%`, background: color }} />
            </div>
            <span style={{ fontSize: '0.65rem', fontWeight: 700, color, minWidth: 32, textAlign: 'right' }}>
                {pct != null ? `${Number(pct).toFixed(1)}%` : '—'}
            </span>
        </div>
    );
};

const MiniMetric = ({ label, value, color }) => (
    <div>
        <div style={{ fontSize: '0.58rem', color: 'var(--text-muted)', letterSpacing: '0.03em', textTransform: 'uppercase' }}>{label}</div>
        <div style={{ fontSize: '0.8rem', fontWeight: 700, color: color || 'var(--text-primary)', marginTop: '0.1rem' }}>{value ?? '—'}</div>
    </div>
);

/* Half-circle arc indicator — viewBox 0 0 120 65 */
const ScoreArc = ({ score, color }) => {
    const cx = 60, cy = 58, r = 50;
    // Arc from left (180°) to right (0°) — half circle
    const startX = cx - r, startY = cy;
    const endX   = cx + r, endY   = cy;
    const arcLen = Math.PI * r;
    // Map score -100..+100 → 0..1 along arc (left=−100, right=+100)
    const pct    = (score + 100) / 200;
    const clPct  = Math.min(Math.max(pct, 0), 1);
    const dashOffset = arcLen * (1 - clPct);
    // Dot position on arc
    const angle  = Math.PI * (1 - clPct); // 0=right, π=left
    const dotX   = cx - r * Math.cos(Math.PI - angle);
    const dotY   = cy - r * Math.sin(Math.PI - angle);

    return (
        <svg width="120" height="65" viewBox="0 0 120 65" style={{ overflow: 'visible' }}>
            {/* Track arc */}
            <path
                d={`M ${startX} ${startY} A ${r} ${r} 0 0 1 ${endX} ${endY}`}
                fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="5" strokeLinecap="round"
            />
            {/* Filled arc */}
            <path
                d={`M ${startX} ${startY} A ${r} ${r} 0 0 1 ${endX} ${endY}`}
                fill="none" stroke={color} strokeWidth="5" strokeLinecap="round"
                strokeDasharray={arcLen} strokeDashoffset={dashOffset}
                style={{ transition: 'stroke-dashoffset 0.6s ease' }}
            />
            {/* Dot indicator */}
            <circle cx={dotX} cy={dotY} r={5} fill={color} stroke="var(--bg-surface)" strokeWidth="2"
                style={{ filter: `drop-shadow(0 0 4px ${color})`, transition: 'cx 0.6s ease, cy 0.6s ease' }} />
            {/* Axis labels */}
            <text x={startX - 2} y={startY + 12} fill="var(--text-muted)" fontSize="7" textAnchor="middle">−100</text>
            <text x={cx}         y={startY + 12} fill="var(--text-muted)" fontSize="7" textAnchor="middle">0</text>
            <text x={endX + 2}   y={startY + 12} fill="var(--text-muted)" fontSize="7" textAnchor="middle">+100</text>
        </svg>
    );
};

export default CockpitView;
