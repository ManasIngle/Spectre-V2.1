import React, { useState, useEffect, useCallback } from 'react';

const dirColor = d =>
    d === 'UP'   ? '#10b981' :
    d === 'DOWN' ? '#ef4444' : '#94a3b8';

const magColor = m =>
    m === 'LARGE'  ? '#f59e0b' :
    m === 'MEDIUM' ? '#fb923c' :
    m === 'SMALL'  ? '#60a5fa' : '#94a3b8';

const confBand = c =>
    c >= 0.60 ? { label: 'HIGH', color: '#10b981' } :
    c >= 0.55 ? { label: 'MODERATE', color: '#f59e0b' } :
    c >= 0.50 ? { label: 'LOW-MOD', color: '#fb923c' } :
                { label: 'LOW', color: '#ef4444' };

const fmtClose = v => v != null ? `₹${Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
const fmtPct   = v => v != null ? `${v > 0 ? '+' : ''}${Number(v).toFixed(3)}%` : '—';
const fmtConf  = v => v != null ? `${(v * 100).toFixed(1)}%` : '—';

/* ────────────────────────── Mini probability bar ────────────────── */
const ProbBar = ({ label, prob, color }) => {
    const pct = prob != null ? Math.min(Math.max(prob * 100, 0), 100) : 0;
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', minWidth: 36 }}>{label}</span>
            <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.5s ease' }} />
            </div>
            <span style={{ fontSize: '0.68rem', fontWeight: 700, color, minWidth: 38, textAlign: 'right' }}>
                {prob != null ? `${pct.toFixed(1)}%` : '—'}
            </span>
        </div>
    );
};

/* ────────────────────────── Prediction card ─────────────────────── */
const PredictionCard = ({ data }) => {
    if (!data) return (
        <div className="cpanel">
            <div className="cpanel-header">Overnight Nifty Prediction</div>
            <div className="cpanel-body" style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Loading…</div>
        </div>
    );

    const dc   = dirColor(data.direction);
    const band = confBand(data.direction_confidence);

    return (
        <div className="cpanel" style={{ borderTop: `3px solid ${dc}` }}>
            <div className="cpanel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>Overnight Nifty Prediction</span>
                <span style={{ fontSize: '0.58rem', color: 'var(--text-muted)', fontWeight: 400 }}>
                    v{data.model_version} · data as of {data.asof_session}
                </span>
            </div>
            <div className="cpanel-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>

                {/* Direction + confidence */}
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'stretch' }}>
                    <div style={{
                        flex: 1, textAlign: 'center',
                        background: `${dc}10`, border: `1px solid ${dc}28`,
                        borderRadius: 8, padding: '0.75rem 0.5rem',
                    }}>
                        <div style={{ fontSize: '0.58rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
                            Direction
                        </div>
                        <div style={{ fontSize: '2rem', fontWeight: 800, color: dc, fontFamily: 'var(--font-display)', lineHeight: 1 }}>
                            {data.direction || '—'}
                        </div>
                        <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: 4 }}>
                            Target: {data.target_date}
                        </div>
                    </div>

                    <div style={{
                        flex: 1, textAlign: 'center',
                        background: `${band.color}10`, border: `1px solid ${band.color}28`,
                        borderRadius: 8, padding: '0.75rem 0.5rem',
                    }}>
                        <div style={{ fontSize: '0.58rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
                            Confidence
                        </div>
                        <div style={{ fontSize: '2rem', fontWeight: 800, color: band.color, fontFamily: 'var(--font-display)', lineHeight: 1 }}>
                            {fmtConf(data.direction_confidence)}
                        </div>
                        <div style={{
                            display: 'inline-block', marginTop: 6,
                            padding: '0.15rem 0.55rem', borderRadius: 20,
                            fontSize: '0.6rem', fontWeight: 700,
                            background: `${band.color}18`, border: `1px solid ${band.color}30`, color: band.color,
                        }}>
                            {band.label}
                        </div>
                    </div>
                </div>

                {/* Price levels */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem' }}>
                    {[
                        { label: 'Prev Close',  value: fmtClose(data.prev_close),      color: 'var(--text-secondary)' },
                        { label: 'Pred Close',  value: fmtClose(data.predicted_close), color: dc },
                        { label: 'Change',      value: fmtPct(data.predicted_change_pct), color: dc },
                    ].map(({ label, value, color }) => (
                        <div key={label} style={{
                            background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-color)',
                            borderRadius: 6, padding: '0.4rem', textAlign: 'center',
                        }}>
                            <div style={{ fontSize: '0.56rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
                            <div style={{ fontSize: '0.82rem', fontWeight: 700, color, marginTop: 2 }}>{value}</div>
                        </div>
                    ))}
                </div>

                {/* Magnitude */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>Magnitude:</span>
                    <span style={{
                        padding: '0.2rem 0.6rem', borderRadius: 20, fontSize: '0.68rem', fontWeight: 700,
                        background: `${magColor(data.magnitude_bucket)}18`,
                        border: `1px solid ${magColor(data.magnitude_bucket)}30`,
                        color: magColor(data.magnitude_bucket),
                    }}>
                        {data.magnitude_bucket || '—'} ({fmtPct(data.abs_change_pct)} abs)
                    </span>
                </div>

                {/* Probability bars */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    <ProbBar label="UP"   prob={data.direction_probs?.UP}   color="#10b981" />
                    <ProbBar label="FLAT" prob={data.direction_probs?.FLAT} color="#94a3b8" />
                    <ProbBar label="DOWN" prob={data.direction_probs?.DOWN} color="#ef4444" />
                </div>

                {/* Advisory footer */}
                <div style={{
                    fontSize: '0.6rem', color: 'var(--text-muted)', textAlign: 'center',
                    paddingTop: '0.4rem', borderTop: '1px solid var(--border-color)',
                    lineHeight: 1.4,
                }}>
                    Advisory only · trade at confidence ≥ 55% · generated daily at 03:30 IST
                </div>
            </div>
        </div>
    );
};

/* ────────────────────────── History table ───────────────────────── */
const HistoryTable = ({ rows }) => {
    if (!rows || rows.length === 0) return (
        <div className="cpanel">
            <div className="cpanel-header">Prediction History</div>
            <div className="cpanel-body" style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No history yet.</div>
        </div>
    );

    const sorted = [...rows].sort((a, b) => b.target_date.localeCompare(a.target_date));

    return (
        <div className="cpanel">
            <div className="cpanel-header">Prediction History (last {rows.length})</div>
            <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.68rem' }}>
                    <thead>
                        <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                            {['Target', 'Dir', 'Conf', 'Pred ₹', 'Actual ₹', 'Err%', 'Correct?', 'Mag'].map(h => (
                                <th key={h} style={{ padding: '0.35rem 0.5rem', color: 'var(--text-muted)', fontWeight: 700, textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {sorted.map(row => {
                            const dc = dirColor(row.direction);
                            const correct = row.direction_correct;
                            return (
                                <tr key={row.target_date} style={{ borderBottom: '1px solid rgba(42,49,67,0.4)' }}>
                                    <td style={{ padding: '0.3rem 0.5rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{row.target_date}</td>
                                    <td style={{ padding: '0.3rem 0.5rem', fontWeight: 700, color: dc }}>{row.direction}</td>
                                    <td style={{ padding: '0.3rem 0.5rem', color: confBand(row.direction_confidence).color, whiteSpace: 'nowrap' }}>
                                        {fmtConf(row.direction_confidence)}
                                    </td>
                                    <td style={{ padding: '0.3rem 0.5rem', color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>
                                        {fmtClose(row.predicted_close)}
                                    </td>
                                    <td style={{ padding: '0.3rem 0.5rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                                        {row.actual_close != null ? fmtClose(row.actual_close) : <span style={{ color: 'var(--text-muted)' }}>pending</span>}
                                    </td>
                                    <td style={{ padding: '0.3rem 0.5rem', color: row.abs_error_pct != null ? (row.abs_error_pct < 0.5 ? '#10b981' : row.abs_error_pct < 1 ? '#f59e0b' : '#ef4444') : 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                                        {row.abs_error_pct != null ? `${Number(row.abs_error_pct).toFixed(3)}%` : '—'}
                                    </td>
                                    <td style={{ padding: '0.3rem 0.5rem' }}>
                                        {correct === true  ? <span style={{ color: '#10b981', fontWeight: 700 }}>✓</span> :
                                         correct === false ? <span style={{ color: '#ef4444', fontWeight: 700 }}>✗</span> :
                                         <span style={{ color: 'var(--text-muted)' }}>—</span>}
                                    </td>
                                    <td style={{ padding: '0.3rem 0.5rem', color: magColor(row.magnitude_bucket), whiteSpace: 'nowrap' }}>
                                        {row.magnitude_bucket || '—'}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

/* ────────────────────────── Backfill banner ─────────────────────── */
const BackfillBanner = ({ status, busy, onRefresh, onRetry, lastError }) => {
    const inProg = busy || status?.fetch_in_progress;
    const exists = status?.exists;
    const ageHours = status?.age_hours;

    let body;
    if (inProg) {
        body = (
            <>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>Backfilling overnight data…</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Downloading 10 years of cross-asset data (~3 minutes). This page will auto-refresh when done.
                </div>
                {status?.fetch_started_at && (
                    <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: 4 }}>
                        Started {new Date(status.fetch_started_at).toLocaleTimeString()}
                    </div>
                )}
            </>
        );
    } else if (!exists) {
        body = (
            <>
                <div style={{ fontWeight: 700, marginBottom: 4, color: '#ef4444' }}>
                    Overnight data not initialized
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 8 }}>
                    {lastError || 'The raw data file is missing. This usually happens on a fresh deploy before the 03:30 IST cron runs.'}
                </div>
                <button onClick={onRefresh} className="nav-tab" style={{
                    background: 'linear-gradient(90deg, #0ff, #f0f)', color: '#000', fontWeight: 700,
                    padding: '0.4rem 0.9rem', border: 'none',
                }}>Backfill now (~3 min)</button>
            </>
        );
    } else {
        // Has data but stale — give user the option to refresh
        body = (
            <>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Data last refreshed {ageHours != null ? `${ageHours}h ago` : 'unknown'} · auto-refresh at 03:30 IST daily
                </div>
                <button onClick={onRefresh} className="nav-tab" style={{
                    marginTop: 4, padding: '0.25rem 0.6rem', fontSize: '0.75rem',
                }}>Refresh now</button>
                {lastError && (
                    <div style={{ marginTop: 8, color: '#ef4444', fontSize: '0.75rem' }}>
                        Last prediction error: {lastError}
                        <button onClick={onRetry} className="nav-tab" style={{
                            marginLeft: 8, padding: '0.15rem 0.5rem', fontSize: '0.7rem',
                        }}>Retry</button>
                    </div>
                )}
            </>
        );
    }

    const bg = inProg ? 'rgba(0,255,255,0.08)' :
               !exists ? 'rgba(239,68,68,0.1)' :
               'rgba(255,255,255,0.03)';
    const border = inProg ? 'rgba(0,255,255,0.25)' :
                   !exists ? 'rgba(239,68,68,0.2)' :
                   'rgba(255,255,255,0.08)';

    return (
        <div style={{
            padding: '0.75rem 1rem', borderRadius: 8,
            background: bg, border: `1px solid ${border}`,
        }}>
            {body}
        </div>
    );
};

/* ────────────────────────── Main view ───────────────────────────── */
const OvernightView = () => {
    const [pred, setPred]     = useState(null);
    const [log, setLog]       = useState([]);
    const [err, setErr]       = useState(null);
    const [errCode, setErrCode] = useState(null);
    const [status, setStatus] = useState(null);
    const [busy, setBusy]     = useState(false);
    const [lastUpdate, setLastUpdate] = useState(null);

    const fetchAll = useCallback(async () => {
        try {
            const [predRes, logRes, statusRes] = await Promise.all([
                fetch('/api/overnight-prediction').then(r => r.json()),
                fetch('/api/overnight-log?limit=30').then(r => r.json()),
                fetch('/api/overnight-prediction/status').then(r => r.json()).catch(() => null),
            ]);
            setStatus(statusRes);
            setLog(Array.isArray(logRes) ? logRes : []);
            if (predRes.error) {
                setErr(predRes.message || predRes.error);
                setErrCode(predRes.error_code || predRes.error);
                setPred(null);
            } else {
                setPred(predRes);
                setErr(null);
                setErrCode(null);
            }
            setLastUpdate(new Date());
        } catch (e) {
            setErr(e.message);
            setErrCode('fetch_failed');
        }
    }, []);

    useEffect(() => {
        fetchAll();
        const id = setInterval(fetchAll, 10 * 60 * 1000); // background refresh every 10 min
        return () => clearInterval(id);
    }, [fetchAll]);

    // Fast-poll while a fetch is running, so the UI updates as soon as it completes
    useEffect(() => {
        if (!status?.fetch_in_progress && !busy) return;
        const id = setInterval(fetchAll, 8000);
        return () => clearInterval(id);
    }, [status?.fetch_in_progress, busy, fetchAll]);

    const onRefresh = async () => {
        setBusy(true);
        try {
            await fetch('/api/overnight-prediction/refresh', { method: 'POST' });
            await fetchAll();
        } catch (e) {
            setErr(e.message);
        } finally {
            // Don't clear busy until status confirms it's running (fast-poll picks it up)
            setTimeout(() => setBusy(false), 2000);
        }
    };

    const onRetry = () => fetchAll();

    const showBanner = errCode === 'data_missing' || errCode === 'model_not_loaded' ||
                       (status && (!status.exists || status.fetch_in_progress)) ||
                       (status && status.age_hours != null && status.age_hours > 26);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', maxWidth: 900, margin: '0 auto' }}>
            {/* Header row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    Next-day Nifty 50 close prediction · US session cross-asset model
                </div>
                {lastUpdate && (
                    <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>
                        Updated {lastUpdate.toLocaleTimeString()} · refreshes every 10 min
                    </div>
                )}
            </div>

            {showBanner && (
                <BackfillBanner
                    status={status}
                    busy={busy}
                    onRefresh={onRefresh}
                    onRetry={onRetry}
                    lastError={err}
                />
            )}

            {err && !showBanner && (
                <div style={{
                    padding: '0.75rem 1rem', borderRadius: 8,
                    background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)',
                    fontSize: '0.8rem', color: '#ef4444',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                }}>
                    <span>{err}</span>
                    <button onClick={onRetry} className="nav-tab" style={{ padding: '0.2rem 0.6rem', fontSize: '0.75rem' }}>
                        Retry
                    </button>
                </div>
            )}

            {/* Prediction card — only show when we actually have data */}
            {pred && <PredictionCard data={pred} />}

            {/* History table */}
            <HistoryTable rows={log} />
        </div>
    );
};

export default OvernightView;
