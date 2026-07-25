import React, { useState, useEffect, useCallback } from 'react';

const REGIME = {
    ACTIVE: { color: '#10b981', label: 'ACTIVE', hint: 'Moves likely — worth engaging' },
    NORMAL: { color: '#f59e0b', label: 'NORMAL', hint: 'Mixed — be selective' },
    DEAD: { color: '#94a3b8', label: 'DEAD', hint: 'Chop — stand aside' },
};
const REC = {
    TRADE: { color: '#10b981', label: 'TRADE' },
    SELECTIVE: { color: '#f59e0b', label: 'SELECTIVE' },
    STAND_ASIDE: { color: '#ef4444', label: 'STAND ASIDE' },
};
const LEAN = { UP: '#10b981', DOWN: '#ef4444', NEUTRAL: '#94a3b8' };

const IntradayReadView = () => {
    const [payload, setPayload] = useState(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);

    const fetchRead = useCallback(async () => {
        try {
            const res = await fetch('/api/intraday-read');
            setPayload(await res.json());
        } catch { setPayload(null); }
        setLoading(false);
    }, []);

    const refresh = async () => {
        setRefreshing(true);
        try {
            const res = await fetch('/api/intraday-read/refresh', { method: 'POST' });
            setPayload(await res.json());
        } catch { /* keep previous */ }
        setRefreshing(false);
    };

    useEffect(() => {
        fetchRead();
        const id = setInterval(fetchRead, 60000);
        return () => clearInterval(id);
    }, [fetchRead]);

    if (loading) return <Center muted>Loading AI market read…</Center>;

    const data = payload?.data;
    const gauge = data?.gauge || {};
    const llm = data?.llm || {};
    const r = llm.read || {};

    const RefreshBtn = (
        <button onClick={refresh} disabled={refreshing} style={{
            padding: '0.35rem 0.9rem', borderRadius: 'var(--radius-sm)', border: 'none',
            fontSize: '0.72rem', fontWeight: 700, cursor: refreshing ? 'default' : 'pointer',
            background: 'var(--accent-blue)', color: '#fff', opacity: refreshing ? 0.6 : 1,
        }}>{refreshing ? 'Generating…' : '↻ Refresh'}</button>
    );

    if (!payload?.available) {
        return (
            <Card>
                <Row between>
                    <Title icon="🧠">AI Market Read</Title>
                    {RefreshBtn}
                </Row>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '0.6rem' }}>
                    {payload?.message || 'No read available yet.'}
                </div>
            </Card>
        );
    }

    if (llm.configured === false) {
        return (
            <Card>
                <Row between><Title icon="🧠">AI Market Read</Title>{RefreshBtn}</Row>
                <div style={{ color: 'var(--status-sell)', fontSize: '0.85rem', marginTop: '0.6rem' }}>
                    OpenRouter not configured. Set <code>OPENROUTER_API_KEY</code> in the ml-sidecar env (Dokploy).
                </div>
                <GaugeRow gauge={gauge} />
            </Card>
        );
    }
    if (llm.error) {
        return (
            <Card>
                <Row between><Title icon="🧠">AI Market Read</Title>{RefreshBtn}</Row>
                <div style={{ color: 'var(--status-sell)', fontSize: '0.8rem', marginTop: '0.6rem' }}>LLM error: {llm.error}</div>
                <GaugeRow gauge={gauge} />
            </Card>
        );
    }

    const reg = REGIME[r.regime] || REGIME.NORMAL;
    const rec = REC[r.recommendation] || REC.SELECTIVE;
    const leanColor = LEAN[r.directional_lean] || LEAN.NEUTRAL;
    const kl = r.key_levels || {};

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {/* HEADER */}
            <Card>
                <Row between wrap>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <Title icon="🧠">AI Market Read</Title>
                        <Badge color={reg.color} text={reg.label} sub={reg.hint} />
                        <Badge color={rec.color} text={rec.label} sub="recommendation" />
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.7rem' }}>
                        <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>
                            {llm.model || ''} · {data.ts ? new Date(data.ts).toLocaleTimeString() : ''}
                        </span>
                        {RefreshBtn}
                    </div>
                </Row>
                {r.summary && (
                    <div style={{ marginTop: '0.7rem', fontSize: '0.95rem', fontWeight: 600, lineHeight: 1.4 }}>
                        {r.summary}
                    </div>
                )}
                {r.two_liner && (
                    <div style={{ marginTop: '0.4rem', fontSize: '0.78rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                        {r.two_liner}
                    </div>
                )}
            </Card>

            <GaugeRow gauge={gauge} lean={r.directional_lean} leanConf={r.lean_confidence}
                      leanColor={leanColor} expVol={r.expected_volatility} />

            {/* LEVELS */}
            {(kl.support?.length || kl.resistance?.length) ? (
                <Card>
                    <Sub>Key Levels (from OI chain)</Sub>
                    <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', marginTop: '0.4rem' }}>
                        <LevelSet label="Support" color="#10b981" levels={kl.support} />
                        <LevelSet label="Resistance" color="#ef4444" levels={kl.resistance} />
                    </div>
                </Card>
            ) : null}

            {/* SECTIONS */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '0.75rem' }}>
                <Section icon="🌍" title="Global / Macro" body={r.global_macro} />
                <Section icon="⛓️" title="Options Chain" body={r.options_chain_read} />
                <Section icon="🤖" title="Internal Models" body={r.internal_models} />
                <Section icon="📰" title="News Watch" body={r.news_watch} />
            </div>

            {/* WATCH + RISKS */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '0.75rem' }}>
                <ListCard icon="👁️" title="Watch — next 10 min" items={r.watch_next_10min} color="var(--accent-blue)" />
                <ListCard icon="⚠️" title="Key Risks" items={r.key_risks} color="#f59e0b" />
            </div>

            {/* DETAILED READ */}
            {r.detailed_read && (
                <Card>
                    <Sub>Detailed Read</Sub>
                    <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', lineHeight: 1.65, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
                        {r.detailed_read}
                    </div>
                </Card>
            )}

            <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', textAlign: 'center', padding: '0.2rem' }}>
                Advisory only — does not place or modify trades. Direction is low-confidence by design; the volatility gauge is the reliable signal.
            </div>
        </div>
    );
};

