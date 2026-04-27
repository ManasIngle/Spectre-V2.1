import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const AuthContext = createContext({
    user: null,
    role: null,
    loading: true,
    isAdmin: false,
    login: async () => { },
    logout: async () => { },
    refresh: async () => { },
});

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [role, setRole] = useState(null);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        try {
            const res = await fetch('/api/auth/me', { credentials: 'same-origin' });
            const json = await res.json();
            if (json.authenticated) {
                setUser(json.username);
                setRole(json.role);
            } else {
                setUser(null);
                setRole(null);
            }
        } catch (e) {
            setUser(null);
            setRole(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { refresh(); }, [refresh]);

    const login = useCallback(async (username, password) => {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ username, password }),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.error || 'Login failed');
        setUser(json.username);
        setRole(json.role);
        return json;
    }, []);

    const logout = useCallback(async () => {
        await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
        setUser(null);
        setRole(null);
    }, []);

    return (
        <AuthContext.Provider value={{
            user, role, loading,
            isAdmin: role === 'admin',
            login, logout, refresh,
        }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
