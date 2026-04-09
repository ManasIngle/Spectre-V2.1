import React, { useState, useEffect, useCallback } from 'react';

const TradeSignalsView = () => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    const fetchSignals = useCallback(async () => {
        try {
            const res = await fetch('/api/trade-signals');
            const json = await res.json();
            setData(json);
        } catch (e) {
            setData({ error: 'Failed to fetch trade signals', signal: 'ERROR' });
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        fetchSignals();
        const id = setInterval(fetchSignals, 30000);
        return () => clearInterval(id);
    }, [fetchSignals]);

    if (loading && !data) {
        return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>Running ML model inference...</div>;
    }

    if (!data || data.error) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--status-sell)' }}>
                {data?.error || 'Error loading signals'}
            </div>
        );
    }

    const isBuy = data.signal?.includes('BUY');
    const isCE = data.option_type === 'CE';
    const isPE = data.option_type === 'PE';
    const noTrade = data.signal === 'NO TRADE';
    const mainColor = isCE ? '#10b981' : isPE ? '#ef4444' : '#94a3b8';

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>

            {/* ═══ MAIN SIGNAL CARD ═══ */}
            <div className="glass" style={{
                borderRadius: 'var(--radius-lg)', overflow: 'hidden',
                borderLeft: `5px solid ${mainColor}`,
            }}>
                {/* Signal Header */}
                <div style={{
                    padding: '1.5rem 2rem', display: 'flex', alignItems: 'center',
                    gap: '2rem', flexWrap: 'wrap',
                    background: noTrade ? 'rgba(148,163,184,0.05)' : isCE ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
                }}>
                    {/* Signal Badge */}
                    <div style={{ textAlign: 'center', minWidth: '160px' }}>
                        <div style={{
                            fontSize: '2rem', fontWeight: 800, color: mainColor,
                            fontFamily: 'var(--font-display)', letterSpacing: '-0.02em',
                        }}>
                            {data.signal}
                        </div>
                        {!noTrade && (
                            <div style={{
                                fontSize: '1.4rem', fontWeight: 700, marginTop: '0.25rem',
                                color: 'var(--text-primary)',
                            }}>
                                NIFTY {data.strike} {data.option_type}
                            </div>
                        )}
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.3rem' }}>
                            ML Prediction: {data.prediction} | Valid until {data.valid_until}
                        </div>
                    </div>

                    {/* Price Levels */}
                    {!noTrade && (
                        <div style={{
                            display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '0.75rem 2rem',
                            flex: 1, minWidth: '300px',
                        }}>
                            <LevelBox label="Nifty Spot" value={data.nifty_spot} color="var(--text-primary)" />
                            <LevelBox label="Target (Nifty)" value={data.target_nifty} color="#10b981" />
                            <LevelBox label="SL (Nifty)" value={data.sl_nifty} color="#ef4444" />
                            <LevelBox label="Strike" value={data.strike} color={mainColor} />
                            <LevelBox
                                label="Option LTP"
                                value={data.option_ltp != null ? `₹${data.option_ltp}` : 'N/A'}
                                color={mainColor}
                            />
                            <LevelBox label="Support (OI)" value={data.support} color="#10b981" />
                            <LevelBox label="Resistance (OI)" value={data.resistance} color="#ef4444" />
                        </div>
                    )}

                    {/* Confidence Gauge */}
                    <div style={{ textAlign: 'center', minWidth: '100px' }}>
                        <ConfidenceRing value={data.confidence} color={mainColor} />
                        <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                            Model Acc: {(data.model_accuracy * 100).toFixed(1)}%
                        </div>
                    </div>
                </div>

                {/* Confirmation Badges */}
                <div style={{
                    display: 'flex', gap: '1rem', padding: '0.75rem 2rem', flexWrap: 'wrap',
                    borderTop: '1px solid var(--border-color)',
                    fontSize: '0.8rem',
                }}>
                    <ConfirmBadge label="OI Confirmation" confirmed={data.oi_confirms} detail={data.pcr ? `PCR: ${data.pcr}` : 'N/A'} />
                    <ConfirmBadge label="Equity Momentum" confirmed={data.equity_confirms} detail={`${data.equity_return > 0 ? '+' : ''}${data.equity_return}%`} />
                    <ConfirmBadge label="Advance %" confirmed={data.equity_advance_pct > 50} detail={`${data.equity_advance_pct}%`} />
                </div>
            </div>

            {/* ═══ BOTTOM ROW ═══ */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>

                {/* Probability Bars */}
                <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '1rem 1.5rem' }}>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>
                        Model Probabilities
                    </h3>
                    <ProbBar label="UP (Buy CE)" pct={data.prob_up} color="#10b981" />
                    <ProbBar label="SIDEWAYS" pct={data.prob_sideways} color="#94a3b8" />
                    <ProbBar label="DOWN (Buy PE)" pct={data.prob_down} color="#ef4444" />
                </div>
                
                {/* Cross-Asset Aggressive Breakout */}
                <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '1rem 1.5rem', border: '1px solid rgba(234, 179, 8, 0.3)' }}>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem', color: '#eab308' }}>
                        BankNifty Cross-Asset 
                        <span style={{ fontSize: '0.65rem', marginLeft: '8px', color: 'var(--text-muted)' }}>(Aggressive Trend)</span>
                    </h3>
                    
                    <div style={{
                        fontSize: '1.4rem', fontWeight: 800, marginBottom: '1rem',
                        color: data.CrossAssetSignal === 'UP' ? '#10b981' : data.CrossAssetSignal === 'DOWN' ? '#ef4444' : '#94a3b8'
                    }}>
                        {data.CrossAssetSignal === 'UP' ? 'BUY CE' : data.CrossAssetSignal === 'DOWN' ? 'BUY PE' : 'NO TRADE'}
                    </div>
                    
                    {data.cross_asset_probs && data.cross_asset_probs.length === 3 && (
                        <>
                            <ProbBar label="UP" pct={data.cross_asset_probs[2]} color="#10b981" height="4px" />
                            <ProbBar label="DOWN" pct={data.cross_asset_probs[0]} color="#ef4444" height="4px" />
                        </>
                    )}
                </div>

                {/* Key Factors */}
                <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '1rem 1.5rem' }}>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>
                        Contributing Factors
                    </h3>
                    {(data.key_factors || []).length > 0 ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                            {data.key_factors.map((f, idx) => (
                                <div key={idx} style={{
                                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                    padding: '0.4rem 0.6rem', borderRadius: 'var(--radius-sm)',
                                    background: 'rgba(255,255,255,0.03)', fontSize: '0.82rem',
                                }}>
                                    <span style={{ fontWeight: 600 }}>{f.factor}</span>
                                    <span style={{ color: 'var(--text-muted)' }}>{f.value}</span>
                                    <span className={`signal-badge ${f.bias.includes('Bullish') ? 'sig-buy' : f.bias.includes('Bearish') ? 'sig-sell' : 'sig-neutral'}`}
                                        style={{ fontSize: '0.7rem', padding: '0.15rem 0.5rem' }}>
                                        {f.bias}
                                    </span>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                            No strong directional factors detected
                        </div>
                    )}
                </div>
            </div>

            {/* Disclaimer */}
            <div style={{
                fontSize: '0.65rem', color: 'var(--text-muted)', textAlign: 'center',
                padding: '0.5rem', opacity: 0.6,
            }}>
                This is an ML-generated signal for educational purposes only. Model accuracy: {(data.model_accuracy * 100).toFixed(1)}%. Always use proper risk management. Past performance does not guarantee future results.
            </div>
        </div>
    );
};