/* ── building blocks ── */
const Center = ({ children, muted }) => (
    <div style={{ textAlign: 'center', padding: '3rem', color: muted ? 'var(--text-muted)' : 'var(--text-primary)' }}>{children}</div>
);
const Card = ({ children }) => (
    <div className="glass" style={{ borderRadius: 'var(--radius-lg)', padding: '0.9rem 1.3rem' }}>{children}</div>
);
const Row = ({ children, between, wrap }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem',
        justifyContent: between ? 'space-between' : 'flex-start', flexWrap: wrap ? 'wrap' : 'nowrap' }}>{children}</div>
);
const Title = ({ icon, children }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, fontSize: '1rem' }}>
        <span style={{ fontSize: '1.2rem' }}>{icon}</span>{children}
    </div>
);
const Sub = ({ children }) => (
    <div style={{ fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-muted)' }}>{children}</div>
);
const Badge = ({ color, text, sub }) => (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
        <span style={{ fontSize: '0.78rem', fontWeight: 800, color, padding: '0.12rem 0.5rem', borderRadius: 4, background: `${color}18`, textAlign: 'center' }}>{text}</span>
        {sub && <span style={{ fontSize: '0.55rem', color: 'var(--text-muted)', textAlign: 'center', marginTop: '0.1rem' }}>{sub}</span>}
    </div>
);
const Section = ({ icon, title, body }) => (
    <Card>
        <Row><span>{icon}</span><Sub>{title}</Sub></Row>
        <div style={{ marginTop: '0.4rem', fontSize: '0.8rem', lineHeight: 1.55, color: 'var(--text-primary)' }}>
            {body || <span style={{ color: 'var(--text-muted)' }}>—</span>}
        </div>
    </Card>
);
const ListCard = ({ icon, title, items, color }) => (
    <Card>
        <Row><span>{icon}</span><Sub>{title}</Sub></Row>
        <ul style={{ margin: '0.5rem 0 0', paddingLeft: '1.1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            {(items || []).map((it, i) => (
                <li key={i} style={{ fontSize: '0.78rem', lineHeight: 1.45, color: 'var(--text-primary)' }}>
                    <span style={{ color, marginLeft: '-0.2rem' }}></span>{it}
                </li>
            ))}
            {(!items || items.length === 0) && <li style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>—</li>}
        </ul>
    </Card>
);
const LevelSet = ({ label, color, levels }) => (
    <div>
        <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>{label}</div>
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            {(levels || []).map((lv, i) => (
                <span key={i} style={{ fontSize: '0.8rem', fontWeight: 700, color, padding: '0.15rem 0.55rem', borderRadius: 5, background: `${color}15` }}>{lv}</span>
            ))}
            {(!levels || levels.length === 0) && <span style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>—</span>}
        </div>
    </div>
);

const GaugeRow = ({ gauge, lean, leanConf, leanColor, expVol }) => (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.6rem' }}>
        <Stat label="Regime" value={gauge.regime || '—'} />
        <Stat label="ATR %" value={gauge.atr_pct != null ? gauge.atr_pct : '—'} />
        <Stat label="India VIX" value={gauge.vix != null ? gauge.vix : '—'} sub={gauge.vix_regime} />
        <Stat label="Move Likelihood" value={gauge.move_likelihood || '—'} />
        <Stat label="Session" value={gauge.time_bucket || '—'} />
        {expVol && <Stat label="Exp. Volatility" value={expVol} />}
        {lean && <Stat label="Dir Lean" value={lean} color={leanColor} sub={leanConf ? `${leanConf} conf` : ''} />}
    </div>
);
const Stat = ({ label, value, sub, color }) => (
    <div className="glass" style={{ borderRadius: 'var(--radius-md)', padding: '0.55rem 0.8rem' }}>
        <div style={{ fontSize: '0.58rem', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-muted)' }}>{label}</div>
        <div style={{ fontSize: '0.95rem', fontWeight: 700, color: color || 'var(--text-primary)', marginTop: '0.15rem' }}>{String(value)}</div>
        {sub && <div style={{ fontSize: '0.56rem', color: 'var(--text-muted)' }}>{sub}</div>}
    </div>
);

export default IntradayReadView;
