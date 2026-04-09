import React, { useMemo } from 'react';

const Heatmap = ({ data, total, requested }) => {
    if (!data || data.length === 0) {
        return (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '3rem' }}>
                Loading heatmap for ~800 NSE stocks... This may take a moment.
            </div>
        );
    }

    const getColor = (percent) => {
        if (percent === 0) return 'rgba(51, 65, 85, 0.6)';
        const absVal = Math.min(Math.abs(percent), 6);
        const intensity = 0.35 + (absVal / 6) * 0.65;
        if (percent > 0) {
            return `rgba(16, 185, 129, ${intensity})`;
        } else {
            return `rgba(239, 68, 68, ${intensity})`;
        }
    };

    // Count positive vs negative for summary
    const summary = useMemo(() => {
        let pos = 0, neg = 0, flat = 0;
        data.forEach(d => {
            if (d.changePercent > 0.1) pos++;
            else if (d.changePercent < -0.1) neg++;
            else flat++;
        });
        return { pos, neg, flat };
    }, [data]);

    const breadth = summary.pos > 0
        ? ((summary.pos / (summary.pos + summary.neg)) * 100).toFixed(0)
        : 0;

    return (
        <div className="glass" style={{ padding: '1.25rem', borderRadius: 'var(--radius-lg)' }}>
            {/* Summary Bar */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>
                    NSE Market Heatmap
                </h2>
                <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    <span>
                        Loaded: <strong style={{ color: 'var(--text-primary)' }}>{data.length}</strong>
                        {requested ? ` / ${requested}` : ''}
                    </span>
                    <span>
                        Advancing: <strong className="val-positive">{summary.pos}</strong>
                    </span>
                    <span>
                        Declining: <strong className="val-negative">{summary.neg}</strong>
                    </span>
                    <span>
                        Breadth: <strong style={{ color: breadth >= 50 ? 'var(--status-buy)' : 'var(--status-sell)' }}>
                            {breadth}%
                        </strong>
                    </span>
                </div>
            </div>

            {/* Heatmap Grid */}
            <div className="heatmap-container" style={{
                gridTemplateColumns: 'repeat(auto-fill, minmax(72px, 1fr))',
                gap: '3px',
                maxHeight: '70vh',
                overflowY: 'auto',
            }}>
                {data.map((item, idx) => (
                    <div
                        key={idx}
                        className="heat-card"
                        style={{
                            backgroundColor: getColor(item.changePercent),
                            aspectRatio: '1.2',
                            padding: '0.25rem',
                        }}
                        title={`${item.ticker}: ₹${item.ltp} (${item.changePercent > 0 ? '+' : ''}${item.changePercent}%)`}
                    >
                        <span className="ticker" style={{ fontSize: '0.6rem', lineHeight: 1.2 }}>
                            {item.ticker}
                        </span>
                        <span className="change" style={{ fontSize: '0.6rem' }}>
                            {item.changePercent > 0 ? '+' : ''}{item.changePercent}%
                        </span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default Heatmap;