/* ─── Sub-Components ─── */

const LevelBox = ({ label, value, color }) => (
    <div>
        <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>{label}</div>
        <div style={{ fontSize: '1.05rem', fontWeight: 700, color }}>{value}</div>
    </div>
);

const ConfidenceRing = ({ value, color }) => {
    const pct = Math.min(value, 100);
    const radius = 35;
    const circ = 2 * Math.PI * radius;
    const offset = circ * (1 - pct / 100);

    return (
        <svg width="90" height="90" viewBox="0 0 90 90">
            <circle cx="45" cy="45" r={radius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="5" />
            <circle cx="45" cy="45" r={radius} fill="none" stroke={color} strokeWidth="5"
                strokeDasharray={circ} strokeDashoffset={offset}
                strokeLinecap="round" transform="rotate(-90 45 45)"
                style={{ transition: 'stroke-dashoffset 0.5s ease' }} />
            <text x="45" y="42" textAnchor="middle" fill={color} fontSize="16" fontWeight="800">{pct.toFixed(0)}%</text>
            <text x="45" y="56" textAnchor="middle" fill="var(--text-muted)" fontSize="8">CONFIDENCE</text>
        </svg>
    );
};

const ConfirmBadge = ({ label, confirmed, detail }) => (
    <div style={{
        display: 'flex', alignItems: 'center', gap: '0.4rem',
        padding: '0.3rem 0.75rem', borderRadius: 'var(--radius-md)',
        background: confirmed ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.08)',
        border: `1px solid ${confirmed ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.15)'}`,
    }}>
        <span style={{ color: confirmed ? '#10b981' : '#ef4444' }}>{confirmed ? '✓' : '✗'}</span>
        <span style={{ fontWeight: 600 }}>{label}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>({detail})</span>
    </div>
);

const ProbBar = ({ label, pct, color }) => (
    <div style={{ marginBottom: '0.75rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', marginBottom: '0.25rem' }}>
            <span>{label}</span>
            <span style={{ fontWeight: 700, color }}>{pct.toFixed(1)}%</span>
        </div>
        <div style={{ height: '8px', background: 'rgba(255,255,255,0.06)', borderRadius: '4px', overflow: 'hidden' }}>
            <div style={{
                height: '100%', width: `${pct}%`, background: color,
                borderRadius: '4px', transition: 'width 0.5s ease',
                boxShadow: `0 0 8px ${color}33`,
            }} />
        </div>
    </div>
);


export default TradeSignalsView;
