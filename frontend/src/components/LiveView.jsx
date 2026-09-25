import { useState, useEffect, useRef } from 'react';
import { getVideoUrl, getZones, acknowledgeAlert } from '../api/api.js';
import ZoneOverlay from './ZoneOverlay.jsx';
import './LiveView.css';

export default function LiveView({ camera, onBack }) {
  const [zones, setZones] = useState([]);
  const [showZones, setShowZones] = useState(true);
  const [imgError, setImgError] = useState(false);
  const containerRef = useRef(null);
  const imgRef = useRef(null);
  const wsRef = useRef(null);

  const camId = camera.cam_id || camera.id || camera.camera_id;
  const isOnline = camera.status !== 'offline';

  useEffect(() => {
    getZones(camId)
      .then(setZones)
      .catch(console.error);
  }, [camId]);

  return (
    <div className="live-view">
      <div className="live-view-header">
        <div className="live-header-left">
          <button className="back-btn" onClick={onBack} title="Back to Grid">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>
          <h2>{camera.name || `Camera ${camId}`}</h2>
          <span className={`status-badge ${isOnline ? 'online' : 'offline'}`}>
            {isOnline ? 'ONLINE' : 'OFFLINE'}
          </span>
        </div>
        <div className="live-header-right">
          <label className="toggle-switch">
            <input 
              type="checkbox" 
              checked={showZones} 
              onChange={(e) => setShowZones(e.target.checked)} 
            />
            <span className="slider round"></span>
          </label>
          <span className="toggle-label">Show Zones</span>
        </div>
      </div>

      <div className="stream-container" ref={containerRef}>
        <div className="stream-wrapper">
          {isOnline && !imgError ? (
            <img 
              ref={imgRef}
              src={getVideoUrl(camId, 80, showZones)}
              alt={`Live view from ${camera.name}`}
              className="stream-video"
              crossOrigin="anonymous"
              onError={() => setImgError(true)}
            />
          ) : (
            <div className="stream-placeholder">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="offline-icon">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <line x1="3" y1="9" x2="21" y2="9" />
                <line x1="9" y1="21" x2="9" y2="9" />
              </svg>
              <p>Zone Monitoring Mode</p>
            </div>
          )}

          {showZones && zones.length > 0 && (
            <ZoneOverlay zones={zones} />
          )}
        </div>
      </div>
      
      <div className="live-details">
        <div className="detail-card">
          <h3>Camera Info</h3>
          <p><strong>ID:</strong> {camId}</p>
          <p><strong>Resolution:</strong> {camera.resolution || '1080p'}</p>
          <p><strong>FPS:</strong> {camera.fps || '30'}</p>
        </div>
        <div className="detail-card">
          <h3>Location</h3>
          <p><strong>Floor:</strong> {camera.floor_name || 'N/A'}</p>
          <p><strong>Section:</strong> {camera.section_name || 'N/A'}</p>
        </div>
      </div>
    </div>
  );
}
