import { useState, useEffect } from 'react';
import { 
  getFootfallStats, 
  toggleCameraAnalytics, 
  getFootfallCamerasConfig, 
  importFootfallCamerasConfig 
} from '../api/api.js';
import './FootfallView.css';

/* ----------------------------------------------------
   Entries vs Exits SVG Line Trend Chart Component
   ---------------------------------------------------- */
function EntriesExitsLineChart({ timeSeries = [] }) {
  const data = (timeSeries && timeSeries.length > 0) ? timeSeries.slice(-15) : [
    { timestamp: '08:50', entries: 0, exits: 0 },
    { timestamp: '08:55', entries: 0, exits: 0 },
  ];

  const maxVal = Math.max(...data.map(d => Math.max(d.entries || 0, d.exits || 0)), 10);
  const width = 680;
  const height = 220;
  const paddingLeft = 45;
  const paddingRight = 20;
  const paddingTop = 25;
  const paddingBottom = 40;
  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const pointsEntries = data.map((d, i) => {
    const x = paddingLeft + (i / Math.max(1, data.length - 1)) * chartWidth;
    const y = paddingTop + chartHeight - ((d.entries || 0) / maxVal) * chartHeight;
    return { x, y, val: d.entries || 0, time: d.timestamp, cam: d.cam_id };
  });

  const pointsExits = data.map((d, i) => {
    const x = paddingLeft + (i / Math.max(1, data.length - 1)) * chartWidth;
    const y = paddingTop + chartHeight - ((d.exits || 0) / maxVal) * chartHeight;
    return { x, y, val: d.exits || 0, time: d.timestamp, cam: d.cam_id };
  });

  const pathEntries = pointsEntries.reduce((acc, p, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${p.x},${p.y}`, '');
  const pathExits = pointsExits.reduce((acc, p, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${p.x},${p.y}`, '');

  const areaEntries = `${pathEntries} L ${pointsEntries[pointsEntries.length - 1].x},${paddingTop + chartHeight} L ${pointsEntries[0].x},${paddingTop + chartHeight} Z`;
  const areaExits = `${pathExits} L ${pointsExits[pointsExits.length - 1].x},${paddingTop + chartHeight} L ${pointsExits[0].x},${paddingTop + chartHeight} Z`;

  const yTicks = [0, Math.round(maxVal * 0.5), maxVal];

  return (
    <div className="line-chart-card">
      <div className="line-chart-header">
        <div>
          <h3>📈 Showroom Traffic Inflow (Entries) vs. Outflow (Exits)</h3>
          <p className="chart-sub">Real-time trend graph comparing customer entries (Green Line) vs exits (Red Line) over time.</p>
        </div>
        <div className="line-chart-legend">
          <span className="legend-item green">
            <span className="legend-line green"></span> 🟢 Entries (Inflow)
          </span>
          <span className="legend-item red">
            <span className="legend-line red"></span> 🔴 Exits (Outflow)
          </span>
        </div>
      </div>

      <div className="svg-responsive-container">
        <svg viewBox={`0 0 ${width} ${height}`} className="line-chart-svg">
          <defs>
            <linearGradient id="greenGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="redGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#ef4444" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {yTicks.map((tick, i) => {
            const y = paddingTop + chartHeight - (tick / maxVal) * chartHeight;
            return (
              <g key={i}>
                <line x1={paddingLeft} y1={y} x2={width - paddingRight} y2={y} stroke="rgba(255,255,255,0.08)" strokeDasharray="3,3" />
                <text x={paddingLeft - 8} y={y + 4} textAnchor="end" fill="#64748b" fontSize="10" fontWeight="600">{tick}</text>
              </g>
            );
          })}

          {/* Fill Areas */}
          <path d={areaEntries} fill="url(#greenGradient)" />
          <path d={areaExits} fill="url(#redGradient)" />

          {/* Lines */}
          <path d={pathEntries} fill="none" stroke="#10b981" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          <path d={pathExits} fill="none" stroke="#ef4444" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />

          {/* Entry Points */}
          {pointsEntries.map((p, i) => (
            <g key={`entry-${i}`} className="chart-point-group">
              <circle cx={p.x} cy={p.y} r="4.5" fill="#10b981" stroke="#0f172a" strokeWidth="2" />
              <title>{`Time: ${p.time} | Entries: +${p.val}`}</title>
            </g>
          ))}

          {/* Exit Points */}
          {pointsExits.map((p, i) => (
            <g key={`exit-${i}`} className="chart-point-group">
              <circle cx={p.x} cy={p.y} r="4.5" fill="#ef4444" stroke="#0f172a" strokeWidth="2" />
              <title>{`Time: ${p.time} | Exits: -${p.val}`}</title>
            </g>
          ))}

          {/* X Axis Labels */}
          {pointsEntries.map((p, i) => {
            const displayTime = (p.time || '').length > 8 ? p.time.split(' ')[1] || p.time : p.time;
            return (
              <text key={`xlabel-${i}`} x={p.x} y={height - 10} textAnchor="middle" fill="#94a3b8" fontSize="9" fontWeight="500">
                {displayTime}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

/* ----------------------------------------------------
   Age Distribution Donut SVG Chart Component
   ---------------------------------------------------- */
function AgeGroupDonutChart({ ageBreakdown = {} }) {
  const config = [
    { key: '18_25', label: '18–25 yrs', color: '#8b5cf6', val: ageBreakdown['18_25'] || 0 },
    { key: '26_35', label: '26–35 yrs', color: '#ec4899', val: ageBreakdown['26_35'] || 0 },
    { key: '36_50', label: '36–50 yrs', color: '#3b82f6', val: ageBreakdown['36_50'] || 0 },
    { key: '50_plus', label: '50+ yrs', color: '#f59e0b', val: ageBreakdown['50_plus'] || 0 },
    { key: '0_9', label: '0–9 yrs', color: '#64748b', val: ageBreakdown['0_9'] || 0 },
    { key: '10_17', label: '10–17 yrs', color: '#06b6d4', val: ageBreakdown['10_17'] || 0 },
  ];

  const total = config.reduce((sum, c) => sum + c.val, 0);
  const radius = 65;
  const circumference = 2 * Math.PI * radius;

  let accumulatedDash = 0;
  const slices = config.map((item) => {
    const pct = total > 0 ? item.val / total : 0;
    const dash = circumference * pct;
    const offset = -accumulatedDash;
    accumulatedDash += dash;
    const pctLabel = Math.round(pct * 100);
    return { ...item, pct, dash, offset, pctLabel };
  });

  return (
    <div className="donut-chart-box">
      <div className="donut-section-header">
        <h4>🍰 Age Groups Distribution (Pie / Donut)</h4>
        <span className="total-age-tag">Total Recorded: {total.toLocaleString()}</span>
      </div>

      <div className="donut-body">
        <div className="donut-svg-wrapper">
          <svg width="170" height="170" viewBox="0 0 200 200" className="donut-svg">
            <circle cx="100" cy="100" r={radius} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="24" />
            {total > 0 ? (
              slices.map((s) => (
                s.val > 0 && (
                  <circle
                    key={s.key}
                    cx="100"
                    cy="100"
                    r={radius}
                    fill="none"
                    stroke={s.color}
                    strokeWidth="24"
                    strokeDasharray={`${s.dash} ${circumference - s.dash}`}
                    strokeDashoffset={s.offset}
                    transform="rotate(-90 100 100)"
                    style={{ transition: 'stroke-dasharray 0.6s ease' }}
                  >
                    <title>{`${s.label}: ${s.val.toLocaleString()} (${s.pctLabel}%)`}</title>
                  </circle>
                )
              ))
            ) : (
              <circle cx="100" cy="100" r={radius} fill="none" stroke="#334155" strokeWidth="24" />
            )}
            <text x="100" y="95" textAnchor="middle" fill="#f8fafc" fontSize="20" fontWeight="800">{total.toLocaleString()}</text>
            <text x="100" y="115" textAnchor="middle" fill="#94a3b8" fontSize="10" fontWeight="600">VISITORS</text>
          </svg>
        </div>

        <div className="donut-legend-list">
          {slices.map((s) => (
            <div key={s.key} className={`legend-row ${s.val === 0 ? 'empty' : ''}`}>
              <div className="legend-left">
                <span className="legend-dot" style={{ backgroundColor: s.color }} />
                <span className="legend-name">{s.label}</span>
              </div>
              <div className="legend-right">
                <span className="legend-val">{s.val.toLocaleString()}</span>
                <span className="legend-pct" style={{ color: s.color }}>({s.pctLabel}%)</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ----------------------------------------------------
   Main FootfallView Page Component
   ---------------------------------------------------- */
export default function FootfallView({ cameras: initialCameras = [] }) {
  const [stats, setStats] = useState(null);
  const [selectedCam, setSelectedCam] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [loading, setLoading] = useState(true);
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
    getFootfallStats(selectedCam, startDate, endDate, startTime, endTime)
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, [selectedCam, startDate, endDate, startTime, endTime]);

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

  if (loading && !stats) {
    return <div className="footfall-loading">Loading Footfall Analytics...</div>;
  }

  const gender = stats?.gender_breakdown || { male: 0, female: 0 };
  const totalGender = (gender.male + gender.female) || 1;
  const malePercent = Math.round((gender.male / totalGender) * 100);
  const femalePercent = Math.round((gender.female / totalGender) * 100);

  const age = stats?.age_breakdown || { "0_9": 0, "10_17": 0, "18_25": 0, "26_35": 0, "36_50": 0, "50_plus": 0 };

  // Active Enabled Cameras for Footfall Analytics
  const activeFootfallCams = camList.filter((c) => c.footfall_enabled !== false);

  return (
    <div className="footfall-view animate-fade-in">
      {/* Top Header & Duration Controls */}
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

          {/* Camera Selection */}
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

          {/* Date & Time Duration Range Filter */}
          <div className="duration-filter-box">
            <div className="duration-field">
              <span className="duration-label">FROM:</span>
              <input 
                type="date" 
                className="duration-input date" 
                value={startDate} 
                onChange={(e) => setStartDate(e.target.value)}
                title="Start Date"
              />
              <input 
                type="time" 
                className="duration-input time" 
                value={startTime} 
                onChange={(e) => setStartTime(e.target.value)}
                title="Start Time"
              />
            </div>

            <div className="duration-field">
              <span className="duration-label">TO:</span>
              <input 
                type="date" 
                className="duration-input date" 
                value={endDate} 
                onChange={(e) => setEndDate(e.target.value)}
                title="End Date"
              />
              <input 
                type="time" 
                className="duration-input time" 
                value={endTime} 
                onChange={(e) => setEndTime(e.target.value)}
                title="End Time"
              />
            </div>

            {(startDate || endDate || startTime || endTime) && (
              <button 
                className="clear-duration-btn" 
                onClick={() => {
                  setStartDate('');
                  setEndDate('');
                  setStartTime('');
                  setEndTime('');
                }}
                title="Clear Date/Time Filter"
              >
                ✕ Clear
              </button>
            )}
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
          <div className="kpi-value">{(stats?.total_entries || 0).toLocaleString()}</div>
        </div>
        <div className="kpi-card red">
          <div className="kpi-title">Total Exits (-1)</div>
          <div className="kpi-value">{(stats?.total_exits || 0).toLocaleString()}</div>
        </div>
        <div className="kpi-card blue">
          <div className="kpi-title">Current Occupancy</div>
          <div className="kpi-value">{(stats?.net_current || 0).toLocaleString()}</div>
        </div>
      </div>

      {/* Real-time Inflow vs Outflow SVG Line Trend Chart */}
      <EntriesExitsLineChart timeSeries={stats?.time_series} />

      {/* Analytics Grid (Timestamp Bar Chart + Demographic Donut Analytics) */}
      <div className="footfall-grid">
        {/* Timestamp Bar Chart */}
        <div className="footfall-chart-card">
          <h3>📊 Footfall Timestamp Activity Bars</h3>
          <div className="bar-chart-container">
            {(stats?.time_series || []).slice(-12).map((item, idx) => {
              const heightPct = Math.min(100, Math.max(10, (item.entries || item.net || 0) * 12));
              const displayTime = (item.timestamp || '').length > 8 ? item.timestamp.split(' ')[1] || item.timestamp : item.timestamp;
              return (
                <div key={idx} className="bar-column">
                  <div className="bar-value">+{item.entries}</div>
                  <div className="bar-fill" style={{ height: `${heightPct}%` }} />
                  <div className="bar-label">{displayTime}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Demographics Breakdown & Age Donut Chart */}
        <div className="footfall-demo-card">
          <h3>👥 Demographics Breakdown Analytics</h3>

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
              <span><span className="dot male-dot" /> Male: {gender.male.toLocaleString()}</span>
              <span><span className="dot female-dot" /> Female: {gender.female.toLocaleString()}</span>
            </div>
          </div>

          {/* Age Group SVG Donut Chart Component */}
          <AgeGroupDonutChart ageBreakdown={age} />
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
