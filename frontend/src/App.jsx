import { useState, useEffect } from 'react';
import { getToken, getMe, clearToken } from './api/api.js';
import Login from './pages/Login.jsx';
import Dashboard from './pages/Dashboard.jsx';

export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setChecking(false);
      return;
    }
    getMe()
      .then((u) => setUser(u))
      .catch(() => clearToken())
      .finally(() => setChecking(false));
  }, []);

  const handleLogin = (userData) => setUser(userData);

  const handleLogout = () => {
    clearToken();
    setUser(null);
  };

  if (checking) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100vh', background: '#0a0a0f',
      }}>
        <div style={{
          width: 40, height: 40, border: '3px solid rgba(59,130,246,0.2)',
          borderTopColor: '#3b82f6', borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }} />
      </div>
    );
  }

  if (!user) return <Login onLogin={handleLogin} />;
  return <Dashboard user={user} onLogout={handleLogout} />;
}
