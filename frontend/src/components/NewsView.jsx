import React, { useState, useEffect, useCallback } from 'react';

const SENTIMENT_CONFIG = {
    bullish: { dot: '🟢', color: '#10b981', label: 'Bullish' },
    mildly_bullish: { dot: '🟢', color: '#34d399', label: 'Mild Bull' },
    bearish: { dot: '🔴', color: '#ef4444', label: 'Bearish' },
    mildly_bearish: { dot: '🔴', color: '#f87171', label: 'Mild Bear' },
    neutral: { dot: '⚪', color: '#94a3b8', label: 'Neutral' },
};

const FILTERS = ['All', 'Bullish', 'Bearish', 'Market Moving'];

const NewsView = () => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('All');
    const [expandedId, setExpandedId] = useState(null);

    const fetchNews = useCallback(async () => {
        try {
            const res = await fetch('/api/news');
            const json = await res.json();
            setData(json);
        } catch (e) {
            setData(null);
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        fetchNews();
        const id = setInterval(fetchNews, 120000);
        return () => clearInterval(id);
    }, [fetchNews]);

    if (loading) return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>Fetching market news...</div>;
    if (!data) return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--status-sell)' }}>Failed to load news</div>;

    const headlines = (data.headlines || []).filter(h => {
        if (filter === 'All') return true;
        if (filter === 'Bullish') return h.sentiment?.includes('bullish');
        if (filter === 'Bearish') return h.sentiment?.includes('bearish');
        if (filter === 'Market Moving') return h.market_moving;
        return true;
    });

    const summary = data.sentiment_summary || {};

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>

            {/* ═══ HEADER BAR ═══ */}
            <div className="glass" style={{
                borderRadius: 'var(--radius-lg)', padding: '0.75rem 1.5rem',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <span style={{ fontSize: '1.3rem' }}>📰</span>
                    <div>
                        <div style={{ fontWeight: 700, fontSize: '1rem' }}>Market News</div>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                            {data.sources_active}/{data.sources_total} sources • {data.total} headlines
                        </div>
                    </div>
                </div>

                {/* Sentiment Summary Pills */}
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <SentimentPill color="#10b981" count={summary.bullish || 0} label="Bull" />
                    <SentimentPill color="#ef4444" count={summary.bearish || 0} label="Bear" />
                    <SentimentPill color="#94a3b8" count={summary.neutral || 0} label="Neutral" />
                </div>

                {/* Filter Chips */}
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                    {FILTERS.map(f => (
                        <button key={f} onClick={() => setFilter(f)} style={{
                            padding: '0.25rem 0.7rem', borderRadius: 'var(--radius-sm)', border: 'none',
                            fontSize: '0.72rem', fontWeight: 600, cursor: 'pointer',
                            background: filter === f ? 'var(--accent-blue)' : 'rgba(255,255,255,0.06)',
                            color: filter === f ? '#fff' : 'var(--text-muted)',
                            transition: 'all 0.2s',
                        }}>
                            {f}
                        </button>
                    ))}
                </div>
            </div>

            {/* ═══ NEWS FEED ═══ */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                {headlines.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                        No headlines match "{filter}" filter
                    </div>
                ) : (
                    headlines.map((h, idx) => {
                        const s = SENTIMENT_CONFIG[h.sentiment] || SENTIMENT_CONFIG.neutral;
                        const isExpanded = expandedId === idx;

                        return (
                            <div key={idx} className="glass" style={{
                                borderRadius: 'var(--radius-md)',
                                padding: '0.6rem 1rem',
                                borderLeft: `3px solid ${h.market_moving ? s.color : 'transparent'}`,
                                cursor: 'pointer',
                                transition: 'all 0.2s',
                            }}
                                onClick={() => setExpandedId(isExpanded ? null : idx)}
                            >
                                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem' }}>
                                    {/* Sentiment Dot */}
                                    <span style={{ fontSize: '0.7rem', marginTop: '0.2rem', flexShrink: 0 }}>{s.dot}</span>

                                    {/* Content */}
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{
                                            fontSize: '0.82rem', fontWeight: 600, lineHeight: 1.35,
                                            color: 'var(--text-primary)',
                                        }}>
                                            {h.title}
                                            {h.market_moving && (
                                                <span style={{
                                                    fontSize: '0.55rem', fontWeight: 700, marginLeft: '0.4rem',
                                                    padding: '0.1rem 0.35rem', borderRadius: 3,
                                                    background: 'rgba(239,68,68,0.15)', color: '#ef4444',
                                                    verticalAlign: 'middle',
                                                }}>
                                                    MARKET MOVER
                                                </span>
                                            )}
                                        </div>

                                        {/* Expanded Description */}
                                        {isExpanded && h.description && (
                                            <div style={{
                                                fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.3rem',
                                                lineHeight: 1.5, paddingBottom: '0.2rem',
                                            }}>
                                                {h.description}
                                                {h.link && (
                                                    <a href={h.link} target="_blank" rel="noopener noreferrer" style={{
                                                        color: 'var(--accent-blue)', marginLeft: '0.5rem', fontSize: '0.7rem',
                                                    }}>
                                                        Read full →
                                                    </a>
                                                )}
                                            </div>
                                        )}
                                    </div>

                                    {/* Meta */}
                                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', flexShrink: 0, gap: '0.15rem' }}>
                                        <span style={{
                                            fontSize: '0.6rem', fontWeight: 700, color: s.color,
                                            padding: '0.1rem 0.35rem', borderRadius: 3,
                                            background: `${s.color}12`,
                                        }}>
                                            {s.label}
                                        </span>
                                        <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)' }}>{h.time_ago}</span>
                                        <span style={{
                                            fontSize: '0.55rem', fontWeight: 700, color: 'var(--text-muted)',
                                            background: 'rgba(255,255,255,0.04)',
                                            padding: '0.05rem 0.3rem', borderRadius: 2,
                                        }}>
                                            {h.source_icon}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
};


/* ─── Sentiment Summary Pill ─── */
const SentimentPill = ({ color, count, label }) => (
    <div style={{
        display: 'flex', alignItems: 'center', gap: '0.3rem',
        padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)',
        background: `${color}10`, border: `1px solid ${color}20`,
        fontSize: '0.68rem',
    }}>
        <span style={{ fontWeight: 700, color }}>{count}</span>
        <span style={{ color: 'var(--text-muted)' }}>{label}</span>
    </div>
);


export default NewsView;
