import React, { useState, useEffect, useCallback } from 'react';

const MODULE_META = {
    smart_money: { icon: '💰', label: 'Smart Money Flow', desc: 'CMF + OBV divergence detection' },
    gamma_exposure: { icon: '⚡', label: 'Gamma Exposure', desc: 'Options dealer hedging pressure' },
    intermarket: { icon: '🌍', label: 'Intermarket Signals', desc: 'VIX, DXY, Gold, Oil, S&P' },
    breadth: { icon: '📊', label: 'Market Breadth', desc: 'Advance/Decline, thrust analysis' },
    sector_rotation: { icon: '🔄', label: 'Sector Rotation', desc: 'Cyclical vs Defensive' },
    volatility_regime: { icon: '🌊', label: 'Volatility Regime', desc: 'VIX zones, ATR, vol divergence' },
    momentum: { icon: '🚀', label: 'Momentum Composite', desc: 'Multi-RSI, MACD, EMA stack' },
    flow_proxy: { icon: '🏛️', label: 'Institutional Flows', desc: 'FII/DII proxy via LC vs MC' },
    risk_assessment: { icon: '🛡️', label: 'Risk Assessment', desc: 'R:R ratio, key levels, range' },
};

const InstitutionalView = () => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    const fetchData = useCallback(async () => {
        try {
            const res = await fetch('/api/institutional-outlook');
            const json = await res.json();
            setData(json);
        } catch (e) {
            setData(null);
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        fetchData();
        const id = setInterval(fetchData, 45000);
        return () => clearInterval(id);
    }, [fetchData]);

    if (loading) return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>Analyzing institutional signals...</div>;
    if (!data) return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--status-sell)' }}>Failed to load institutional data</div>;

    const comp = data.composite || {};
    const modules = data.modules || {};
    const score = comp.score || 0;
    const scoreColor = score > 20 ? '#10b981' : score < -20 ? '#ef4444' : '#f59e0b';

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>

            {/* ═══ COMPOSITE VERDICT ═══ */}
            <div className="glass" style={{
                borderRadius: 'var(--radius-lg)', padding: '1.5rem 2rem',
                borderLeft: `5px solid ${scoreColor}`,
                display: 'flex', alignItems: 'center', gap: '2rem', flexWrap: 'wrap',
            }}>
                <div style={{ textAlign: 'center', minWidth: 120 }}>
                    <ScoreGauge value={score} size={110} />
                </div>
                <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                        Institutional Verdict
                    </div>
                    <div style={{ fontSize: '1.8rem', fontWeight: 800, color: scoreColor, fontFamily: 'var(--font-display)' }}>
                        {comp.verdict || 'N/A'}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                        Confidence: <span style={{ fontWeight: 700, color: comp.confidence === 'HIGH' ? '#10b981' : comp.confidence === 'MODERATE' ? '#f59e0b' : '#ef4444' }}>{comp.confidence}</span>
                        &nbsp;•&nbsp; Agreement: {((comp.agreement_ratio || 0) * 100).toFixed(0)}%
                    </div>
                </div>

                {/* Intermarket Strip */}
                {modules.intermarket?.markets && (
                    <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                        {Object.entries(modules.intermarket.markets).map(([name, m]) => (
                            <IntermarketChip key={name} name={name} price={m.price} change={m.change_pct} />
                        ))}
                    </div>
                )}
            </div>

            {/* ═══ MODULE GRID ═══ */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1rem' }}>
                {Object.entries(MODULE_META).map(([key, meta]) => {
                    const mod = modules[key] || {};
                    return <ModuleCard key={key} moduleKey={key} meta={meta} data={mod} />;
                })}
            </div>
        </div>
    );
};


/* ─── Score Gauge (SVG) ─── */
const ScoreGauge = ({ value, size = 100 }) => {
    const r = (size - 10) / 2;
    const circ = Math.PI * r; // Half circle
    const pct = (value + 100) / 200; // Normalize -100..100 to 0..1
    const offset = circ * (1 - pct);
    const color = value > 20 ? '#10b981' : value < -20 ? '#ef4444' : '#f59e0b';

    return (
        <svg width={size} height={size * 0.65} viewBox={`0 0 ${size} ${size * 0.65}`}>
            <path d={`M 5 ${size * 0.6} A ${r} ${r} 0 0 1 ${size - 5} ${size * 0.6}`}
                fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="6" strokeLinecap="round" />
            <path d={`M 5 ${size * 0.6} A ${r} ${r} 0 0 1 ${size - 5} ${size * 0.6}`}
                fill="none" stroke={color} strokeWidth="6" strokeLinecap="round"
                strokeDasharray={circ} strokeDashoffset={offset}
                style={{ transition: 'stroke-dashoffset 0.8s ease' }} />
            <text x={size / 2} y={size * 0.48} textAnchor="middle" fill={color} fontSize="22" fontWeight="800">
                {value > 0 ? '+' : ''}{value.toFixed(0)}
            </text>
            <text x={size / 2} y={size * 0.63} textAnchor="middle" fill="var(--text-muted)" fontSize="7">
                -100 ────── +100
            </text>
        </svg>
    );
};


