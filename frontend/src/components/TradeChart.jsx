import { useMemo, useState } from 'react';

/**
 * Reusable line chart for the Trade Journal. Inline SVG, no chart library.
 *
 * Props:
 *   data:     [{ t: 'HH:MM:SS', value: number, phase?: 'before'|'during'|'after' }]
 *   lines:    [{ value: number, label: string, color: string, dashed?: boolean }]
 *   markers:  [{ t: 'HH:MM:SS', label: string, type: 'entry'|'exit'|'best' }]
 *   width:    number (default 700)
 *   height:   number (default 220)
 *   yLabel:   string
 *   yFormat:  (n) => string
 */
const TradeChart = ({
    data = [],
    lines = [],
    markers = [],
    width = 700,
    height = 220,
    yLabel = '',
    yFormat = (n) => n.toFixed(2),
}) => {
    const [hover, setHover] = useState(null);

    const chart = useMemo(() => {
        if (!data || data.length === 0) return null;
        const padL = 55, padR = 16, padT = 12, padB = 28;
        const innerW = width - padL - padR;
        const innerH = height - padT - padB;

        const values = data.map(d => d.value).filter(v => v != null && !isNaN(v));
        const lineVals = lines.map(l => l.value).filter(v => v != null);
        const allVals = [...values, ...lineVals];
        if (allVals.length === 0) return null;
        const minV = Math.min(...allVals);
        const maxV = Math.max(...allVals);
        const span = maxV - minV || 1;
        // Pad y-range a bit so threshold lines aren't on the edge
        const pad = span * 0.08;
        const y0 = minV - pad, y1 = maxV + pad;
        const yRange = y1 - y0;

        const xFor = (i) => padL + (i / Math.max(1, data.length - 1)) * innerW;
        const yFor = (v) => padT + innerH - ((v - y0) / yRange) * innerH;

        // Build path with phase-coloured segments
        const points = data.map((d, i) => ({
            x: xFor(i), y: yFor(d.value), phase: d.phase || 'during', t: d.t, value: d.value,
        }));

        // Single path (we'll colour markers per phase)
        const pathD = points.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');

        // Y-axis ticks
        const ticks = [];
        for (let i = 0; i <= 4; i++) {
            const v = y0 + (yRange * i) / 4;
            ticks.push({ value: v, y: yFor(v) });
        }

        // X-axis time labels (first, ~middle, last)
        const xLabels = [];
        if (data.length > 0) {
            xLabels.push({ x: xFor(0), label: data[0].t.slice(0, 5) });
            if (data.length > 4) {
                const mid = Math.floor(data.length / 2);
                xLabels.push({ x: xFor(mid), label: data[mid].t.slice(0, 5) });
            }
            xLabels.push({ x: xFor(data.length - 1), label: data[data.length - 1].t.slice(0, 5) });
        }

        // Resolve markers
        const tIdx = (t) => data.findIndex(d => d.t === t);
        const resolvedMarkers = markers.map(m => {
            const i = tIdx(m.t);
            if (i < 0) return null;
            return { ...m, x: xFor(i), y: yFor(data[i].value) };
        }).filter(Boolean);

        return {
            points, pathD, ticks, xLabels, resolvedMarkers,
            yFor, padL, padR, padT, padB, innerW, innerH, y0, y1,
        };
    }, [data, lines, markers, width, height]);

    if (!chart) {
        return (
            <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
                No data to chart.
            </div>
        );
    }

    const phaseColor = {
        before: 'rgba(150,150,150,0.5)',
        during: '#0ff',
        after: 'rgba(255,255,255,0.35)',
    };

    const markerColor = {
        entry: '#0f0',
        exit: '#f80',
        best: '#ff0',
    };

    const onMove = (e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const idx = Math.round(((x - chart.padL) / chart.innerW) * (data.length - 1));
        if (idx < 0 || idx >= data.length) {
            setHover(null);
            return;
        }
        setHover({ idx, ...chart.points[idx] });
    };

    return (
        <svg
            width={width}
            height={height}
            style={{ background: 'rgba(0,0,0,0.18)', borderRadius: 6 }}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
        >
            {/* Y grid + labels */}
            {chart.ticks.map((t, i) => (
                <g key={i}>
                    <line
                        x1={chart.padL} x2={width - chart.padR}
                        y1={t.y} y2={t.y}
                        stroke="rgba(255,255,255,0.06)" strokeWidth="1"
                    />
                    <text x={chart.padL - 6} y={t.y + 3} textAnchor="end" fontSize="10" fill="var(--text-muted)">
                        {yFormat(t.value)}
                    </text>
                </g>
            ))}
            {/* Y-axis label */}
            {yLabel && (
                <text x={10} y={chart.padT + chart.innerH / 2} fontSize="10" fill="var(--text-muted)"
                      transform={`rotate(-90 10 ${chart.padT + chart.innerH / 2})`}>
                    {yLabel}
                </text>
            )}
            {/* X labels */}
            {chart.xLabels.map((x, i) => (
                <text key={i} x={x.x} y={height - 8} textAnchor="middle" fontSize="10" fill="var(--text-muted)">
                    {x.label}
                </text>
            ))}
            {/* Threshold lines */}
            {lines.map((ln, i) => {
                const y = chart.yFor(ln.value);
                return (
                    <g key={i}>
                        <line
                            x1={chart.padL} x2={width - chart.padR}
                            y1={y} y2={y}
                            stroke={ln.color} strokeWidth="1.2"
                            strokeDasharray={ln.dashed === false ? '' : '4 3'}
                            opacity="0.85"
                        />
                        <text
                            x={width - chart.padR - 4} y={y - 3}
                            textAnchor="end" fontSize="10" fill={ln.color}
                            opacity="0.95"
                        >
                            {ln.label} {yFormat(ln.value)}
                        </text>
                    </g>
                );
            })}
            {/* Main line — single path, then phase-coloured points overlaid */}
            <path d={chart.pathD} fill="none" stroke="rgba(255,255,255,0.55)" strokeWidth="1.4" />
            {chart.points.map((p, i) => (
                <circle
                    key={i} cx={p.x} cy={p.y} r="1.6"
                    fill={phaseColor[p.phase]}
                />
            ))}
            {/* Entry/Exit/Best markers */}
            {chart.resolvedMarkers.map((m, i) => (
                <g key={i}>
                    <line
                        x1={m.x} x2={m.x}
                        y1={chart.padT} y2={height - chart.padB}
                        stroke={markerColor[m.type] || '#fff'}
                        strokeWidth="1" strokeDasharray="3 3" opacity="0.6"
                    />
                    <circle cx={m.x} cy={m.y} r="4" fill={markerColor[m.type] || '#fff'} stroke="#000" strokeWidth="1" />
                    <text
                        x={m.x + 6} y={chart.padT + 12}
                        fontSize="10" fill={markerColor[m.type] || '#fff'}
                        fontWeight="bold"
                    >
                        {m.label}
                    </text>
                </g>
            ))}
            {/* Hover tooltip */}
            {hover && (
                <g>
                    <line
                        x1={hover.x} x2={hover.x}
                        y1={chart.padT} y2={height - chart.padB}
                        stroke="rgba(255,255,255,0.3)" strokeWidth="1"
                    />
                    <rect
                        x={Math.min(hover.x + 8, width - 110)}
                        y={chart.padT + 4}
                        width="100" height="32"
                        fill="rgba(0,0,0,0.85)" rx="3" stroke="rgba(255,255,255,0.2)"
                    />
                    <text
                        x={Math.min(hover.x + 14, width - 104)}
                        y={chart.padT + 18}
                        fontSize="10" fill="#0ff"
                    >
                        {hover.t}
                    </text>
                    <text
                        x={Math.min(hover.x + 14, width - 104)}
                        y={chart.padT + 30}
                        fontSize="11" fill="#fff"
                    >
                        {yFormat(hover.value)}
                    </text>
                </g>
            )}
        </svg>
    );
};

export default TradeChart;
