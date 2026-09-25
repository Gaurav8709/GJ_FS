import { useState, useEffect, useRef } from 'react';
import { getWsStreamUrl } from '../api/api.js';
import './CameraCard.css';

export default function CameraCard({ camera, onClick, style }) {
  const camId = camera.cam_id || camera.id || camera.camera_id;
  const name = camera.name || `Camera ${camId}`;
  const isOnline = camera.status !== 'offline';
  const personCount = camera.person_count ?? camera.detected ?? 0;
  const hasAlert = camera.has_alert || camera.alert_active;
  
  const [imgError, setImgError] = useState(!isOnline);
  const [isVisible, setIsVisible] = useState(false);
  const canvasRef = useRef(null);
  const wsRef = useRef(null);
  const cardRef = useRef(null);

  // Intersection Observer to only stream when in viewport
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        setIsVisible(entry.isIntersecting);
      },
      { rootMargin: '100px' }
    );
    
    if (cardRef.current) {
      observer.observe(cardRef.current);
    }
    
    return () => observer.disconnect();
  }, []);

  // Highly performant Canvas-based WebSocket Streaming
  useEffect(() => {
    if (!isOnline || !isVisible) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      return;
    }
    
    const wsUrl = getWsStreamUrl(camId, 60, 5); // 5 FPS grid stream
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = async (event) => {
      try {
        setImgError(false);
        const canvas = canvasRef.current;
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d');
        const blob = new Blob([event.data], { type: 'image/jpeg' });
        const bitmap = await createImageBitmap(blob);
        
        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close();
      } catch (err) {
        console.error("Canvas draw error", err);
      }
    };

    ws.onerror = () => {
      setImgError(true);
    };

    return () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
      wsRef.current = null;
    };
  }, [camId, isOnline, isVisible]);

  return (
    <div
      ref={cardRef}
      className={`camera-card ${hasAlert ? 'camera-card--alert' : ''}`}
      onClick={onClick}
      style={style}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick?.()}
    >
      {/* Stream container */}
      <div className="camera-stream">
        {isOnline && !imgError ? (
          <canvas
            ref={canvasRef}
            width={640}
            height={480}
            className="camera-stream-img"
            style={{ objectFit: 'cover', width: '100%', height: '100%' }}
          />
        ) : (
          <div className="camera-offline">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.6 }}>
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
              <line x1="3" y1="9" x2="21" y2="9" />
              <line x1="9" y1="21" x2="9" y2="9" />
            </svg>
            <span>{isOnline ? 'Active' : 'Standby'}</span>
          </div>
        )}

        {/* Overlays */}
        <div className="camera-overlay-top">
          <span className={`camera-status ${isOnline ? 'online' : 'offline'}`}>
            <span className="status-dot-small" />
            {isOnline ? 'LIVE' : 'OFFLINE'}
          </span>
          {hasAlert && (
            <span className="camera-alert-badge">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2L1 21h22L12 2zm0 4l7.53 13H4.47L12 6z" />
              </svg>
              ALERT
            </span>
          )}
        </div>

        {personCount > 0 && (
          <div className="camera-person-badge">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
            </svg>
            {personCount}
          </div>
        )}
      </div>

      {/* Info bar */}
      <div className="camera-info">
        <div className="camera-name">{name} (Detected: {personCount})</div>
        <div className="camera-meta">
          {camera.section_name && <span>{camera.section_name}</span>}
          {camera.floor_name && <span>{camera.floor_name}</span>}
        </div>

      </div>
    </div>
  );
}