/* ─── Intermarket Chip ─── */
const IntermarketChip = ({ name, price, change }) => {
    const isUp = change > 0;
    const color = isUp ? '#10b981' : change < 0 ? '#ef4444' : '#94a3b8';
    const short = name.replace('S&P 500 Futures', 'S&P').replace('Dollar Index', 'DXY').replace('Crude Oil', 'Oil').replace('India VIX', 'VIX');

    return (
        <div style={{
            padding: '0.3rem 0.6rem', borderRadius: 'var(--radius-sm)',
            background: `${color}10`, border: `1px solid ${color}25`,
            fontSize: '0.72rem', textAlign: 'center', minWidth: 70,
        }}>
            <div style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>{short}</div>
            <div style={{ fontWeight: 700, color, fontSize: '0.8rem' }}>
                {isUp ? '+' : ''}{change?.toFixed(2)}%
            </div>
        </div>
    );
};


/* ─── Module Card ─── */
const ModuleCard = ({ moduleKey, meta, data }) => {
    const score = data.score || 0;
    const barPct = ((score + 100) / 200) * 100;
    const barColor = score > 15 ? '#10b981' : score < -15 ? '#ef4444' : '#f59e0b';

    return (
        <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '1rem 1.25rem' }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem' }}>
                <div>
                    <span style={{ fontSize: '1.1rem', marginRight: '0.4rem' }}>{meta.icon}</span>
                    <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>{meta.label}</span>
                </div>
                <span style={{
                    fontSize: '0.9rem', fontWeight: 800, color: barColor,
                    background: `${barColor}15`, padding: '0.15rem 0.6rem', borderRadius: 'var(--radius-sm)',
                }}>
                    {score > 0 ? '+' : ''}{score.toFixed(0)}
                </span>
            </div>

            {/* Score Bar */}
            <div style={{ position: 'relative', height: 8, background: 'rgba(255,255,255,0.06)', borderRadius: 4, marginBottom: '0.5rem' }}>
                <div style={{
                    position: 'absolute', left: 0, top: 0, height: '100%',
                    width: `${barPct}%`, background: `linear-gradient(90deg, #ef4444, #f59e0b 50%, #10b981)`,
                    borderRadius: 4, transition: 'width 0.5s ease', opacity: 0.3,
                }} />
                <div style={{
                    position: 'absolute', top: -3, left: `${barPct}%`, transform: 'translateX(-50%)',
                    width: 14, height: 14, borderRadius: '50%', background: barColor,
                    border: '2px solid var(--bg-primary)', transition: 'left 0.5s ease',
                }} />
            </div>

            {/* Bias */}
            <div style={{ fontSize: '0.78rem', fontWeight: 600, color: barColor, marginBottom: '0.4rem' }}>
                {data.bias || 'N/A'}
            </div>

            {/* Module-specific details */}
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                {moduleKey === 'smart_money' && (
                    <>
                        <Detail label="CMF (20)" value={data.cmf?.toFixed(4)} />
                        <Detail label="OBV Trend" value={data.obv_trend} />
                        <Detail label="Divergence" value={data.divergence} highlight={data.divergence !== 'None'} />
                    </>
                )}
                {moduleKey === 'gamma_exposure' && (
                    <>
                        <Detail label="GEX Direction" value={data.gex_direction} />
                        <Detail label="PCR" value={data.pcr?.toFixed(2)} />
                        <Detail label="Max Pain" value={data.max_pain} />
                    </>
                )}
                {moduleKey === 'intermarket' && (
                    <>
                        <Detail label="VIX" value={`${data.vix?.toFixed(1)} (${data.vix_status})`} highlight={data.vix_status === 'High Fear'} />
                        <Detail label="VIX Change" value={`${data.vix_change > 0 ? '+' : ''}${data.vix_change?.toFixed(2)}%`} />
                    </>
                )}
                {moduleKey === 'breadth' && (
                    <>
                        <Detail label="Advancing" value={`${data.advancing} / ${(data.advancing || 0) + (data.declining || 0)}`} />
                        <Detail label="Breadth %" value={`${data.breadth_pct?.toFixed(1)}%`} />
                        <Detail label="A/D Ratio" value={data.ad_ratio?.toFixed(2)} />
                        <Detail label="Strong Up / Down" value={`${data.strong_up} / ${data.strong_down}`} />
                    </>
                )}
                {moduleKey === 'sector_rotation' && (
                    <>
                        <Detail label="Regime" value={data.regime} highlight />
                        <Detail label="Cyclical Avg" value={`${data.cyclical_avg > 0 ? '+' : ''}${data.cyclical_avg?.toFixed(2)}%`} />
                        <Detail label="Defensive Avg" value={`${data.defensive_avg > 0 ? '+' : ''}${data.defensive_avg?.toFixed(2)}%`} />
                        {(data.sectors || []).slice(0, 4).map((s, i) => (
                            <Detail key={i} label={s.name} value={`${s.change > 0 ? '+' : ''}${s.change?.toFixed(2)}%`} />
                        ))}
                    </>
                )}
                {moduleKey === 'volatility_regime' && (
                    <>
                        <Detail label="VIX Level" value={data.vix_level?.toFixed(1)} />
                        <Detail label="VIX Zone" value={data.vix_zone} highlight={data.vix_zone?.includes('Fear')} />
                        <Detail label="Vol Trend" value={`${data.vol_trend} (${data.vol_ratio?.toFixed(2)}x)`} />
                        <Detail label="Realized Vol" value={`${data.realized_vol?.toFixed(2)}%`} />
                        <Detail label="VIX-Nifty Div." value={data.nifty_vix_divergence} highlight={data.nifty_vix_divergence !== 'None'} />
                    </>
                )}
                {moduleKey === 'momentum' && (
                    <>
                        <Detail label="RSI 7 / 14 / 21" value={`${data.rsi_7?.toFixed(0)} / ${data.rsi_14?.toFixed(0)} / ${data.rsi_21?.toFixed(0)}`} />
                        <Detail label="RSI Alignment" value={data.rsi_alignment} highlight />
                        <Detail label="MACD Alignment" value={data.macd_alignment} />
                        <Detail label="EMA Stack" value={data.ema_score} />
                        <Detail label="Price Structure" value={data.structure} highlight={data.structure?.includes('Uptrend') || data.structure?.includes('Downtrend')} />
                    </>
                )}
                {moduleKey === 'flow_proxy' && (
                    <>
                        <Detail label="Flow Type" value={data.flow_type} highlight />
                        <Detail label="Large-cap Avg" value={`${data.large_cap_avg > 0 ? '+' : ''}${data.large_cap_avg?.toFixed(2)}%`} />
                        <Detail label="Mid-cap Avg" value={`${data.mid_cap_avg > 0 ? '+' : ''}${data.mid_cap_avg?.toFixed(2)}%`} />
                        <Detail label="LC vs MC" value={`${data.lc_vs_mc > 0 ? '+' : ''}${data.lc_vs_mc?.toFixed(2)}%`} />
                    </>
                )}
                {moduleKey === 'risk_assessment' && (
                    <>
                        <Detail label="Nifty LTP" value={data.nifty_ltp?.toFixed(0)} />
                        <Detail label="Dist 20 EMA" value={`${data.dist_from_20ema > 0 ? '+' : ''}${data.dist_from_20ema?.toFixed(2)}%`} />
                        <Detail label="Dist 50 EMA" value={`${data.dist_from_50ema > 0 ? '+' : ''}${data.dist_from_50ema?.toFixed(2)}%`} />
                        <Detail label="Expected Range" value={data.expected_range} highlight />
                        <Detail label="R:R Ratio" value={data.rr_ratio?.toFixed(2)} />
                        <Detail label="OI Support" value={data.oi_support} />
                        <Detail label="OI Resistance" value={data.oi_resistance} />
                    </>
                )}
            </div>
        </div>
    );
};

const Detail = ({ label, value, highlight }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span>{label}</span>
        <span style={{ fontWeight: 600, color: highlight ? '#f59e0b' : 'var(--text-secondary)' }}>{value || '—'}</span>
    </div>
);


export default InstitutionalView;
