import { useState, useEffect } from 'react';
import { 
  getFootfallStats, 
  updateFootfall, 
  toggleCameraAnalytics, 
  getFootfallCamerasConfig, 
  importFootfallCamerasConfig 
} from '../api/api.js';
import './FootfallView.css';

export default function FootfallView({ cameras: initialCameras = [] }) {
  const [stats, setStats] = useState(null);
  const [selectedCam, setSelectedCam] = useState('');
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [camList, setCamList] = useState(initialCameras);
  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [importJsonText, setImportJsonText] = useState('');
  const [importStatus, setImportStatus] = useState(null);
  const [togglingCam, setTogglingCam] = useState({});

  useEffect(() => {
    setCamList(initialCameras);
  }, [initialCameras]);

  const fetchStats = () => {
    getFootfallStats(selectedCam)
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, [selectedCam]);

  // Handle Footfall Toggle per Camera
  const handleToggleFootfall = async (camId, currentVal) => {
    const newVal = !currentVal;
    setTogglingCam((prev) => ({ ...prev, [camId]: true }));
    try {
      await toggleCameraAnalytics(camId, { footfall_enabled: newVal });
      setCamList((prev) =>
        prev.map((c) => (c.cam_id === camId ? { ...c, footfall_enabled: newVal } : c))
      );
    } catch (err) {
      console.error("Failed to toggle camera footfall analytics:", err);
      alert(`Could not toggle analytics for ${camId}: ${err.message}`);
    } finally {
      setTogglingCam((prev) => ({ ...prev, [camId]: false }));
    }
  };

  // Export footfall_cameras.json for CV Team
  const handleExportConfig = async () => {
    try {
      const config = await getFootfallCamerasConfig();
      const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'footfall_cameras.json';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Failed to export config:", err);
      alert("Error exporting footfall_cameras.json: " + err.message);
    }
  };

  // Import footfall_cameras.json from CV Team
  const handleImportSubmit = async () => {
    setImportStatus("Importing...");
    try {
      const parsed = JSON.parse(importJsonText);
      const res = await importFootfallCamerasConfig(parsed);
      setImportStatus(`Success! Imported ${res.imported_count || 0} camera configurations.`);
      setTimeout(() => {
        setShowImportModal(false);
        setImportStatus(null);
        setImportJsonText('');
        window.location.reload();
      }, 1200);
    } catch (err) {
      console.error("Import error:", err);
      setImportStatus("Import Failed: " + err.message);
    }
  };

  const handleSimulateUpdate = async (type) => {
    setSimulating(true);
    const camId = selectedCam || 'cam1';
    const payload = {
      cam_id: camId,
      entries: type === 'entry' ? 1 : 0,
      exits: type === 'exit' ? 1 : 0,
      male_count: Math.random() > 0.5 ? 1 : 0,
      female_count: Math.random() > 0.5 ? 1 : 0,
      age_breakdown: {
        "0_9": 0,
        "10_17": 0,
        "18_25": Math.random() > 0.5 ? 1 : 0,
        "26_35": Math.random() > 0.5 ? 1 : 0,
        "36_50": 0,
        "50_plus": 0
      }
    };
    try {
      await updateFootfall(payload);
      fetchStats();
    } catch (e) {
      console.error("Simulation error", e);
    } finally {
      setSimulating(false);
    }
  };

  if (loading && !stats) {
    return <div className="footfall-loading">Loading Footfall Analytics...</div>;
  }

  const gender = stats?.gender_breakdown || { male: 0, female: 0 };
  const totalGender = (gender.male + gender.female) || 1;
  const malePercent = Math.round((gender.male / totalGender) * 100);
  const femalePercent = Math.round((gender.female / totalGender) * 100);

  const age = stats?.age_breakdown || { "0_9": 0, "10_17": 0, "18_25": 0, "26_35": 0, "36_50": 0, "50_plus": 0 };
  const maxAge = Math.max(...Object.values(age), 1);

  // Active Enabled Cameras for Footfall Analytics
  const activeFootfallCams = camList.filter((c) => c.footfall_enabled !== false);

  return (
    <div className="footfall-view animate-fade-in">
      <div className="footfall-header">
        <div>
          <h2>Footfall Analytics & Demographics</h2>
          <p className="footfall-subtitle">Real-time listener tracking for showroom entries, exits, gender, and age distribution.</p>
        </div>
        <div className="footfall-controls">
          <button 
            className="config-toggle-btn"
            onClick={() => setShowConfigPanel((p) => !p)}
            title="Configure Cameras for Footfall Analytics"
          >
            ⚙️ Camera Config ({activeFootfallCams.length}/{camList.length} Active)
          </button>

          <select 
            className="cam-select" 
            value={selectedCam} 
            onChange={(e) => setSelectedCam(e.target.value)}
          >
            <option value="">All Enabled Cameras ({activeFootfallCams.length})</option>
            {camList.map((c) => (
              <option key={c.id || c.cam_id} value={c.cam_id}>
                {c.name || c.cam_id.toUpperCase()} {c.footfall_enabled === false ? '(Paused)' : '✓'}
              </option>
            ))}
          </select>

          <div className="sim-buttons">
            <button className="sim-btn in" onClick={() => handleSimulateUpdate('entry')} disabled={simulating}>
              +1 Entry
            </button>
            <button className="sim-btn out" onClick={() => handleSimulateUpdate('exit')} disabled={simulating}>
              -1 Exit
            </button>
          </div>
        </div>
      </div>

      {/* Camera Configuration & Toggle Panel */}
      {showConfigPanel && (
        <div className="camera-config-card animate-fade-in">
          <div className="config-card-header">
            <div>
              <h3>🎥 Footfall Camera Analytics Configuration</h3>
              <p>Enable/Disable Footfall tracking for individual cameras or export/import CV team's <code>footfall_cameras.json</code>.</p>
            </div>
            <div className="config-action-buttons">
              <button className="export-json-btn" onClick={handleExportConfig}>
                📥 Export footfall_cameras.json
              </button>
              <button className="import-json-btn" onClick={() => setShowImportModal(true)}>
                📤 Import footfall_cameras.json
              </button>
            </div>
          </div>

          <div className="camera-toggle-grid">
            {camList.map((cam) => {
              const isEnabled = cam.footfall_enabled !== false;
              const isBusy = togglingCam[cam.cam_id];

              return (
                <div key={cam.cam_id} className={`cam-config-tile ${isEnabled ? 'enabled' : 'disabled'}`}>
                  <div className="tile-top">
                    <div className="cam-title-info">
                      <span className="cam-code">{cam.cam_id}</span>
                      <span className="cam-name">{cam.name || cam.cam_id}</span>
                    </div>

                    <label className="switch-toggle" title="Toggle Footfall Analytics">
                      <input 
                        type="checkbox" 
                        checked={isEnabled} 
                        disabled={isBusy}
                        onChange={() => handleToggleFootfall(cam.cam_id, isEnabled)}
                      />
                      <span className="slider round"></span>
                    </label>
                  </div>

                  <div className="tile-meta">
                    <div className="meta-line">
                      <span className="meta-label">Analytics:</span>
                      <span className="meta-val">{cam.analytics_config || `config_nvdsanalytics_${cam.cam_id}.txt`}</span>
                    </div>
                    <div className="meta-line">
                      <span className="meta-label">Status:</span>
                      <span className={`status-badge ${isEnabled ? 'green' : 'gray'}`}>
                        {isBusy ? 'Saving...' : isEnabled ? 'FOOTFALL ACTIVE' : 'FOOTFALL PAUSED'}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Summary KPI Cards */}
      <div className="footfall-kpis">
        <div className="kpi-card green">
          <div className="kpi-title">Total Entries (+1)</div>
          <div className="kpi-value">{stats?.total_entries || 0}</div>
        </div>
        <div className="kpi-card red">
          <div className="kpi-title">Total Exits (-1)</div>
          <div className="kpi-value">{stats?.total_exits || 0}</div>
        </div>
        <div className="kpi-card blue">
          <div className="kpi-title">Current Occupancy</div>
          <div className="kpi-value">{stats?.net_current || 0}</div>
        </div>
      </div>

      {/* Analytics Charts Grid */}
      <div className="footfall-grid">
        {/* Timestamp Bar Chart */}
        <div className="footfall-chart-card">
          <h3>Footfall Timestamp History</h3>
          <div className="bar-chart-container">
            {(stats?.time_series || []).slice(-12).map((item, idx) => {
              const heightPct = Math.min(100, Math.max(10, item.entries * 12));
              return (
                <div key={idx} className="bar-column">
                  <div className="bar-value">+{item.entries}</div>
                  <div className="bar-fill" style={{ height: `${heightPct}%` }} />
                  <div className="bar-label">{item.timestamp}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Demographics Breakdown */}
        <div className="footfall-demo-card">
          <h3>Demographics Breakdown</h3>

          {/* Gender Ratio */}
          <div className="gender-section">
            <div className="section-label">Gender Distribution</div>
            <div className="gender-bar-wrapper">
              <div className="gender-bar male" style={{ width: `${malePercent}%` }}>
                {malePercent > 10 && `Male ${malePercent}%`}
              </div>
              <div className="gender-bar female" style={{ width: `${femalePercent}%` }}>
                {femalePercent > 10 && `Female ${femalePercent}%`}
              </div>
            </div>
            <div className="gender-legend">
              <span><span className="dot male-dot" /> Male: {gender.male}</span>
              <span><span className="dot female-dot" /> Female: {gender.female}</span>
            </div>
          </div>

          {/* Age Distribution */}
          <div className="age-section">
            <div className="section-label">Age Groups</div>
            {Object.entries(age).map(([group, count]) => {
              const widthPct = Math.round((count / maxAge) * 100);
              const formattedGroup = group.replace('_', '-').replace('plus', '+');
              return (
                <div key={group} className="age-row">
                  <span className="age-label">{formattedGroup} yrs</span>
                  <div className="age-bar-track">
                    <div className="age-bar-fill" style={{ width: `${widthPct}%` }} />
                  </div>
                  <span className="age-count">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Import Modal */}
      {showImportModal && (
        <div className="modal-backdrop">
          <div className="modal-box import-modal">
            <h3>Upload / Paste footfall_cameras.json</h3>
            <p>Paste the JSON configuration sent by your CV team to automatically configure all cameras.</p>
            
            <textarea 
              className="import-textarea"
              rows={10}
              placeholder='Paste footfall_cameras.json content here...'
              value={importJsonText}
              onChange={(e) => setImportJsonText(e.target.value)}
            />

            {importStatus && <div className="import-status-msg">{importStatus}</div>}

            <div className="modal-actions">
              <button className="cancel-btn" onClick={() => setShowImportModal(false)}>Cancel</button>
              <button className="confirm-btn" onClick={handleImportSubmit} disabled={!importJsonText.trim()}>
                Import Configuration
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
