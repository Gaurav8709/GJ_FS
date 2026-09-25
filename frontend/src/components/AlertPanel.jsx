import { acknowledgeAlert } from '../api/api.js';
import './AlertPanel.css';

export default function AlertPanel({ alerts, setAlerts, setAlertCount, fullPage = false }) {
  const handleAcknowledge = async (id) => {
    try {
      await acknowledgeAlert(id);
      setAlerts(prev => prev.map(a => a.id === id ? { ...a, acknowledged: true } : a));
      setAlertCount(prev => Math.max(0, prev - 1));
    } catch (err) {
      console.error('Failed to acknowledge alert:', err);
    }
  };

  const unacknowledgedCount = alerts.filter(a => !a.acknowledged).length;

  return (
    <div className={`alert-panel ${fullPage ? 'full-page' : ''}`}>
      <div className="alert-header">
        <h2>Notifications {unacknowledgedCount > 0 && <span className="alert-count-badge">{unacknowledgedCount}</span>}</h2>
      </div>

      <div className="alert-list">
        {alerts.length === 0 ? (
          <div className="alert-empty">No alerts found.</div>
        ) : (
          alerts.map(alert => {
            const isUnack = !alert.acknowledged;
            
            // Map severity to color and icon
            let severityClass = 'info';
            let icon = (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
            );

            if (alert.severity === 'high' || alert.severity === 'critical') {
              severityClass = 'high';
              icon = (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              );
            } else if (alert.severity === 'medium') {
              severityClass = 'medium';
              icon = (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                </svg>
              );
            }

            return (
              <div key={alert.id} className={`alert-card ${severityClass} ${isUnack ? 'unacknowledged' : ''}`}>
                <div className="alert-icon">
                  {icon}
                </div>
                <div className="alert-content">
                  <div className="alert-meta">
                    <span className="alert-type">{alert.alert_type.replace('_', ' ')}</span>
                    <span className="alert-time">{new Date(alert.timestamp).toLocaleString()}</span>
                  </div>
                  <div className="alert-message">{alert.message}</div>
                  <div className="alert-location">
                    <span>Camera: {alert.camera_id}</span>
                  </div>
                </div>
                {isUnack && (
                  <button 
                    className="alert-ack-btn" 
                    onClick={() => handleAcknowledge(alert.id)}
                    title="Mark as read"
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
