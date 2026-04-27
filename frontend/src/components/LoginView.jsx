import { useState } from 'react';
import { useAuth } from '../AuthContext';

const LoginView = () => {
    const { login } = useAuth();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);

    const onSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setBusy(true);
        try {
            await login(username, password);
        } catch (err) {
            setError(err.message || 'Login failed');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'radial-gradient(ellipse at center, #1a1a2e 0%, #0a0a14 100%)',
        }}>
            <form onSubmit={onSubmit} className="glass" style={{
                padding: '2.5rem',
                width: '100%',
                maxWidth: 380,
                display: 'flex',
                flexDirection: 'column',
                gap: '1rem',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="url(#login-grad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <defs>
                            <linearGradient id="login-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                                <stop offset="0%" style={{ stopColor: '#0ff' }} />
                                <stop offset="100%" style={{ stopColor: '#f0f' }} />
                            </linearGradient>
                        </defs>
                        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
                    </svg>
                    <h2 style={{ margin: 0 }}>Spectre</h2>
                </div>

                <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Username</label>
                <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    autoFocus
                    required
                    style={{
                        padding: '0.6rem 0.75rem',
                        background: 'rgba(0,0,0,0.4)',
                        border: '1px solid rgba(255,255,255,0.15)',
                        borderRadius: 4,
                        color: 'var(--text)',
                        fontSize: '0.95rem',
                    }}
                />

                <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Password</label>
                <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="current-password"
                    required
                    style={{
                        padding: '0.6rem 0.75rem',
                        background: 'rgba(0,0,0,0.4)',
                        border: '1px solid rgba(255,255,255,0.15)',
                        borderRadius: 4,
                        color: 'var(--text)',
                        fontSize: '0.95rem',
                    }}
                />

                {error && (
                    <div style={{ color: 'var(--accent-sell, #f44)', fontSize: '0.85rem', padding: '0.5rem 0' }}>
                        {error}
                    </div>
                )}

                <button
                    type="submit"
                    disabled={busy}
                    className="nav-tab"
                    style={{
                        marginTop: '0.5rem',
                        padding: '0.7rem',
                        fontSize: '0.95rem',
                        fontWeight: 'bold',
                        background: busy ? 'rgba(0,255,255,0.1)' : 'linear-gradient(90deg, #0ff, #f0f)',
                        color: busy ? 'var(--text-muted)' : '#000',
                        cursor: busy ? 'wait' : 'pointer',
                        border: 'none',
                    }}
                >
                    {busy ? 'Signing in…' : 'Sign in'}
                </button>
            </form>
        </div>
    );
};

export default LoginView;
