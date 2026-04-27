import React, { useState } from 'react';
import MLLogsView from './MLLogsView';
import OptionArrayView from './OptionArrayView';

const SUBTABS = [
    { key: 'ml-logs',      label: 'ML Logs',            csv: '/api/ml-logs/download',         filename: 'system_signals.csv' },
    { key: 'option-array', label: 'Option Price Array', csv: '/api/option-array/download',    filename: 'option_price_array.csv' },
];

const DownloadView = () => {
    const [sub, setSub] = useState('ml-logs');
    const active = SUBTABS.find(t => t.key === sub) || SUBTABS[0];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {/* Header bar: subtabs + download button */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                    {SUBTABS.map(t => (
                        <button
                            key={t.key}
                            onClick={() => setSub(t.key)}
                            className={`nav-tab${sub === t.key ? ' active' : ''}`}
                            style={{ fontSize: '0.78rem' }}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                <a
                    href={active.csv}
                    download={active.filename}
                    style={{
                        padding: '8px 16px',
                        background: 'linear-gradient(45deg, #0d6efd, #0dcaf0)',
                        color: 'white', border: 'none', borderRadius: '4px',
                        cursor: 'pointer', fontWeight: 700, fontSize: '0.78rem',
                        textDecoration: 'none', display: 'inline-block',
                    }}
                >
                    Download {active.filename}
                </a>
            </div>

            {/* Active subtab body */}
            {sub === 'ml-logs' ? <MLLogsView /> : <OptionArrayView />}
        </div>
    );
};

export default DownloadView;
