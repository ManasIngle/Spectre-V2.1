import React, { useState, useEffect, useCallback, useRef } from 'react';

const OITrendingView = () => {
    const [oiData, setOiData] = useState(null);
    const [trending, setTrending] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [activeTab, setActiveTab] = useState('trending'); // Default to trending OI

    const tableContainerRef = useRef(null);
    const atmRowRef = useRef(null);

    const fetchOI = useCallback(async () => {
        try {
            const [chainRes, trendRes] = await Promise.all([
                fetch('/api/oi-chain'),
                fetch('/api/oi-trend'),
            ]);
            const chain = await chainRes.json();
            const trend = await trendRes.json();

            if (chain.error) {
                setError(chain.error);
            } else {
                setOiData(chain);
                setError(null);
            }
            setTrending(trend.snapshots || []);
        } catch (e) {
            setError('Failed to fetch OI data');
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        fetchOI();
        const id = setInterval(fetchOI, 180000); // 3 min
        return () => clearInterval(id);
    }, [fetchOI]);

    useEffect(() => {
        if (activeTab === 'chain' && tableContainerRef.current && atmRowRef.current) {
            const container = tableContainerRef.current;
            const row = atmRowRef.current;
            container.scrollTop = row.offsetTop - (container.clientHeight / 2) + (row.clientHeight / 2);
        }
    }, [activeTab, oiData?.atm_strike]);

    if (loading && !oiData) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                Loading Nifty Option Chain from NSE...
            </div>
        );
    }

    if (error && !oiData) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
                <div style={{ fontSize: '1.5rem' }}>⏳</div>
                <div style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>NSE OI data unavailable</div>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', maxWidth: 420 }}>
                    {error}. NSE rate-limits external IPs — retrying automatically every 3 minutes.
                </div>
                <button
                    onClick={fetchOI}
                    style={{
                        marginTop: '0.5rem', padding: '0.5rem 1.5rem',
                        borderRadius: '8px', border: '1px solid var(--border-color)',
                        background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)',
                        cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600,
                    }}
                >
                    Retry now
                </button>
            </div>
        );
    }

    const strikes = oiData?.strikes || [];
    const atm = oiData?.atm_strike || 0;

    // Process trending data
    const processedTrending = trending.map((snap, idx) => {
        const diff = snap.total_pe_oi_chg - snap.total_ce_oi_chg;
        let chngDir = 0;
        let chngPct = 0;
        if (idx > 0) {
            const prevSnap = trending[idx - 1];
            const prevDiff = prevSnap.total_pe_oi_chg - prevSnap.total_ce_oi_chg;
            chngDir = diff - prevDiff;
            if (prevDiff !== 0) {
                chngPct = (chngDir / Math.abs(prevDiff)) * 100;
            }
        }
        return {
            ...snap,
            diff,
            chngDir,
            chngPct
        };
    }).reverse(); // newest first

    return (
        <div className="glass" style={{ borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
            {/* Tabs Header */}
            <div style={{ display: 'flex', borderBottom: '1px solid var(--border-color)', background: 'rgba(0,0,0,0.1)' }}>
                <button
                    onClick={() => setActiveTab('chain')}
                    style={{
                        padding: '1rem 1.5rem', background: 'transparent', border: 'none',
                        borderBottom: activeTab === 'chain' ? '2px solid var(--status-buy)' : '2px solid transparent',
                        color: activeTab === 'chain' ? 'var(--text-primary)' : 'var(--text-muted)',
                        cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem'
                    }}>
                    Option Chain
                </button>
                <button
                    onClick={() => setActiveTab('trending')}
                    style={{
                        padding: '1rem 1.5rem', background: 'transparent', border: 'none',
                        borderBottom: activeTab === 'trending' ? '2px solid var(--status-buy)' : '2px solid transparent',
                        color: activeTab === 'trending' ? 'var(--text-primary)' : 'var(--text-muted)',
                        cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem'
                    }}>
                    Trending OI
                </button>
            </div>

            {/* Summary Header */}
            <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '0.75rem 1.5rem', borderBottom: '1px solid var(--border-color)',
                flexWrap: 'wrap', gap: '0.75rem',
            }}>
                <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
                    {oiData?.underlying && (
                        <span>Nifty: <strong style={{ color: 'var(--text-primary)' }}>{oiData.underlying}</strong></span>
                    )}
                    {oiData?.expiry && (
                        <span>Expiry: <strong style={{ color: 'var(--text-primary)' }}>{oiData.expiry}</strong></span>
                    )}
                    {oiData?.pcr_oi != null && (
                        <span>PCR (OI): <strong style={{ color: oiData.pcr_oi >= 1 ? 'var(--status-buy)' : 'var(--status-sell)' }}>
                            {oiData.pcr_oi}
                        </strong></span>
                    )}
                    {oiData?.pcr_volume != null && (
                        <span>PCR (Vol): <strong style={{ color: oiData.pcr_volume >= 1 ? 'var(--status-buy)' : 'var(--status-sell)' }}>
                            {oiData.pcr_volume}
                        </strong></span>
                    )}
                    {oiData?.timestamp && (
                        <span style={{ color: 'var(--text-muted)' }}>NSE: {oiData.timestamp}</span>
                    )}
                </div>
            </div>

            {/* Total OI Change Summary */}
            <div style={{
                display: 'flex', justifyContent: 'center', gap: '3rem',
                padding: '0.75rem 1.5rem', borderBottom: '1px solid var(--border-color)',
                fontSize: '0.85rem',
            }}>
                <span>
                    Total CE OI Chg:{' '}
                    <strong style={{ color: oiData?.total_ce_oi_chg > 0 ? 'var(--status-sell)' : 'var(--status-buy)' }}>
                        {(oiData?.total_ce_oi_chg || 0).toLocaleString()}
                    </strong>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginLeft: '0.25rem' }}>
                        (CE ↑ = Bearish)
                    </span>
                </span>
                <span>
                    Total PE OI Chg:{' '}
                    <strong style={{ color: oiData?.total_pe_oi_chg > 0 ? 'var(--status-buy)' : 'var(--status-sell)' }}>
                        {(oiData?.total_pe_oi_chg || 0).toLocaleString()}
                    </strong>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginLeft: '0.25rem' }}>
                        (PE ↑ = Bullish)
                    </span>
                </span>
            </div>

            {/* Trending OI Table Tab */}
            {activeTab === 'trending' && (
                <div className="table-container" style={{ maxHeight: '60vh', overflowY: 'auto', borderRadius: 0, border: 'none' }}>
                    <table style={{ textAlign: 'center' }}>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>LTP</th>
                                <th>Chng. in Call OI</th>
                                <th>Chng. in Put OI</th>
                                <th>Diff. in OI</th>
                                <th>Direct. of chng</th>
                                <th>Chng. in Direction</th>
                                <th>Direction of Chng %</th>
                                <th>PCR</th>
                            </tr>
                        </thead>
                        <tbody>
                            {processedTrending.map((row, idx) => (
                                <tr key={idx}>
                                    <td style={{ color: 'var(--text-muted)' }}>
                                        {row.timestamp ? row.timestamp.split(' ')[1] : new Date(row.time * 1000).toLocaleTimeString()}
                                    </td>
                                    <td>{row.underlying ? row.underlying.toLocaleString() : '-'}</td>
                                    <td style={{ color: '#fca5a5' }}>{(row.total_ce_oi_chg || 0).toLocaleString()}</td>
                                    <td style={{ color: '#6ee7b7' }}>{(row.total_pe_oi_chg || 0).toLocaleString()}</td>
                                    <td style={{ color: row.diff > 0 ? 'var(--status-buy)' : 'var(--status-sell)' }}>
                                        {Math.abs(row.diff).toLocaleString()}
                                    </td>
                                    <td>
                                        {row.chngDir > 0 ? (
                                            <span style={{ display: 'inline-block', background: 'rgba(16,185,129,0.2)', color: 'var(--status-buy)', padding: '2px 6px', borderRadius: '4px' }}>↗</span>
                                        ) : row.chngDir < 0 ? (
                                            <span style={{ display: 'inline-block', background: 'rgba(239,68,68,0.2)', color: 'var(--status-sell)', padding: '2px 6px', borderRadius: '4px' }}>↘</span>
                                        ) : '-'}
                                    </td>
                                    <td style={{ color: row.chngDir > 0 ? 'var(--status-buy)' : 'var(--status-sell)' }}>
                                        {row.chngDir !== 0 ? Math.abs(row.chngDir).toLocaleString() : '-'}
                                    </td>
                                    <td style={{ color: row.chngPct > 0 ? 'var(--status-buy)' : 'var(--status-sell)' }}>
                                        {row.chngPct !== 0 ? Math.abs(row.chngPct).toFixed(2) : '-'}
                                    </td>
                                    <td style={{ color: row.pcr_oi >= 1 ? 'var(--status-buy)' : 'var(--status-sell)' }}>
                                        {(row.pcr_oi || 0).toFixed(2)}
                                    </td>
                                </tr>
                            ))}
                            {processedTrending.length === 0 && (
                                <tr>
                                    <td colSpan={9} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                                        No trending data available yet. Waiting for minimum 2 snapshots.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Option Chain Tab */}
            {activeTab === 'chain' && (
                <div className="table-container" ref={tableContainerRef} style={{ maxHeight: '60vh', overflowY: 'auto', borderRadius: 0, border: 'none' }}>
                    <table>
                        <thead>
                            <tr style={{ position: 'sticky', top: 0, zIndex: 10 }}>
                                <th colSpan={5} style={{ background: 'rgba(239,68,68,0.12)', color: '#fca5a5' }}>CALLS (CE)</th>
                                <th style={{ background: 'rgba(59,130,246,0.15)', color: '#93c5fd' }}>Strike</th>
                                <th colSpan={5} style={{ background: 'rgba(16,185,129,0.12)', color: '#6ee7b7' }}>PUTS (PE)</th>
                            </tr>
                            <tr style={{ position: 'sticky', top: '34px', zIndex: 10 }}>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>OI</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>OI Chg</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>Vol</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>IV</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>LTP</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}></th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>LTP</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>IV</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>Vol</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>OI Chg</th>
                                <th style={{ background: 'rgba(30,30,40,1)' }}>OI</th>
                            </tr>
                        </thead>
                        <tbody>
                            {strikes.map((s, idx) => {
                                const isATM = s.strike === atm;
                                const isITM_CE = s.strike < atm;
                                const isITM_PE = s.strike > atm;

                                return (
                                    <tr
                                        key={idx}
                                        ref={isATM ? atmRowRef : null}
                                        style={isATM ? { background: 'rgba(59,130,246,0.15)', fontWeight: 700 } : {}}
                                    >
                                        {/* CE side */}
                                        <td style={isITM_CE ? { opacity: 0.5 } : {}}>
                                            <OIBar value={s.CE_OI} maxVal={getMaxOI(strikes, 'CE_OI')} side="ce" />
                                        </td>
                                        <td className={s.CE_OI_Chg > 0 ? 'val-negative' : s.CE_OI_Chg < 0 ? 'val-positive' : ''}>
                                            {s.CE_OI_Chg.toLocaleString()}
                                        </td>
                                        <td style={{ color: 'var(--text-muted)' }}>{shortNum(s.CE_Vol)}</td>
                                        <td style={{ color: 'var(--text-muted)' }}>{s.CE_IV || '-'}</td>
                                        <td>{s.CE_LTP || '-'}</td>

                                        {/* Strike */}
                                        <td style={{
                                            fontWeight: 700,
                                            background: isATM ? 'rgba(59,130,246,0.25)' : 'rgba(59,130,246,0.05)',
                                            color: isATM ? '#60a5fa' : 'var(--text-primary)',
                                        }}>
                                            {s.strike}
                                            {isATM && <span style={{ fontSize: '0.6rem', marginLeft: '0.3rem' }}>ATM</span>}
                                        </td>

                                        {/* PE side */}
                                        <td>{s.PE_LTP || '-'}</td>
                                        <td style={{ color: 'var(--text-muted)' }}>{s.PE_IV || '-'}</td>
                                        <td style={{ color: 'var(--text-muted)' }}>{shortNum(s.PE_Vol)}</td>
                                        <td className={s.PE_OI_Chg > 0 ? 'val-positive' : s.PE_OI_Chg < 0 ? 'val-negative' : ''}>
                                            {s.PE_OI_Chg.toLocaleString()}
                                        </td>
                                        <td style={isITM_PE ? { opacity: 0.5 } : {}}>
                                            <OIBar value={s.PE_OI} maxVal={getMaxOI(strikes, 'PE_OI')} side="pe" />
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};


/** Inline OI bar visualization */
const OIBar = ({ value, maxVal, side }) => {
    const pct = maxVal > 0 ? Math.min((value / maxVal) * 100, 100) : 0;
    const color = side === 'ce' ? 'rgba(239,68,68,0.35)' : 'rgba(16,185,129,0.35)';

    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', justifyContent: side === 'ce' ? 'flex-end' : 'flex-start' }}>
            {side === 'ce' && <span style={{ fontSize: '0.7rem', minWidth: '45px', textAlign: 'right' }}>{shortNum(value)}</span>}
            <div style={{
                width: '60px', height: '12px', background: 'rgba(255,255,255,0.04)',
                borderRadius: '2px', overflow: 'hidden',
                display: 'flex', justifyContent: side === 'ce' ? 'flex-end' : 'flex-start',
            }}>
                <div style={{ width: `${pct}%`, background: color, borderRadius: '2px', transition: 'width 0.3s ease' }} />
            </div>
            {side === 'pe' && <span style={{ fontSize: '0.7rem', minWidth: '45px' }}>{shortNum(value)}</span>}
        </div>
    );
};


function getMaxOI(strikes, key) {
    return Math.max(...strikes.map(s => s[key] || 0), 1);
}

function shortNum(n) {
    if (!n) return '0';
    if (n >= 10000000) return (n / 10000000).toFixed(1) + 'Cr';
    if (n >= 100000) return (n / 100000).toFixed(1) + 'L';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
}

export default OITrendingView;
