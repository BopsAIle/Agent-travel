import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { API_BASE, readError } from '../api';

const TOKEN_KEY = 'travel-agent-token';
const USER_KEY = 'travel-agent-user';

const AuthContext = createContext(null);

function loadStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || '');
  const [user, setUser] = useState(loadStoredUser);
  const [ready, setReady] = useState(!localStorage.getItem(TOKEN_KEY));

  const persist = (nextToken, nextUser) => {
    setToken(nextToken || '');
    setUser(nextUser);
    if (nextToken) localStorage.setItem(TOKEN_KEY, nextToken);
    else localStorage.removeItem(TOKEN_KEY);
    if (nextUser) localStorage.setItem(USER_KEY, JSON.stringify(nextUser));
    else localStorage.removeItem(USER_KEY);
  };

  const logout = () => persist('', null);

  const authHeaders = () => (token ? { Authorization: `Bearer ${token}` } : {});

  const authenticate = async (path, email, password) => {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const data = await response.json();
    persist(data.access_token, { user_id: data.user_id, email: data.email });
    return data;
  };

  const login = (email, password) => authenticate('/auth/login', email, password);
  const register = (email, password) => authenticate('/auth/register', email, password);

  useEffect(() => {
    if (!token) {
      setReady(true);
      return;
    }
    let cancelled = false;
    fetch(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => {
        if (!response.ok) throw new Error('invalid');
        return response.json();
      })
      .then((data) => {
        if (!cancelled) persist(token, { user_id: data.user_id, email: data.email });
      })
      .catch(() => {
        if (!cancelled) logout();
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo(
    () => ({ token, user, ready, login, register, logout, authHeaders }),
    [token, user, ready]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
