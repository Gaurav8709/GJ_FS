import { useState, useEffect, useRef } from 'react';
import { getCameraStatus } from '../api/api.js';
import './StatsBar.css';

/* Animated number component */
function AnimatedNumber({ value }) {
  const [display, setDisplay] = useState(0);
  const ref = useRef(null);

  useEffect(() => {
    const target = Number(value) || 0;
    const start = display;
    const diff = target - start;
    if (diff === 0) return;
    const duration = 600;
    const startTime = performance.now();

    const step = (now) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const ease = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      setDisplay(Math.round(start + diff * ease));
      if (progress < 1) ref.current = requestAnimationFrame(step);
    };

    ref.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(ref.current);
  }, [value]);

  return <span className="stat-number">{display}</span>;
}

export default function StatsBar({ cameras, alerts }) {
  const [stats, setStats] = useState({
    online: 0, total: 0, detected: 0, workers: 0,
  });

  /* Poll camera status every 5 seconds */
  useEffect(() => {
    const fetchStats = () => {
      getCameraStatus()
        .then((data) => {
          const statuses = Array.isArray(data) ? data : data.cameras || [];
          const online = statuses.filter((c) => c.status === 'online' || c.is_online).length;
          const detected = statuses.reduce((sum, c) => sum + (c.person_count || c.detected || 0), 0);
          const workers = data.workers_on_duty ?? data.active_workers ?? 0;
          setStats({
            online,
            total: statuses.length || cameras?.length || 0,
            detected,
            workers,
          });
        })
        .catch(() => {
          // Use props fallback
          const online = (cameras || []).filter((c) => c.status !== 'offline').length;
          setStats({
            online,
            total: cameras?.length || 0,
            detected: 0,
            workers: 0,
          });
        });
    };

    fetchStats();
    const timer = setInterval(fetchStats, 5000);
    return () => clearInterval(timer);
  }, [cameras]);

  const activeAlerts = (alerts || []).filter((a) => !a.acknowledged).length;

  const items = [
    {
      label: 'Monitored Zones',
      value: stats.total,
      color: 'blue',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
          <line x1="3" y1="9" x2="21" y2="9" />
          <line x1="9" y1="21" x2="9" y2="9" />
        </svg>
      ),
    },
    {
      label: 'Persons Detected',
      value: stats.detected,
      color: 'blue',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
        </svg>
      ),
    },
    {
      label: 'Active Alerts',
      value: activeAlerts,
      color: activeAlerts > 0 ? 'red' : 'green',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
      ),
    },
    {
      label: 'Workers On Duty',
      value: stats.workers,
      color: 'purple',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="8.5" cy="7" r="4" />
          <line x1="20" y1="8" x2="20" y2="14" /><line x1="23" y1="11" x2="17" y2="11" />
        </svg>
      ),
    },
  ];

  return (
    <div className="stats-bar">
      {items.map((item) => (
        <div key={item.label} className={`stat-card stat-card--${item.color}`}>
          <div className="stat-icon">{item.icon}</div>
          <div className="stat-info">
            <div className="stat-value">
              <AnimatedNumber value={item.value} />
              {item.suffix && <span className="stat-suffix">{item.suffix}</span>}
            </div>
            <div className="stat-label">{item.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
