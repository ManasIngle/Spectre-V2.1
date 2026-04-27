import { useEffect, useState } from 'react';
import { useAuth } from '../AuthContext';

const UsersAdminView = ({ onClose }) => {
    const { user: currentUser } = useAuth();
    const [users, setUsers] = useState([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    const [newUsername, setNewUsername] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [newRole, setNewRole] = useState('user');

    const fetchUsers = async () => {
        try {
            const res = await fetch('/api/auth/users', { credentials: 'same-origin' });
            const json = await res.json();
            if (res.ok) setUsers(json.users || []);
            else setError(json.error || 'Failed to load users');
        } catch (e) {
            setError(e.message);
        }
    };

    useEffect(() => { fetchUsers(); }, []);

    const onCreate = async (e) => {
        e.preventDefault();
        setError('');
        setBusy(true);
        try {
            const res = await fetch('/api/auth/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ username: newUsername, password: newPassword, role: newRole }),
            });
            const json = await res.json();
            if (!res.ok) throw new Error(json.error || 'Create failed');
            setNewUsername('');
            setNewPassword('');
            setNewRole('user');
            await fetchUsers();
        } catch (err) {
            setError(err.message);
        } finally {
            setBusy(false);
        }
    };

    const onDelete = async (username) => {
        if (!confirm(`Delete user "${username}"?`)) return;
        setError('');
        try {
            const res = await fetch(`/api/auth/users/${encodeURIComponent(username)}`, {
                method: 'DELETE', credentials: 'same-origin',
            });
            const json = await res.json();
            if (!res.ok) throw new Error(json.error || 'Delete failed');
            await fetchUsers();
        } catch (err) {
            setError(err.message);
        }
    };

    return (
        <div style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }} onClick={onClose}>
            <div className="glass" style={{
                padding: '2rem', maxWidth: 720, width: '90%',
                maxHeight: '90vh', overflow: 'auto',
            }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h2 style={{ margin: 0 }}>User Management</h2>
                    <button className="nav-tab" onClick={onClose}>Close</button>
                </div>

                {/* Existing users */}
                <h3 style={{ fontSize: '0.95rem', color: 'var(--text-muted)' }}>Existing users</h3>
                <div className="table-container" style={{ marginBottom: '1.5rem' }}>
                    <table>
                        <thead>
                            <tr>
                                <th>Username</th>
                                <th>Role</th>
                                <th>Created</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {users.map((u) => (
                                <tr key={u.username}>
                                    <td>{u.username}{u.username === currentUser ? ' (you)' : ''}</td>
                                    <td>
                                        <span className={`signal-badge ${u.role === 'admin' ? 'sig-buy' : 'sig-neutral'}`}>
                                            {u.role}
                                        </span>
                                    </td>
                                    <td style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                                        {u.created_at ? u.created_at.slice(0, 10) : '—'}
                                    </td>
                                    <td>
                                        {u.username !== currentUser && (
                                            <button
                                                className="nav-tab"
                                                onClick={() => onDelete(u.username)}
                                                style={{ fontSize: '0.8rem', padding: '0.25rem 0.5rem' }}
                                            >Delete</button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                {/* Create new */}
                <h3 style={{ fontSize: '0.95rem', color: 'var(--text-muted)' }}>Add new user</h3>
                <form onSubmit={onCreate} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 120px auto', gap: '0.5rem', alignItems: 'center' }}>
                    <input
                        type="text"
                        placeholder="Username"
                        value={newUsername}
                        onChange={(e) => setNewUsername(e.target.value)}
                        required
                        style={inputStyle}
                    />
                    <input
                        type="password"
                        placeholder="Password (≥6 chars)"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        required
                        minLength={6}
                        style={inputStyle}
                    />
                    <select className="dropdown" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                    </select>
                    <button type="submit" disabled={busy} className="nav-tab">
                        {busy ? 'Creating…' : 'Create'}
                    </button>
                </form>

                {error && (
                    <div style={{ color: 'var(--accent-sell, #f44)', marginTop: '1rem', fontSize: '0.9rem' }}>
                        {error}
                    </div>
                )}
            </div>
        </div>
    );
};

const inputStyle = {
    padding: '0.5rem 0.75rem',
    background: 'rgba(0,0,0,0.4)',
    border: '1px solid rgba(255,255,255,0.15)',
    borderRadius: 4,
    color: 'var(--text)',
    fontSize: '0.9rem',
};

export default UsersAdminView;
