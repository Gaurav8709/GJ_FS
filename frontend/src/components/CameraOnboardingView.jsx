import { useState, useMemo } from 'react';
import { onboardCamera, updateCamera, deleteCamera, clearAllCameras } from '../api/api.js';
import './CameraOnboardingView.css';

export default function CameraOnboardingView({ cameras = [], floors = [], onRefresh }) {
  /* Form state */
  const [camId, setCamId] = useState('');
  const [name, setName] = useState('');
  const [rtspUrl, setRtspUrl] = useState('');
  const [webRtspUrl, setWebRtspUrl] = useState('');
  const [codec, setCodec] = useState('H.264');
  const [selectedFloorId, setSelectedFloorId] = useState('');
  const [selectedSectionId, setSelectedSectionId] = useState('');
  const [locationText, setLocationText] = useState('');
  const [active, setActive] = useState(true);

  /* UI feedback state */
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterTab, setFilterTab] = useState('all'); // all | active | inactive

  /* Edit Modal State */
  const [editingCam, setEditingCam] = useState(null);
  const [editForm, setEditForm] = useState({});

  /* Clear confirmation state */
  const [showClearModal, setShowClearModal] = useState(false);
  const [clearing, setClearing] = useState(false);

  /* Uniqueness check for Camera Number/ID */
  const existingCamIds = useMemo(() => {
    return new Set(cameras.map((c) => (c.cam_id || '').trim().toLowerCase()));
  }, [cameras]);

  const isDuplicateId = useMemo(() => {
    if (!camId.trim()) return false;
    return existingCamIds.has(camId.trim().toLowerCase());
  }, [camId, existingCamIds]);

  /* Sections derived from selected floor */
  const availableSections = useMemo(() => {
    if (!selectedFloorId) return [];
    const floor = floors.find((f) => String(f.id || f.floor_id) === String(selectedFloorId));
    return floor ? floor.sections || [] : [];
  }, [selectedFloorId, floors]);

  /* Metrics */
  const activeCount = cameras.filter((c) => c.active !== false).length;
  const uniqueZones = new Set(cameras.map((c) => c.location || c.section_id).filter(Boolean)).size;

  /* Handle Camera Submission */
  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    const cleanCamId = camId.trim();
    if (!cleanCamId) {
      setError('Please enter a valid Camera Number / ID (e.g. cam1, cam28)');
      return;
    }

    if (isDuplicateId) {
      setError(`Camera ID '${cleanCamId}' already exists! Existing camera numbers cannot be reused.`);
      return;
    }

    if (!name.trim()) {
      setError('Please enter a descriptive Camera Name');
      return;
    }

    try {
      setLoading(true);
      const payload = {
        cam_id: cleanCamId,
        name: name.trim(),
        rtsp_url: rtspUrl.trim() || `rtsp://stream.local/${cleanCamId}`,
        web_rtsp_url: webRtspUrl.trim(),
        codec: codec,
        floor_id: selectedFloorId ? parseInt(selectedFloorId, 10) : null,
        section_id: selectedSectionId ? parseInt(selectedSectionId, 10) : null,
        location: locationText.trim() || (selectedFloorId ? `Floor ${selectedFloorId}` : 'Showroom Main'),
        active: active,
      };

      await onboardCamera(payload);
      setSuccess(`Camera '${cleanCamId}' onboarded successfully into RDS!`);

      /* Reset form */
      setCamId('');
      setName('');
      setRtspUrl('');
      setWebRtspUrl('');
      setLocationText('');
      setSelectedFloorId('');
      setSelectedSectionId('');

      if (onRefresh) onRefresh();
    } catch (err) {
      setError(err.message || 'Failed to onboard camera');
    } finally {
      setLoading(false);
    }
  };

  /* Handle Camera Delete */
  const handleDelete = async (targetCamId) => {
    if (!window.confirm(`Are you sure you want to delete camera '${targetCamId}'?`)) return;
    try {
      await deleteCamera(targetCamId);
      setSuccess(`Camera '${targetCamId}' deleted successfully`);
      if (onRefresh) onRefresh();
    } catch (err) {
      setError(err.message || 'Failed to delete camera');
    }
  };

  /* Handle Clear All Cameras */
  const handleClearAll = async () => {
    try {
      setClearing(true);
      await clearAllCameras();
      setSuccess('All cameras have been successfully cleared from the database.');
      setShowClearModal(false);
      if (onRefresh) onRefresh();
    } catch (err) {
      setError(err.message || 'Failed to clear cameras');
    } finally {
      setClearing(false);
    }
  };

  /* Handle Edit Submit */
  const handleEditSubmit = async (e) => {
    e.preventDefault();
    if (!editingCam) return;
    try {
      setLoading(true);
      await updateCamera(editingCam.cam_id, editForm);
      setSuccess(`Camera '${editingCam.cam_id}' updated successfully`);
      setEditingCam(null);
      if (onRefresh) onRefresh();
    } catch (err) {
      setError(err.message || 'Failed to update camera');
    } finally {
      setLoading(false);
    }
  };

  /* Filtered cameras for display */
  const filteredCameras = useMemo(() => {
    return cameras.filter((c) => {
      if (filterTab === 'active' && c.active === false) return false;
      if (filterTab === 'inactive' && c.active !== false) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const matchId = (c.cam_id || '').toLowerCase().includes(q);
        const matchName = (c.name || '').toLowerCase().includes(q);
        const matchLoc = (c.location || '').toLowerCase().includes(q);
        return matchId || matchName || matchLoc;
      }
      return true;
    });
  }, [cameras, filterTab, searchQuery]);

  return (
    <div className="onboarding-container">
      {/* Top Banner & Header */}
      <div className="onboarding-header">
        <div>
          <div className="onboarding-title-badge">
            <span className="badge-pulse" />
            Central Hardware Onboarding
          </div>
          <h1 className="onboarding-title">Camera Onboarding & System Setup</h1>
          <p className="onboarding-subtitle">
            Register RTSP feeds, web streams, and zones into PostgreSQL RDS to centralize live surveillance across all platform modules.
          </p>
        </div>

        <div className="onboarding-header-actions">
          <button
            className="btn-clear-all"
            onClick={() => setShowClearModal(true)}
            title="Delete all existing dummy camera records"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
            Clear Existing Cameras
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="onboarding-metrics">
        <div className="metric-card">
          <div className="metric-icon blue">🎥</div>
          <div className="metric-info">
            <span className="metric-value">{cameras.length}</span>
            <span className="metric-label">Total Onboarded Cameras</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon green">⚡</div>
          <div className="metric-info">
            <span className="metric-value">{activeCount}</span>
            <span className="metric-label">Active Online Feeds</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon purple">📍</div>
          <div className="metric-info">
            <span className="metric-value">{uniqueZones}</span>
            <span className="metric-label">Showroom Zones Covered</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon cyan">🔒</div>
          <div className="metric-info">
            <span className="metric-value">AWS RDS</span>
            <span className="metric-label">PostgreSQL Central Sync</span>
          </div>
        </div>
      </div>

      {/* Notifications */}
      {error && (
        <div className="onboarding-alert error">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{error}</span>
          <button className="alert-close" onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {success && (
        <div className="onboarding-alert success">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <span>{success}</span>
          <button className="alert-close" onClick={() => setSuccess(null)}>✕</button>
        </div>
      )}

      {/* Two Column Layout */}
      <div className="onboarding-grid">
        {/* Left: Registration Form */}
        <div className="onboarding-card form-card">
          <div className="card-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12h14" />
            </svg>
            <h2>Onboard New Camera</h2>
          </div>

          <form onSubmit={handleSubmit} className="onboarding-form">
            {/* Camera Number / ID */}
            <div className="form-group">
              <label className="form-label required">
                Camera Number / ID
                <span className="form-hint">(e.g. cam1, cam28, cam_entrance)</span>
              </label>
              <div className="input-with-icon">
                <input
                  type="text"
                  className={`form-input ${isDuplicateId ? 'input-error' : ''}`}
                  placeholder="e.g. cam28"
                  value={camId}
                  onChange={(e) => setCamId(e.target.value)}
                  required
                />
                {camId && (
                  <span className={`status-indicator ${isDuplicateId ? 'taken' : 'available'}`}>
                    {isDuplicateId ? '❌ Existing ID' : '✓ Available'}
                  </span>
                )}
              </div>
              {isDuplicateId && (
                <div className="field-error-msg">
                  ⚠️ Existing camera number cannot be reused! Please enter a unique camera ID.
                </div>
              )}
            </div>

            {/* Camera Name */}
            <div className="form-group">
              <label className="form-label required">Camera Display Name</label>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. Main Entrance Camera 1"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>

            {/* Floor & Section / Zone Selection */}
            <div className="form-row-2">
              <div className="form-group">
                <label className="form-label">Floor</label>
                <select
                  className="form-select"
                  value={selectedFloorId}
                  onChange={(e) => {
                    setSelectedFloorId(e.target.value);
                    setSelectedSectionId('');
                  }}
                >
                  <option value="">Select Floor...</option>
                  {floors.map((f) => (
                    <option key={f.id || f.floor_id} value={f.id || f.floor_id}>
                      {f.name || `Floor ${f.id}`}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Section / Zone</label>
                <select
                  className="form-select"
                  value={selectedSectionId}
                  onChange={(e) => setSelectedSectionId(e.target.value)}
                  disabled={!selectedFloorId}
                >
                  <option value="">Select Section...</option>
                  {availableSections.map((s) => (
                    <option key={s.id || s.section_id} value={s.id || s.section_id}>
                      {s.name || `Section ${s.id}`}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Zone / Location Custom Text */}
            <div className="form-group">
              <label className="form-label">Location / Zone Description</label>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. Ground Floor - Billing Counter / Aisle 2"
                value={locationText}
                onChange={(e) => setLocationText(e.target.value)}
              />
            </div>

            {/* RTSP Stream Link */}
            <div className="form-group">
              <label className="form-label">RTSP Stream Link</label>
              <input
                type="text"
                className="form-input code-font"
                placeholder="rtsp://admin:pass@192.168.1.100:554/stream1"
                value={rtspUrl}
                onChange={(e) => setRtspUrl(e.target.value)}
              />
            </div>

            {/* Web RTSP / Stream Link & Codec */}
            <div className="form-row-2">
              <div className="form-group">
                <label className="form-label">Web RTSP / WebRTC Link</label>
                <input
                  type="text"
                  className="form-input code-font"
                  placeholder="http://192.168.1.100:8080/hls"
                  value={webRtspUrl}
                  onChange={(e) => setWebRtspUrl(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Codec / Format</label>
                <select
                  className="form-select"
                  value={codec}
                  onChange={(e) => setCodec(e.target.value)}
                >
                  <option value="H.264">H.264 (Standard)</option>
                  <option value="H.265">H.265 (HEVC)</option>
                  <option value="MJPEG">MJPEG</option>
                  <option value="WebRTC">WebRTC Stream</option>
                </select>
              </div>
            </div>

            {/* Active Switch */}
            <div className="form-group checkbox-group">
              <label className="switch-label">
                <input
                  type="checkbox"
                  checked={active}
                  onChange={(e) => setActive(e.target.checked)}
                />
                <span className="switch-slider" />
                <span className="switch-text">Enable Camera Active Streaming</span>
              </label>
            </div>

            <button
              type="submit"
              className="btn-submit"
              disabled={loading || isDuplicateId}
            >
              {loading ? (
                <span className="spinner" />
              ) : (
                <>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  Register &amp; Onboard Camera
                </>
              )}
            </button>
          </form>
        </div>

        {/* Right: Camera Directory Table */}
        <div className="onboarding-card directory-card">
          <div className="card-header space-between">
            <div className="header-left-title">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                <line x1="8" y1="21" x2="16" y2="21" />
                <line x1="12" y1="17" x2="12" y2="21" />
              </svg>
              <h2>Camera Directory ({filteredCameras.length})</h2>
            </div>

            <div className="tab-filters">
              <button
                className={`tab-btn ${filterTab === 'all' ? 'active' : ''}`}
                onClick={() => setFilterTab('all')}
              >
                All ({cameras.length})
              </button>
              <button
                className={`tab-btn ${filterTab === 'active' ? 'active' : ''}`}
                onClick={() => setFilterTab('active')}
              >
                Active ({activeCount})
              </button>
              <button
                className={`tab-btn ${filterTab === 'inactive' ? 'active' : ''}`}
                onClick={() => setFilterTab('inactive')}
              >
                Inactive ({cameras.length - activeCount})
              </button>
            </div>
          </div>

          {/* Search bar */}
          <div className="directory-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              placeholder="Search camera number, name, or zone location..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button className="search-clear" onClick={() => setSearchQuery('')}>✕</button>
            )}
          </div>

          {/* Table */}
          <div className="table-responsive">
            <table className="camera-table">
              <thead>
                <tr>
                  <th>Camera ID</th>
                  <th>Name &amp; Zone Location</th>
                  <th>RTSP Link</th>
                  <th>Codec</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredCameras.length === 0 ? (
                  <tr>
                    <td colSpan="6" className="table-empty">
                      <div className="empty-state">
                        <span>📹</span>
                        <p>No onboarded cameras found.</p>
                        <small>Use the form on the left to register your cameras into RDS.</small>
                      </div>
                    </td>
                  </tr>
                ) : (
                  filteredCameras.map((cam) => (
                    <tr key={cam.id || cam.cam_id}>
                      <td>
                        <span className="cam-id-pill">{cam.cam_id}</span>
                      </td>
                      <td>
                        <div className="cam-name-cell">
                          <span className="cam-name">{cam.name}</span>
                          <span className="cam-location">📍 {cam.location || 'Showroom Main'}</span>
                        </div>
                      </td>
                      <td>
                        <div className="rtsp-url-cell" title={cam.rtsp_url}>
                          <code>{cam.rtsp_url || 'N/A'}</code>
                        </div>
                      </td>
                      <td>
                        <span className="codec-tag">{cam.codec || 'H.264'}</span>
                      </td>
                      <td>
                        <span className={`status-pill ${cam.active !== false ? 'online' : 'offline'}`}>
                          <span className="dot" />
                          {cam.active !== false ? 'Active' : 'Disabled'}
                        </span>
                      </td>
                      <td>
                        <div className="action-buttons">
                          <button
                            className="btn-action edit"
                            title="Edit Camera"
                            onClick={() => {
                              setEditingCam(cam);
                              setEditForm({
                                name: cam.name,
                                rtsp_url: cam.rtsp_url,
                                web_rtsp_url: cam.web_rtsp_url || '',
                                codec: cam.codec || 'H.264',
                                location: cam.location || '',
                                active: cam.active !== false,
                              });
                            }}
                          >
                            ✏️
                          </button>
                          <button
                            className="btn-action delete"
                            title="Delete Camera"
                            onClick={() => handleDelete(cam.cam_id)}
                          >
                            🗑️
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Edit Camera Modal */}
      {editingCam && (
        <div className="modal-backdrop" onClick={() => setEditingCam(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Edit Camera [{editingCam.cam_id}]</h3>
              <button className="modal-close" onClick={() => setEditingCam(null)}>✕</button>
            </div>
            <form onSubmit={handleEditSubmit} className="onboarding-form">
              <div className="form-group">
                <label className="form-label">Camera Display Name</label>
                <input
                  type="text"
                  className="form-input"
                  value={editForm.name || ''}
                  onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label">Location / Zone Description</label>
                <input
                  type="text"
                  className="form-input"
                  value={editForm.location || ''}
                  onChange={(e) => setEditForm({ ...editForm, location: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">RTSP Stream Link</label>
                <input
                  type="text"
                  className="form-input code-font"
                  value={editForm.rtsp_url || ''}
                  onChange={(e) => setEditForm({ ...editForm, rtsp_url: e.target.value })}
                />
              </div>

              <div className="form-row-2">
                <div className="form-group">
                  <label className="form-label">Web RTSP / WebRTC Link</label>
                  <input
                    type="text"
                    className="form-input code-font"
                    value={editForm.web_rtsp_url || ''}
                    onChange={(e) => setEditForm({ ...editForm, web_rtsp_url: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Codec</label>
                  <select
                    className="form-select"
                    value={editForm.codec || 'H.264'}
                    onChange={(e) => setEditForm({ ...editForm, codec: e.target.value })}
                  >
                    <option value="H.264">H.264</option>
                    <option value="H.265">H.265</option>
                    <option value="MJPEG">MJPEG</option>
                    <option value="WebRTC">WebRTC</option>
                  </select>
                </div>
              </div>

              <div className="form-group checkbox-group">
                <label className="switch-label">
                  <input
                    type="checkbox"
                    checked={editForm.active}
                    onChange={(e) => setEditForm({ ...editForm, active: e.target.checked })}
                  />
                  <span className="switch-slider" />
                  <span className="switch-text">Active Stream Status</span>
                </label>
              </div>

              <div className="modal-actions">
                <button type="button" className="btn-secondary" onClick={() => setEditingCam(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={loading}>
                  {loading ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Clear All Confirmation Modal */}
      {showClearModal && (
        <div className="modal-backdrop" onClick={() => setShowClearModal(false)}>
          <div className="modal-card modal-warning" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="warning-text">⚠️ Clear All Cameras Data</h3>
              <button className="modal-close" onClick={() => setShowClearModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <p>Are you sure you want to delete all <strong>{cameras.length}</strong> camera records from PostgreSQL RDS?</p>
              <p className="subtext">This action will erase existing test/dummy camera data so you can onboard fresh showroom cameras.</p>
            </div>
            <div className="modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowClearModal(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn-danger"
                onClick={handleClearAll}
                disabled={clearing}
              >
                {clearing ? 'Clearing...' : 'Yes, Delete All Cameras'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
