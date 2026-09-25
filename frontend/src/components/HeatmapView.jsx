import { useState, useEffect, useMemo } from 'react';
import { getLatestHeatmaps, getHeatmapForCamera } from '../api/api.js';
import './HeatmapView.css';

export default function HeatmapView({ cameras }) {
  const [heatmaps, setHeatmaps] = useState([]);
  const [selectedCam, setSelectedCam] = useState('');
  const [activeHeatmap, setActiveHeatmap] = useState(null);
  const [loading, setLoading] = useState(true);
  const [timeFilter, setTimeFilter] = useState('LATEST'); // LATEST, TODAY, HOUR
  const [fullscreenModal, setFullscreenModal] = useState(false);

  const fetchHeatmaps = () => {
    getLatestHeatmaps()
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        setHeatmaps(list);

        // Auto select first camera if none selected
        if (list.length > 0 && !selectedCam) {
          setSelectedCam(list[0].cam_id);
          setActiveHeatmap(list[0]);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchHeatmaps();
    const interval = setInterval(fetchHeatmaps, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (selectedCam) {
      getHeatmapForCamera(selectedCam)
        .then((data) => {
          if (data && data.image_url) {
            setActiveHeatmap(data);
          } else {
            setActiveHeatmap(null);
          }
        })
        .catch(console.error);
    }
  }, [selectedCam]);

  // Selected camera object details
  const currentCamObj = useMemo(() => {
    return (cameras || []).find((c) => c.cam_id === selectedCam) || {
      cam_id: selectedCam || 'cam1',
      name: selectedCam ? selectedCam.toUpperCase() : 'Camera 1',
      section_name: 'Showroom Main Floor'
    };
  }, [cameras, selectedCam]);

  // Density calculations
  const densityVal = activeHeatmap?.peak_density || 0;
  const densityPct = Math.round(densityVal * 100);

  const densityStatus = 
    densityPct > 75 ? { label: 'CRITICAL HOTSPOT', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)' } :
    densityPct > 50 ? { label: 'HIGH TRAFFIC', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' } :
    densityPct > 25 ? { label: 'MODERATE DENSITY', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)' } :
    { label: 'LOW TRAFFIC', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)' };

  const metaInfo = activeHeatmap?.meta_info || {};
  const peakHour = metaInfo.peak_hour || '14:00 - 16:00';
  const topZone = metaInfo.top_zone || 'Main Display Counter';

  return (
    <div className="heatmap-view animate-fade-in">
      {/* Top Header */}
      <div className="heatmap-header">
        <div>
          <div className="header-title-row">
            <h2>Showroom Foot-Traffic Heatmaps</h2>
            <span className="live-stream-badge">
              <span className="pulse-dot green"></span> CV Stream Sync Active
            </span>
          </div>
          <p className="heatmap-subtitle">
            Density heatmaps generated automatically by Computer Vision pipeline tracking customer dwell hotspots across camera feeds.
          </p>
        </div>

        <div className="heatmap-controls">
          <div className="control-box">
            <span className="control-label">SELECT CAMERA:</span>
            <select 
              className="cam-select" 
              value={selectedCam} 
              onChange={(e) => setSelectedCam(e.target.value)}
            >
              <option value="">Choose Showroom Camera</option>
              {(cameras || []).map((c) => (
                <option key={c.id || c.cam_id} value={c.cam_id}>
                  {c.name || c.cam_id.toUpperCase()} ({c.section_name || 'Floor'})
                </option>
              ))}
            </select>
          </div>

          <div className="time-filter-pills">
            <button 
              className={`filter-pill ${timeFilter === 'LATEST' ? 'active' : ''}`}
              onClick={() => setTimeFilter('LATEST')}
            >
              Real-time
            </button>
            <button 
              className={`filter-pill ${timeFilter === 'TODAY' ? 'active' : ''}`}
              onClick={() => setTimeFilter('TODAY')}
            >
              Today
            </button>
          </div>
        </div>
      </div>

      {/* Main Grid View */}
      <div className="heatmap-main-grid">
        {/* Left Container: Heatmap Display */}
        <div className="heatmap-display-card">
          <div className="display-card-header">
            <div className="cam-title-group">
              <h3>{currentCamObj.name || selectedCam.toUpperCase()}</h3>
              <span className="section-badge">{currentCamObj.section_name || 'Showroom Section'}</span>
            </div>

            {activeHeatmap && (
              <div className="header-badges">
                <span className="density-status-tag" style={{ color: densityStatus.color, background: densityStatus.bg }}>
                  {densityStatus.label} ({densityPct}%)
                </span>
                <button className="expand-btn" onClick={() => setFullscreenModal(true)} title="Expand Fullscreen Heatmap">
                  🔍 Fullscreen
                </button>
              </div>
            )}
          </div>

          <div className="heatmap-image-wrapper">
            {loading ? (
              <div className="heatmap-loading-state">
                <div className="spinner large"></div>
                <p>Syncing camera heatmap overlay from CV stream...</p>
              </div>
            ) : activeHeatmap && activeHeatmap.image_url ? (
              <div className="image-overlay-container">
                <img 
                  src={activeHeatmap.image_url} 
                  alt={`Heatmap for ${selectedCam}`} 
                  className="heatmap-overlay-img"
                />
                <div className="heatmap-watermark">
                  <span>📷 {selectedCam.toUpperCase()} HEATMAP OVERLAY</span>
                  <span>{activeHeatmap.created_at ? new Date(activeHeatmap.created_at).toLocaleTimeString() : 'LIVE'}</span>
                </div>
              </div>
            ) : (
              <div className="no-heatmap-placeholder">
                <div className="placeholder-icon">🗺️</div>
                <h4>Waiting for CV Heatmap Stream ({selectedCam || 'Camera'})</h4>
                <p>The Computer Vision pipeline automatically updates density overlays every 10–15 minutes.</p>
                <div className="placeholder-status">
                  <span className="dot pulse"></span> Listening on backend endpoint <code>/api/heatmaps/upload</code>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Container: Analytics & Stream History */}
        <div className="heatmap-sidebar-card">
          <div className="card-section-title">
            <h3>Dwell &amp; Traffic Density Analytics</h3>
            <span className="info-sub">Camera: {selectedCam.toUpperCase()}</span>
          </div>

          {/* Density Meter */}
          <div className="density-meter-box">
            <div className="meter-label-row">
              <span className="meter-title">Peak Density Score</span>
              <span className="meter-val" style={{ color: densityStatus.color }}>{densityPct}%</span>
            </div>

            <div className="meter-track">
              <div 
                className="meter-bar-fill" 
                style={{ width: `${densityPct}%`, backgroundColor: densityStatus.color }}
              />
            </div>

            <div className="meter-scale">
              <span>0% Low</span>
              <span>50% Med</span>
              <span>100% Extreme</span>
            </div>
          </div>

          {/* Key Insights List */}
          <div className="insights-container">
            <div className="insight-item">
              <span className="insight-icon">🔥</span>
              <div className="insight-text">
                <span className="insight-label">Primary Hotspot Zone</span>
                <strong className="insight-val">{topZone}</strong>
              </div>
            </div>

            <div className="insight-item">
              <span className="insight-icon">⏰</span>
              <div className="insight-text">
                <span className="insight-label">Peak Traffic Hours</span>
                <strong className="insight-val">{peakHour}</strong>
              </div>
            </div>

            <div className="insight-item">
              <span className="insight-icon">⏳</span>
              <div className="insight-text">
                <span className="insight-label">Avg Customer Dwell Time</span>
                <strong className="insight-val">12.5 Mins</strong>
              </div>
            </div>
          </div>

          {/* Stream History Log */}
          <div className="stream-history-box">
            <h4>CV Stream Heatmap History ({heatmaps.length})</h4>
            {heatmaps.length === 0 ? (
              <p className="no-history-text">No heatmaps received yet.</p>
            ) : (
              <div className="history-list">
                {heatmaps.map((h) => {
                  const isSelected = selectedCam === h.cam_id;
                  return (
                    <div 
                      key={h.id} 
                      className={`history-item ${isSelected ? 'active' : ''}`}
                      onClick={() => { setSelectedCam(h.cam_id); setActiveHeatmap(h); }}
                    >
                      <div className="history-cam-info">
                        <span className="cam-badge">📷 {h.cam_id.toUpperCase()}</span>
                        <span className="time-badge">
                          {h.created_at ? new Date(h.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Recent'}
                        </span>
                      </div>
                      <div className="history-density">
                        <span className="d-label">Density:</span>
                        <span className="d-val">{Math.round((h.peak_density || 0) * 100)}%</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Fullscreen Image Modal */}
      {fullscreenModal && activeHeatmap && (
        <div className="modal-backdrop" onClick={() => setFullscreenModal(false)}>
          <div className="modal-content heatmap-modal animate-pop" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3>Heatmap Density Stream — {selectedCam.toUpperCase()}</h3>
                <p className="modal-sub">Captured at {new Date(activeHeatmap.created_at).toLocaleString()}</p>
              </div>
              <button className="modal-close" onClick={() => setFullscreenModal(false)}>✕</button>
            </div>
            <div className="modal-body modal-heatmap-body">
              <img src={activeHeatmap.image_url} alt="Fullscreen Heatmap" className="modal-heatmap-img" />
            </div>
            <div className="modal-footer">
              <a href={activeHeatmap.image_url} target="_blank" rel="noreferrer" className="btn-secondary">
                📥 Open High-Res S3 File
              </a>
              <button className="btn-primary" onClick={() => setFullscreenModal(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
