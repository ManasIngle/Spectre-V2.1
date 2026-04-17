import React, { useState, useEffect, useCallback } from 'react';

const TradeSignalsView = () => {
    const [data, setData] = useState(null);
    const [morning, setMorning] = useState(null);
    const [scalper, setScalper] = useState(null);
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

    const fetchMorning = useCallback(async () => {
        try {
            const res = await fetch('/api/morning-signal');
            const json = await res.json();
            setMorning(json);
        } catch (_) {
            setMorning(null);
        }
    }, []);

    const fetchScalper = useCallback(async () => {
        try {
            const res = await fetch('/api/scalper-signal');
            const json = await res.json();
            setScalper(json);
        } catch (_) {
            setScalper(null);
        }
    }, []);

    useEffect(() => {
        fetchSignals();
        fetchMorning();
        fetchScalper();
        const id  = setInterval(fetchSignals, 30000);
        const mId = setInterval(fetchMorning, 60000);
        const sId = setInterval(fetchScalper, 60000); // scalper refreshes every minute
        return () => { clearInterval(id); clearInterval(mId); clearInterval(sId); };
    }, [fetchSignals, fetchMorning, fetchScalper]);

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
                            display: 'inline-block', fontSize: '0.6rem', fontWeight: 700,
                            color: '#a78bfa', background: 'rgba(167,139,250,0.12)',
                            border: '1px solid rgba(167,139,250,0.25)',
                            borderRadius: '4px', padding: '0.15rem 0.5rem',
                            letterSpacing: '0.06em', marginBottom: '0.35rem', textTransform: 'uppercase',
                        }}>
                            Stabilized Ensemble · Model 1 + 2
                        </div>
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
                            <LevelBox label="Nifty Spot" value={parseFloat(data.nifty_spot).toFixed(2)} color="var(--text-primary)" />
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
                            Model Acc: {data.model_accuracy.toFixed(1)}%
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

            {/* ═══ 3-MINUTE SCALPER LSTM ═══ */}
            {scalper && !scalper.error && (
                <ScalperCard scalper={scalper} />
            )}

            {/* ═══ BOTTOM ROW ═══ */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>

                {/* Probability Bars */}
                <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '1rem 1.5rem' }}>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>
                        Model Probabilities
                    </h3>
                    <ProbBar label="UP (Buy CE)" pct={data.prob_up} color="#10b981" />
                    <ProbBar label="SIDEWAYS" pct={data.prob_sideways} color="#94a3b8" />
                    <ProbBar label="DOWN (Buy PE)" pct={data.prob_down} color="#ef4444" />
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

            {/* ═══ MODEL BREAKDOWN ROW ═══ */}
            {data.models && (
                <div style={{ display: 'grid', gridTemplateColumns: data.models.old_direction ? '1fr 1fr 1fr 1fr' : '1fr 1fr 1fr', gap: '1rem' }}>
                    {data.models.rolling && <ModelCard model={data.models.rolling} accent="#6366f1" />}
                    {data.models.direction && <ModelCard model={data.models.direction} accent="#8b5cf6" />}
                    {data.models.cross_asset && <ModelCard model={data.models.cross_asset} accent="#eab308" />}
                    {data.models.old_direction && <ModelCard model={data.models.old_direction} accent="#f97316" />}
                </div>
            )}

            {/* ═══ MORNING OPENING SIGNAL ═══ */}
            {morning && morning.raw_signal && morning.raw_signal !== 'NOT YET' && morning.raw_signal !== 'PENDING' && (
                <div className="glass" style={{
                    borderRadius: 'var(--radius-lg)', overflow: 'hidden',
                    borderLeft: `5px solid ${morning.gap_filter === 'SKIP' ? '#ef4444' : morning.gap_filter === 'CAUTION' ? '#f59e0b' : '#10b981'}`,
                }}>
                    <div style={{ padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
                        <div style={{ textAlign: 'center', minWidth: '160px' }}>
                            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.2rem' }}>
                                Morning Opening Signal
                            </div>
                            <div style={{
                                fontSize: '1.6rem', fontWeight: 800,
                                color: morning.raw_signal.includes('CE') ? '#10b981' : morning.raw_signal.includes('PE') ? '#ef4444' : '#94a3b8',
                            }}>
                                {morning.raw_signal}
                            </div>
                            {morning.option_type !== '-' && (
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                                    Spot: {morning.nifty_spot} | Prev Close: {morning.prev_day_close}
                                </div>
                            )}
                        </div>
                        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', flex: 1 }}>
                            <LevelBox label="Confidence" value={`${morning.confidence.toFixed(1)}%`} color={morning.confidence > 45 ? '#10b981' : '#f59e0b'} />
                            <LevelBox label="Filtered Conf" value={`${morning.filtered_confidence.toFixed(1)}%`} color="#94a3b8" />
                            <LevelBox label="Prob Gap" value={`${morning.prob_gap.toFixed(1)}%`} color="#94a3b8" />
                            <LevelBox label="Gap" value={`${morning.gap_pct > 0 ? '+' : ''}${morning.gap_pct.toFixed(2)}%`} color={Math.abs(morning.gap_pct) > 0.8 ? '#ef4444' : Math.abs(morning.gap_pct) > 0.4 ? '#f59e0b' : '#10b981'} />
                            <LevelBox label="Gap Type" value={morning.gap_type} color={morning.gap_severity === 'high' ? '#ef4444' : morning.gap_severity === 'medium' ? '#f59e0b' : '#10b981'} />
                            <LevelBox label="Filter" value={morning.gap_filter} color={morning.gap_filter === 'SKIP' ? '#ef4444' : morning.gap_filter === 'CAUTION' ? '#f59e0b' : '#10b981'} />
                            <LevelBox label="Prev Day" value={morning.prev_day_trend} color={morning.prev_day_trend === 'BULLISH' ? '#10b981' : morning.prev_day_trend === 'BEARISH' ? '#ef4444' : '#94a3b8'} />
                            <LevelBox label="Model Acc" value={`${morning.model_accuracy}%`} color="var(--text-primary)" />
                        </div>
                        <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                            {morning.generated_at} | Valid for {morning.valid_for_minutes} min
                        </div>
                    </div>
                </div>
            )}

            {/* Disclaimer */}
            <div style={{
                fontSize: '0.65rem', color: 'var(--text-muted)', textAlign: 'center',
                padding: '0.5rem', opacity: 0.6,
            }}>
                This is an ML-generated signal for educational purposes only.                 Model accuracy: {data.model_accuracy.toFixed(1)}%. Always use proper risk management. Past performance does not guarantee future results.
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

const ModelCard = ({ model, accent }) => {
    const labels = ['DOWN', 'SIDEWAYS', 'UP'];
    const pred = labels[model.prediction] || 'N/A';
    const sigColor = pred === 'UP' ? '#10b981' : pred === 'DOWN' ? '#ef4444' : '#94a3b8';
    return (
        <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '1rem 1.2rem', borderTop: `3px solid ${accent}` }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: accent, marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                {model.label}
            </div>
            <div style={{ fontSize: '1.3rem', fontWeight: 800, color: sigColor, marginBottom: '0.5rem' }}>
                {model.signal || pred}
            </div>
            {model.probs && model.probs.length === 3 && (
                <>
                    <ProbBar label="UP" pct={model.probs[2]} color="#10b981" height="3px" />
                    <ProbBar label="SIDE" pct={model.probs[1]} color="#94a3b8" height="3px" />
                    <ProbBar label="DOWN" pct={model.probs[0]} color="#ef4444" height="3px" />
                </>
            )}
            <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '0.3rem' }}>
                Acc: {model.accuracy ? (model.accuracy).toFixed(1) : 'N/A'}%
            </div>
        </div>
    );
};

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


