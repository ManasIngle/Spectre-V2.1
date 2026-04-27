import React from 'react';

/**
 * Map signal strings to CSS class names for multi-level intensity coloring.
 * Matches the reference image: Sell+++/++/+ are deep red, Buy+++/++/+ are deep green.
 */
const getSignalClass = (signal) => {
    if (!signal || signal === '-' || signal === '---') return 'sig-neutral';
    const s = signal.toString();

    if (s.includes('Buy+++')) return 'sig-buy-3';
    if (s.includes('Buy++')) return 'sig-buy-2';
    if (s.includes('Buy+')) return 'sig-buy-1';
    if (s.includes('Buy')) return 'sig-buy';
    if (s.includes('Sell+++')) return 'sig-sell-3';
    if (s.includes('Sell++')) return 'sig-sell-2';
    if (s.includes('Sell+')) return 'sig-sell-1';
    if (s.includes('Sell')) return 'sig-sell';
    if (s === 'Neutral') return 'sig-neutral';
    return 'sig-neutral';
};

const getStatusClass = (status) => {
    if (!status) return 'sig-neutral';
    if (status.includes('Sell')) return 'sig-sell';
    if (status.includes('Buy')) return 'sig-buy';
    return 'sig-neutral';
};

const COLUMNS = [
    { key: 'VWAP', label: 'VWAP' },
    { key: 'Alligator', label: 'Alligator' },
    { key: 'ST211', label: 'ST 21-1' },
    { key: 'ST142', label: 'ST 14-2' },
    { key: 'ST103', label: 'ST 10-3' },
    { key: 'ADX', label: 'ADX' },
    { key: 'RSI', label: 'RSI' },
    { key: 'MACD', label: 'MACD' },
    { key: 'FRAMA', label: 'FRAMA' },
    { key: 'Vol', label: 'Vol' },
    { key: 'RS', label: 'RS' },
];

const TraderViewTable = ({ data, interval }) => {
    if (!data || data.length === 0) {
        return (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '3rem' }}>
                No data — market may be closed or data source unavailable.
            </div>
        );
    }

    const displayInterval = interval ? interval.replace('m', ' Min') : '3 Min';

    return (
        <div className="table-container glass">
            <table>
                <thead>
                    <tr>
                        <th className="th-status">δ : {displayInterval}</th>
                        <th className="th-script">Script</th>
                        <th>LTP</th>
                        <th>Chng</th>
                        {COLUMNS.map(col => (
                            <th key={col.key}>{col.label}</th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {data.map((row, idx) => (
                        <tr key={idx}>
                            {/* Status */}
                            <td>
                                <span className={`signal-badge ${getStatusClass(row.Status)}`}>
                                    {row.Status || 'Neutral'}
                                </span>
                            </td>
                            {/* Script Name */}
                            <td className="script-name">{row.Script || '—'}</td>
                            {/* LTP */}
                            <td className="ltp-cell">{row.LTP ? row.LTP.toFixed(2) : '—'}</td>
                            {/* Change */}
                            <td className={(row.Chng ?? 0) >= 0 ? 'val-positive' : 'val-negative'}>
                                {row.Chng != null ? `${row.Chng > 0 ? '+' : ''}${row.Chng.toFixed(2)}` : '—'}
                            </td>
                            {/* Indicator Columns */}
                            {COLUMNS.map(col => (
                                <td key={col.key}>
                                    <span className={`signal-badge ${getSignalClass(row[col.key])}`}>
                                        {row[col.key] || '-'}
                                    </span>
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};

export default TraderViewTable;
