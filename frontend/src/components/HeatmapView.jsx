import { useState, useEffect, useMemo } from 'react';
import { getLatestHeatmaps, getHeatmapForCamera, toggleCameraAnalytics, getImageUrl } from '../api/api.js';
import './HeatmapView.css';

export default function HeatmapView({ cameras: initialCameras = [] }) {
  const [heatmaps, setHeatmaps] = useState([]);
  const [selectedCam, setSelectedCam] = useState('');
  const [selectedDate, setSelectedDate] = useState('');
  const [activeHeatmap, setActiveHeatmap] = useState(null);
  const [cameraHistory, setCameraHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [timeFilter, setTimeFilter] = useState('LATEST');
  const [fullscreenModal, setFullscreenModal] = useState(false);
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [camList, setCamList] = useState(initialCameras);
  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [togglingCam, setTogglingCam] = useState({});
  const [imageErrorMap, setImageErrorMap] = useState({});

  useEffect(() => {
    setCamList(initialCameras);
  }, [initialCameras]);

  const fetchHeatmaps = () => {
    getLatestHeatmaps(selectedDate)
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        setHeatmaps(list);

        setSelectedCam((prev) => {
          if (prev) return prev;
          return list.length > 0 ? list[0].cam_id : '';
        });
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchHeatmaps();
    const interval = setInterval(fetchHeatmaps, 5000);
    return () => clearInterval(interval);
  }, [selectedDate]);

  useEffect(() => {
    if (selectedCam) {
      getHeatmapForCamera(selectedCam, 50, selectedDate)
        .then((res) => {
          if (res) {
            const history = Array.isArray(res.history) ? res.history : (Array.isArray(res) ? res : []);
            setCameraHistory(history);
            if (history.length > 0) {
              setActiveHeatmap(history[0]);
            } else if (res.image_url) {
              setActiveHeatmap(res);
            } else {
              setActiveHeatmap(null);
            }
          }
        })
        .catch(console.error);
    }
  }, [selectedCam, selectedDate]);

  const handleToggleHeatmap = async (camId, currentVal) => {
    const newVal = !currentVal;
    setTogglingCam((prev) => ({ ...prev, [camId]: true }));
    try {
      await toggleCameraAnalytics(camId, { heatmap_enabled: newVal });
      setCamList((prev) =>
        prev.map((c) => (c.cam_id === camId ? { ...c, heatmap_enabled: newVal } : c))
      );
    } catch (err) {
      console.error("Failed to toggle heatmap analytics:", err);
      alert(`Could not toggle heatmap analytics for ${camId}: ${err.message}`);
    } finally {
      setTogglingCam((prev) => ({ ...prev, [camId]: false }));
    }
  };

  // Selected camera object details
  const currentCamObj = useMemo(() => {
    return (camList || []).find((c) => c.cam_id === selectedCam) || {
      cam_id: selectedCam || 'cam1',
      name: selectedCam ? selectedCam.toUpperCase() : 'Camera 1',
      section_name: 'Showroom Main Floor'
    };
  }, [camList, selectedCam]);

  const activeHeatmapCams = camList.filter((c) => c.heatmap_enabled !== false);

  // Last 4 heatmaps for selected camera
  const lastFourHeatmaps = useMemo(() => {
    if (cameraHistory.length > 0) return cameraHistory.slice(0, 4);
    if (activeHeatmap) return [activeHeatmap];
    return [];
  }, [cameraHistory, activeHeatmap]);

  // Density calculations
  const densityVal = activeHeatmap?.peak_density || 0;
  const densityPct = Math.round(densityVal * 100);

  const getDensityStatus = (pct) => {
    if (pct > 75) return { label: 'CRITICAL HOTSPOT', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)' };
    if (pct > 50) return { label: 'HIGH TRAFFIC', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' };
    if (pct > 25) return { label: 'MODERATE DENSITY', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)' };
    return { label: 'LOW TRAFFIC', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)' };
  };

  const densityStatus = getDensityStatus(densityPct);
  const metaInfo = activeHeatmap?.meta_info || {};
  const topZone = metaInfo?.top_zone || activeHeatmap?.top_zone || 'Menswear Display Section';
  const peakHour = metaInfo?.peak_hour || activeHeatmap?.peak_hour || '2:00 PM - 5:00 PM';

  const handleImageError = (id) => {
    setImageErrorMap((prev) => ({ ...prev, [id]: true }));
  };

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
          <button 
            className="config-toggle-btn"
            onClick={() => setShowConfigPanel((p) => !p)}
            title="Configure Heatmap Analytics Cameras"
          >
            ⚙️ Heatmap Config ({activeHeatmapCams.length}/{camList.length} Active)
          </button>

          {/* Camera Selection */}
          <div className="control-box">
            <span className="control-label">SELECT CAMERA:</span>
            <select 
              className="cam-select" 
              value={selectedCam} 
              onChange={(e) => setSelectedCam(e.target.value)}
            >
              <option value="">Choose Showroom Camera</option>
              {(camList || []).map((c) => (
                <option key={c.id || c.cam_id} value={c.cam_id}>
                  {c.name || c.cam_id.toUpperCase()} {c.heatmap_enabled === false ? '(Paused)' : '✓'}
                </option>
              ))}
            </select>
          </div>

          {/* Date Filter Selection */}
          <div className="control-box">
            <span className="control-label">FILTER DATE:</span>
            <input 
              type="date" 
              className="cam-select date-select" 
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              title="Filter Heatmaps by Date"
            />
            {selectedDate && (
              <button 
                className="clear-date-btn" 
                onClick={() => setSelectedDate('')} 
                title="Reset Date Filter"
              >
                ✕ Clear
              </button>
            )}
          </div>

          <div className="time-filter-pills">
            <button 
              className={`filter-pill ${timeFilter === 'LATEST' ? 'active' : ''}`}
              onClick={() => { setTimeFilter('LATEST'); setSelectedDate(''); }}
            >
              Real-time
            </button>
            <button 
              className={`filter-pill ${timeFilter === 'TODAY' ? 'active' : ''}`}
              onClick={() => {
                setTimeFilter('TODAY');
                setSelectedDate(new Date().toISOString().split('T')[0]);
              }}
            >
              Today
            </button>
          </div>
        </div>
      </div>

      {/* Heatmap Camera Config Panel */}
      {showConfigPanel && (
        <div className="camera-config-card animate-fade-in" style={{ marginBottom: '24px' }}>
          <div className="config-card-header">
            <div>
              <h3>🔥 Heatmap Camera Analytics Toggles</h3>
              <p>Enable/disable KDE density heatmap generation for individual camera streams.</p>
            </div>
          </div>

          <div className="camera-toggle-grid">
            {camList.map((cam) => {
              const isEnabled = cam.heatmap_enabled !== false;
              const isBusy = togglingCam[cam.cam_id];

              return (
                <div key={cam.cam_id} className={`cam-config-tile ${isEnabled ? 'enabled' : 'disabled'}`}>
                  <div className="tile-top">
                    <div className="cam-title-info">
                      <span className="cam-code">{cam.cam_id}</span>
                      <span className="cam-name">{cam.name || cam.cam_id}</span>
                    </div>

                    <label className="switch-toggle" title="Toggle Heatmap Analytics">
                      <input 
                        type="checkbox" 
                        checked={isEnabled} 
                        disabled={isBusy}
                        onChange={() => handleToggleHeatmap(cam.cam_id, isEnabled)}
                      />
                      <span className="slider round"></span>
                    </label>
                  </div>

                  <div className="tile-meta">
                    <div className="meta-line">
                      <span className="meta-label">Status:</span>
                      <span className={`status-badge ${isEnabled ? 'green' : 'gray'}`}>
                        {isBusy ? 'Saving...' : isEnabled ? 'HEATMAP ACTIVE' : 'HEATMAP PAUSED'}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Main Grid View */}
      <div className="heatmap-main-grid">
        {/* Left Container: Last 4 Heatmaps Grid for Selected Camera */}
        <div className="heatmap-display-card">
          <div className="display-card-header">
            <div className="cam-title-group">
              <h3>{currentCamObj.name || (selectedCam ? selectedCam.toUpperCase() : 'Camera')} — Last 4 Heatmaps</h3>
              <span className="section-badge">{currentCamObj.section_name || 'Showroom Section'}</span>
              {selectedDate && <span className="date-badge">📅 Date: {selectedDate}</span>}
            </div>

            {activeHeatmap && (
              <div className="header-badges">
                <span className="density-status-tag" style={{ color: densityStatus.color, background: densityStatus.bg }}>
                  {densityStatus.label} ({densityPct}%)
                </span>
              </div>
            )}
          </div>

          {/* 2x2 Grid of Last 4 Heatmaps */}
          {loading ? (
            <div className="heatmap-loading-state">
              <div className="spinner large"></div>
              <p>Syncing camera heatmap overlays from CV stream...</p>
            </div>
          ) : lastFourHeatmaps.length > 0 ? (
            <div className="heatmap-2x2-grid">
              {lastFourHeatmaps.map((hm, index) => {
                const cardDensityPct = Math.round((hm.peak_density || 0) * 100);
                const cardStatus = getDensityStatus(cardDensityPct);
                const hasImgError = imageErrorMap[hm.id];
                const timeString = hm.created_at ? new Date(hm.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'LIVE';

                return (
                  <div key={hm.id || index} className="heatmap-grid-tile animate-fade-in">
                    <div className="tile-card-header">
                      <span className="tile-cam-name">📷 {hm.cam_id.toUpperCase()} #{index + 1}</span>
                      <div className="tile-header-right">
                        <span className="tile-density-tag" style={{ color: cardStatus.color, background: cardStatus.bg }}>
                          {cardDensityPct}% ({cardStatus.label})
                        </span>
                        <button 
                          className="tile-expand-btn" 
                          onClick={() => { setActiveHeatmap(hm); setFullscreenModal(true); }}
                          title="View Fullscreen Heatmap"
                        >
                          🔍 Fullscreen
                        </button>
                      </div>
                    </div>

                    <div className="tile-image-wrapper">
                      {hm.image_url && !hasImgError ? (
                        <img 
                          src={getImageUrl(hm.image_url)} 
                          alt={`Heatmap ${hm.cam_id} #${index + 1}`} 
                          className="heatmap-grid-img"
                          onError={() => handleImageError(hm.id)}
                        />
                      ) : (
                        <div className="fallback-kde mini-kde">
                          <div className="hotspot-glow core mini" style={{ opacity: hm.peak_density > 0 ? Math.min(1, hm.peak_density) : 0.8 }} />
                          <div className="kde-info-overlay mini">
                            <span className="cam-title">📷 {hm.cam_id.toUpperCase()}</span>
                            <span className="density-tag">{cardDensityPct}% Density</span>
                          </div>
                        </div>
                      )}
                      <div className="heatmap-watermark mini">
                        <span>📷 {hm.cam_id.toUpperCase()}</span>
                        <span>⏰ {timeString}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="no-heatmap-placeholder">
              <div className="placeholder-icon">🗺️</div>
              <h4>No Heatmaps Found ({selectedCam ? selectedCam.toUpperCase() : 'Camera'})</h4>
              <p>
                {selectedDate 
                  ? `No heatmaps generated on ${selectedDate}. Try selecting another date or clearing date filter.` 
                  : "The Computer Vision pipeline automatically updates density overlays every 10–15 minutes."}
              </p>
              <div className="placeholder-status">
                <span className="dot pulse"></span> Listening on backend endpoint <code>/api/heatmaps/upload</code>
              </div>
            </div>
          )}
        </div>

        {/* Right Container: Analytics & Heatmap Notifications Feed */}
        <div className="heatmap-sidebar-card">
          <div className="card-section-title">
            <h3>Dwell &amp; Traffic Density Analytics</h3>
            <span className="info-sub">Camera: {selectedCam ? selectedCam.toUpperCase() : 'All'}</span>
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

          {/* Notifications & Stream History Feed */}
          <div className="stream-history-box">
            <div className="history-box-header">
              <h4>🔔 Heatmap Notifications ({cameraHistory.length || heatmaps.length})</h4>
            </div>

            {(cameraHistory.length > 0 ? cameraHistory : heatmaps).length === 0 ? (
              <p className="no-history-text">No heatmap notifications received yet.</p>
            ) : (
              <div className="history-list">
                {(cameraHistory.length > 0 ? cameraHistory : heatmaps).slice(0, 6).map((h) => {
                  const isSelected = activeHeatmap?.id === h.id;
                  const hDensityPct = Math.round((h.peak_density || 0) * 100);
                  const hStatus = getDensityStatus(hDensityPct);

                  return (
                    <div 
                      key={h.id} 
                      className={`history-item ${isSelected ? 'active' : ''}`}
                      onClick={() => setActiveHeatmap(h)}
                    >
                      <div className="history-cam-info">
                        <span className="cam-badge">📷 {h.cam_id.toUpperCase()}</span>
                        <span className="time-badge">
                          {h.created_at ? new Date(h.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Recent'}
                        </span>
                      </div>
                      <div className="history-density">
                        <span className="d-label" style={{ color: hStatus.color }}>{hStatus.label}</span>
                        <span className="d-val">{hDensityPct}%</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Show More Button */}
            <button 
              className="show-more-history-btn" 
              onClick={() => setShowHistoryModal(true)}
              title="View All Heatmap Notifications and Full Details"
            >
              📋 Show More History ({cameraHistory.length || heatmaps.length} Total)
            </button>
          </div>
        </div>
      </div>

      {/* Fullscreen Image Modal */}
      {fullscreenModal && activeHeatmap && (
        <div className="modal-backdrop" onClick={() => setFullscreenModal(false)}>
          <div className="modal-content heatmap-modal animate-pop" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3>Heatmap Density Stream — {selectedCam ? selectedCam.toUpperCase() : 'Camera'}</h3>
                <p className="modal-sub">Captured at {new Date(activeHeatmap.created_at).toLocaleString()}</p>
              </div>
              <button className="modal-close" onClick={() => setFullscreenModal(false)}>✕</button>
            </div>
            <div className="modal-body modal-heatmap-body">
              {activeHeatmap.image_url && !imageErrorMap[activeHeatmap.id] ? (
                <img 
                  src={getImageUrl(activeHeatmap.image_url)} 
                  alt="Fullscreen Heatmap" 
                  className="modal-heatmap-img" 
                  onError={() => handleImageError(activeHeatmap.id)}
                />
              ) : (
                <div className="fallback-kde">
                  <div className="kde-visual-preview">
                    <div className="hotspot-glow core" style={{ opacity: activeHeatmap.peak_density > 0 ? Math.min(1, activeHeatmap.peak_density) : 0.8 }} />
                    <div className="kde-info-overlay">
                      <span className="cam-title">📷 {activeHeatmap.cam_id.toUpperCase()}</span>
                      <span className="density-tag">{Math.round((activeHeatmap.peak_density || 0) * 100)}% Density</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer">
              {activeHeatmap.image_url && (
                <a href={getImageUrl(activeHeatmap.image_url)} target="_blank" rel="noreferrer" className="btn-secondary">
                  📥 Open High-Res Heatmap File
                </a>
              )}
              <button className="btn-primary" onClick={() => setFullscreenModal(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Show More History Modal */}
      {showHistoryModal && (
        <div className="modal-backdrop" onClick={() => setShowHistoryModal(false)}>
          <div className="modal-content history-modal animate-pop" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3>📋 Complete Heatmap Notifications &amp; History</h3>
                <p className="modal-sub">Showing all historical density logs for {selectedCam ? selectedCam.toUpperCase() : 'Showroom'}</p>
              </div>
              <button className="modal-close" onClick={() => setShowHistoryModal(false)}>✕</button>
            </div>
            <div className="modal-body history-modal-body">
              <div className="history-modal-grid">
                {(cameraHistory.length > 0 ? cameraHistory : heatmaps).map((h) => {
                  const hPct = Math.round((h.peak_density || 0) * 100);
                  const hStatus = getDensityStatus(hPct);
                  const hMeta = h.meta_info || {};

                  return (
                    <div key={h.id} className="history-modal-card">
                      <div className="card-top">
                        <span className="cam-tag">📷 {h.cam_id.toUpperCase()}</span>
                        <span className="status-tag" style={{ color: hStatus.color, background: hStatus.bg }}>
                          {hPct}% ({hStatus.label})
                        </span>
                      </div>
                      <div className="card-time">
                        ⏰ {h.created_at ? new Date(h.created_at).toLocaleString() : 'Recent'}
                      </div>
                      <div className="card-meta-info">
                        <div><span>Hotspot:</span> <strong>{hMeta.top_zone || h.top_zone || 'Showroom Floor'}</strong></div>
                        <div><span>Peak Hour:</span> <strong>{hMeta.peak_hour || '14:00 - 17:00'}</strong></div>
                      </div>
                      <div className="card-actions">
                        <button 
                          className="btn-inspect"
                          onClick={() => { setActiveHeatmap(h); setFullscreenModal(true); setShowHistoryModal(false); }}
                        >
                          🔍 View Heatmap Img
                        </button>
                        {h.image_url && (
                          <a href={getImageUrl(h.image_url)} target="_blank" rel="noreferrer" className="btn-s3">
                            📥 Image File
                          </a>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-primary" onClick={() => setShowHistoryModal(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