const ScalperCard = ({ scalper }) => {
    const sig = scalper.signal || 'NO TRADE';
    const pred = scalper.prediction || 'SIDEWAYS';
    const conf = scalper.confidence || 0;
    const color = sig === 'BUY CE' ? '#10b981' : sig === 'BUY PE' ? '#ef4444' : '#64748b';
    const probs = scalper.probs || {};

    return (
        <div className="glass" style={{
            borderRadius: 'var(--radius-lg)', overflow: 'hidden',
            borderLeft: `5px solid ${color}`,
        }}>
            <div style={{ padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', gap: '2rem', flexWrap: 'wrap' }}>
                {/* Label */}
                <div style={{ minWidth: 180 }}>
                    <div style={{
                        fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.07em',
                        textTransform: 'uppercase', color: '#a78bfa',
                        background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.25)',
                        borderRadius: '4px', padding: '0.15rem 0.5rem', display: 'inline-block', marginBottom: '0.4rem',
                    }}>
                        3-Min Scalper LSTM · Next {scalper.horizon_minutes || 3} min
                    </div>
                    <div style={{ fontSize: '1.8rem', fontWeight: 800, color, fontFamily: 'var(--font-display)', lineHeight: 1 }}>
                        {sig}
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                        Prediction: {pred} · Model Acc: {scalper.model_accuracy?.toFixed(1) || '—'}%
                    </div>
                </div>

                {/* Confidence ring */}
                <div style={{ textAlign: 'center' }}>
                    <ConfidenceRing value={conf} color={color} />
                    <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>Confidence</div>
                </div>

                {/* Prob bars */}
                <div style={{ flex: 1, minWidth: 200 }}>
                    {[
                        { label: 'UP  (BUY CE)', val: probs.up,       color: '#10b981' },
                        { label: 'SIDEWAYS',      val: probs.sideways, color: '#94a3b8' },
                        { label: 'DOWN (BUY PE)', val: probs.down,     color: '#ef4444' },
                    ].map(({ label, val, color: c }) => (
                        <div key={label} style={{ marginBottom: '0.5rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '0.2rem' }}>
                                <span>{label}</span>
                                <span style={{ fontWeight: 700, color: c }}>{val != null ? `${val.toFixed(1)}%` : '—'}</span>
                            </div>
                            <div style={{ height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
                                <div style={{ height: '100%', width: `${val || 0}%`, background: c, borderRadius: '3px', transition: 'width 0.5s ease' }} />
                            </div>
                        </div>
                    ))}
                </div>

                {/* Meta */}
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                    <span>Bars used: {scalper.bars_available || '—'}</span>
                    <span>Lookback: {scalper.seq_len_used || 30} min</span>
                    <span>UP recall: 72% · trained 2015-2022</span>
                </div>
            </div>
        </div>
    );
};

export default TradeSignalsView;
