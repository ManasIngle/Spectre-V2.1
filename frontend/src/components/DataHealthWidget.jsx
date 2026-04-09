import React, { useState, useEffect } from 'react';

const DataHealthWidget = () => {
    const [health, setHealth] = useState(null);

    useEffect(() => {
        const check = async () => {
            try {
                const res = await fetch('/api/health');
                if (res.ok) {
                    setHealth(await res.json());
                } else {
                    setHealth({ status: 'OFFLINE' });
                }
            } catch {
                setHealth({ status: 'OFFLINE' });
            }
        };
        check();
        const id = setInterval(check, 60000);
        return () => clearInterval(id);
    }, []);

    const isOnline = health?.status === 'ONLINE';
    const failCount = health?.failing_count || 0;

    return (
        <div className="health-widget glass" style={{ padding: '0.4rem 0.8rem', borderRadius: 'var(--radius-md)', gap: '0.5rem' }}>
            <span className={`health-dot ${isOnline ? 'online' : 'offline'}`}></span>
            <span style={{ fontSize: '0.8rem' }}>
                {!health ? 'Connecting...' :
                    isOnline ? (
                        failCount > 0
                            ? `Online (${failCount} streams failing)`
                            : `Online (${health.online || 0} streams)`
                    ) : 'Offline'
                }
            </span>
        </div>
    );
};

export default DataHealthWidget;
