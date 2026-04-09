import React, { useState, useEffect, useCallback } from 'react';

const MarketDirectionView = () => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchDirection = useCallback(async () => {
        try {
            const res = await fetch('/api/market-direction');
            const json = await res.json();
            setData(json);
            setError(null);
        } catch (e) {
            setError('Failed to fetch market direction');
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        fetchDirection();
        const id = setInterval(fetchDirection, 30000); // Refresh every 30s
        return () => clearInterval(id);
    }, [fetchDirection]);

    if (loading && !data) {
        return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>Analyzing market direction across timeframes...</div>;
    }

    if (error && !data) {
        return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--status-sell)' }}>{error}</div>;
    }

    if (!data) return null;

    const score = data.score || 0;
    const isPositive = score > 0;
    const dirColor = score > 15 ? '#10b981' : score > 5 ? '#34d399' : score < -15 ? '#ef4444' : score < -5 ? '#f87171' : '#94a3b8';
    const tfs = data.timeframes || {};
    const oi = data.oi_analysis || {};

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>

            {/* ═══ MAIN VERDICT CARD ═══ */}
            <div className="glass" style={{
                borderRadius: 'var(--radius-lg)', padding: '1.5rem 2rem',
                display: 'flex', alignItems: 'center', gap: '2rem', flexWrap: 'wrap',
                borderLeft: `4px solid ${dirColor}`,
            }}>
                {/* Score Gauge */}
                <div style={{ textAlign: 'center', minWidth: '140px' }}>
                    <div style={{
                        fontSize: '3rem', fontWeight: 800, color: dirColor,
                        fontFamily: 'var(--font-display)', lineHeight: 1,
                    }}>
                        {score > 0 ? '+' : ''}{score}
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                        CONFLUENCE SCORE
                    </div>
                    <ScoreBar score={score} />
                </div>

                {/* Direction + Action */}
                <div style={{ flex: 1, minWidth: '200px' }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: dirColor, marginBottom: '0.25rem' }}>
                        {data.direction}
                    </div>
                    <div style={{ fontSize: '0.95rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                        Next 30 Min Outlook for Nifty Options
                    </div>
                    <div style={{
                        display: 'inline-block', padding: '0.4rem 1rem',
                        background: isPositive ? 'rgba(16,185,129,0.15)' : score < -5 ? 'rgba(239,68,68,0.15)' : 'rgba(148,163,184,0.15)',
                        borderRadius: 'var(--radius-md)', fontWeight: 600, fontSize: '0.85rem',
                        color: dirColor, border: `1px solid ${dirColor}33`,
                    }}>
                        Suggested: {data.suggested_action}
                    </div>
                </div>

                {/* Key Metrics */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem 1.5rem', fontSize: '0.82rem' }}>
                    <MetricItem label="Nifty LTP" value={data.nifty_ltp} />
                    <MetricItem label="Confidence" value={`${data.confidence}%`} color={dirColor} />
                    <MetricItem label="Indicator Score" value={data.indicator_score} color={data.indicator_score > 0 ? '#10b981' : '#ef4444'} />
                    <MetricItem label="OI Bias" value={data.oi_bias > 0 ? `+${data.oi_bias} (Bullish)` : data.oi_bias < 0 ? `${data.oi_bias} (Bearish)` : '0 (Neutral)'}
                        color={data.oi_bias > 0 ? '#10b981' : data.oi_bias < 0 ? '#ef4444' : '#94a3b8'} />
                </div>
            </div>

            {/* ═══ MULTI-TIMEFRAME CONFLUENCE TABLE ═══ */}
            <div className="glass" style={{ borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
                <div style={{ padding: '0.75rem 1.5rem', borderBottom: '1px solid var(--border-color)', fontWeight: 700, fontSize: '1rem' }}>
                    Multi-Timeframe Confluence — NIFTY
                </div>
                <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
                    <table>
                        <thead>
                            <tr>
                                <th>TF</th>
                                <th>Score</th>
                                <th>VWAP</th>
                                <th>EMA X</th>
                                <th>Alligator</th>
                                <th>ST 21-1</th>
                                <th>ST 14-2</th>
                                <th>ST 10-3</th>
                                <th>ADX</th>
                                <th>RSI</th>
                                <th>MACD</th>
                                <th>FRAMA</th>
                                <th>Mom%</th>
                            </tr>
                        </thead>
                        <tbody>
                            {['1m', '3m', '5m', '15m'].map(tf => {
                                const d = tfs[tf];
                                if (!d) return (
                                    <tr key={tf}>
                                        <td className="script-name">{tf}</td>
                                        <td colSpan={12} style={{ color: 'var(--text-muted)' }}>No data</td>
                                    </tr>
                                );
                                return (
                                    <tr key={tf}>
                                        <td className="script-name">{tf}</td>
                                        <td>
                                            <span className={`signal-badge ${d.normalized > 3 ? 'sig-buy-2' : d.normalized > 0 ? 'sig-buy' : d.normalized < -3 ? 'sig-sell-2' : d.normalized < 0 ? 'sig-sell' : 'sig-neutral'}`}>
                                                {d.normalized > 0 ? '+' : ''}{d.normalized}
                                            </span>
                                        </td>
                                        <SignalCell value={d.signals?.VWAP} />
                                        <SignalCell value={d.signals?.EMA_Cross} />
                                        <SignalCell value={d.signals?.Alligator} />
                                        <SignalCell value={d.signals?.ST_21_1} />
                                        <SignalCell value={d.signals?.ST_14_2} />
                                        <SignalCell value={d.signals?.ST_10_3} />
                                        <SignalCell value={d.signals?.ADX} />
                                        <SignalCell value={d.signals?.RSI} />
                                        <SignalCell value={d.signals?.MACD} />
                                        <SignalCell value={d.signals?.FRAMA} />
                                        <td className={d.momentum > 0 ? 'val-positive' : d.momentum < 0 ? 'val-negative' : ''} style={{ fontSize: '0.75rem' }}>
                                            {d.momentum > 0 ? '+' : ''}{d.momentum}%
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* ═══ BOTTOM ROW: OI + KEY LEVELS ═══ */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>

                {/* OI Analysis Card */}
                <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '1rem 1.5rem' }}>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>OI Analysis</h3>
                    {oi.pcr != null ? (
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.82rem' }}>
                            <MetricItem label="PCR (OI)" value={oi.pcr} color={oi.pcr > 1 ? '#10b981' : '#ef4444'} />
                            <MetricItem label="PCR Bias" value={oi.pcr_bias} color={oi.pcr_bias === 'Bullish' ? '#10b981' : oi.pcr_bias === 'Bearish' ? '#ef4444' : '#94a3b8'} />
                            <MetricItem label="CE OI Chg" value={(oi.ce_oi_change || 0).toLocaleString()} color="#fca5a5" />
                            <MetricItem label="PE OI Chg" value={(oi.pe_oi_change || 0).toLocaleString()} color="#6ee7b7" />
                        </div>
                    ) : (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>OI data unavailable (outside market hours)</div>
                    )}
                </div>

                {/* Key Levels Card */}
                <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '1rem 1.5rem' }}>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>Key Levels (OI-Based)</h3>
                    {oi.support ? (
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.82rem' }}>
                            <MetricItem label="🟢 Support (Max PE OI)" value={oi.support} color="#10b981" />
                            <MetricItem label="🔴 Resistance (Max CE OI)" value={oi.resistance} color="#ef4444" />
                            <MetricItem label="Max PE OI" value={(oi.max_pe_oi || 0).toLocaleString()} />
                            <MetricItem label="Max CE OI" value={(oi.max_ce_oi || 0).toLocaleString()} />
                            {tfs['5m'] && (
                                <>
                                    <MetricItem label="VWAP (5m)" value={tfs['5m'].vwap} color="#3b82f6" />
                                    <MetricItem label="RSI (5m)" value={tfs['5m'].rsi} color={tfs['5m'].rsi > 60 ? '#10b981' : tfs['5m'].rsi < 40 ? '#ef4444' : '#94a3b8'} />
                                </>
                            )}
                        </div>
                    ) : (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                            {tfs['5m'] ? (
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                                    <MetricItem label="VWAP (5m)" value={tfs['5m'].vwap} color="#3b82f6" />
                                    <MetricItem label="RSI (5m)" value={tfs['5m'].rsi} color={tfs['5m'].rsi > 60 ? '#10b981' : tfs['5m'].rsi < 40 ? '#ef4444' : '#94a3b8'} />
                                    <MetricItem label="EMA 9" value={tfs['5m'].ema9} />
                                    <MetricItem label="EMA 21" value={tfs['5m'].ema21} />
                                    <MetricItem label="ADX Strength" value={tfs['5m'].adx_strength} />
                                    <MetricItem label="MACD Hist" value={tfs['5m'].macd_hist} color={tfs['5m'].macd_hist > 0 ? '#10b981' : '#ef4444'} />
                                </div>
                            ) : 'Key levels unavailable'}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};


/* ─── Utility Components ─── */

const MetricItem = ({ label, value, color }) => (
    <div>
        <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem', marginBottom: '0.15rem' }}>{label}</div>
        <div style={{ fontWeight: 600, color: color || 'var(--text-primary)', fontSize: '0.9rem' }}>{value ?? '-'}</div>
    </div>
);

const SignalCell = ({ value }) => {
    const cls = getSignalClass(value);
    return (
        <td><span className={`signal-badge ${cls}`}>{value || '-'}</span></td>
    );
};

function getSignalClass(signal) {
    if (!signal || signal === '-' || signal === 'Neutral') return 'sig-neutral';
    const s = signal.toString();
    if (s.includes('Buy+++')) return 'sig-buy-3';
    if (s.includes('Buy++')) return 'sig-buy-2';
    if (s.includes('Buy+')) return 'sig-buy-1';
    if (s.includes('Buy')) return 'sig-buy';
    if (s.includes('Sell+++')) return 'sig-sell-3';
    if (s.includes('Sell++')) return 'sig-sell-2';
    if (s.includes('Sell+')) return 'sig-sell-1';
    if (s.includes('Sell')) return 'sig-sell';
    return 'sig-neutral';
}

const ScoreBar = ({ score }) => {
    // Score from -100 to +100, map to 0-100% bar position
    const pct = ((score + 100) / 200) * 100;
    const color = score > 15 ? '#10b981' : score > 5 ? '#34d399' : score < -15 ? '#ef4444' : score < -5 ? '#f87171' : '#94a3b8';

    return (
        <div style={{ marginTop: '0.5rem', width: '140px' }}>
            {/* Labels */}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.55rem', color: 'var(--text-muted)', marginBottom: '2px' }}>
                <span>SELL</span>
                <span>NEUTRAL</span>
                <span>BUY</span>
            </div>
            {/* Bar */}
            <div style={{
                height: '6px', background: 'linear-gradient(to right, #ef4444, #f87171, #94a3b8, #34d399, #10b981)',
                borderRadius: '3px', position: 'relative',
            }}>
                {/* Indicator */}
                <div style={{
                    position: 'absolute', left: `${pct}%`, top: '-3px',
                    width: '12px', height: '12px', borderRadius: '50%',
                    background: color, border: '2px solid var(--bg-surface)',
                    transform: 'translateX(-50%)',
                    boxShadow: `0 0 8px ${color}`,
                }} />
            </div>
        </div>
    );
};


export default MarketDirectionView;
