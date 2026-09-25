import { useState, useEffect, useMemo } from 'react';
import { getEmployeeMonitoringSummary, triggerFaceAlert, getEmployeeDetections } from '../api/api.js';
import './FaceAlertsView.css';

export default function FaceAlertsView({ cameras }) {
  const [summary, setSummary] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedEmp, setSelectedEmp] = useState(null);
  const [empDetections, setEmpDetections] = useState([]);
  const [loadingDetections, setLoadingDetections] = useState(false);

  // Filters State
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL'); // ALL, ACTIVE, INACTIVE
  const [cameraFilter, setCameraFilter] = useState('ALL');
  const [dateFilter, setDateFilter] = useState('');

  // Real-time alert toast
  const [recentAlert, setRecentAlert] = useState(null);
  const [simulating, setSimulating] = useState(false);

  const fetchSummary = () => {
    getEmployeeMonitoringSummary()
      .then((data) => {
        setSummary(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        console.error('Error fetching employee monitoring summary:', err);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleOpenEmployeeDetails = (emp) => {
    setSelectedEmp(emp);
    setLoadingDetections(true);
    getEmployeeDetections(emp.emp_id)
      .then((dets) => {
        setEmpDetections(Array.isArray(dets) ? dets : []);
      })
      .catch(console.error)
      .finally(() => setLoadingDetections(false));
  };

  const handleSimulateDetection = async (emp, targetCamId) => {
    setSimulating(true);
    const camId = targetCamId || (cameras && cameras.length > 0 ? cameras[0].cam_id : 'cam06');
    const camObj = (cameras || []).find((c) => c.cam_id === camId);
    const locationName = camObj ? `${camObj.name || camId} (${camObj.section_name || 'Showroom'})` : `Camera ${camId.upper()}`;

    const payload = {
      emp_id: emp.emp_id,
      emp_name: emp.emp_name,
      cam_id: camId,
      location: locationName,
      confidence: 0.97,
      snapshot_url: emp.face_url || 'https://via.placeholder.com/300x200?text=Face+Snapshot',
      timestamp: new Date().toISOString()
    };

    try {
      const res = await triggerFaceAlert(payload);
      setRecentAlert(res.alert);
      fetchSummary();
      if (selectedEmp && selectedEmp.emp_id === emp.emp_id) {
        handleOpenEmployeeDetails(emp);
      }
    } catch (err) {
      console.error('Alert trigger error:', err);
    } finally {
      setSimulating(false);
    }
  };

  // Filtered Employees
  const filteredSummary = useMemo(() => {
    return summary.filter((emp) => {
      const matchesSearch = 
        (emp.emp_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
        (emp.emp_id || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
        (emp.role || '').toLowerCase().includes(searchTerm.toLowerCase());

      const isActive = emp.total_detections > 0;
      const matchesStatus = 
        statusFilter === 'ALL' ? true :
        statusFilter === 'ACTIVE' ? isActive :
        !isActive;

      return matchesSearch && matchesStatus;
    });
  }, [summary, searchTerm, statusFilter]);

  // Overall KPIs
  const totalEmployees = summary.length;
  const activeEmployees = summary.filter((e) => e.total_detections > 0).length;
  const totalDetectionsToday = summary.reduce((acc, e) => acc + (e.total_detections || 0), 0);

  return (
    <div className="face-alerts-view animate-fade-in">
      {/* Header */}
      <div className="monitoring-header">
        <div>
          <div className="title-row">
            <h2>Employee Monitoring &amp; Presence Tracking</h2>
            <span className="live-pill">
              <span className="pulse-dot green"></span> Live Recognition Engine
            </span>
          </div>
          <p className="monitoring-subtitle">
            Real-time camera detection analytics for assigned showroom employees. Click any employee card to inspect detected camera locations, snapshots, and timestamps.
          </p>
        </div>
      </div>

      {/* Real-time Alert Toast Banner */}
      {recentAlert && (
        <div className="alert-toast-banner animate-pop">
          <div className="toast-icon">🚨</div>
          <div className="toast-content">
            <strong>{recentAlert.message}</strong>
            <span>
              Confidence: {Math.round((recentAlert.confidence || 0.95) * 100)}% • Location: {recentAlert.location} • {new Date(recentAlert.timestamp).toLocaleTimeString()}
            </span>
          </div>
          <button className="toast-close" onClick={() => setRecentAlert(null)}>✕</button>
        </div>
      )}

      {/* KPI Cards */}
      <div className="monitoring-kpi-grid">
        <div className="monitoring-kpi-card purple">
          <div className="kpi-icon">👥</div>
          <div className="kpi-details">
            <span className="kpi-label">Assigned Employees</span>
            <span className="kpi-num">{totalEmployees}</span>
          </div>
        </div>

        <div className="monitoring-kpi-card green">
          <div className="kpi-icon">🟢</div>
          <div className="kpi-details">
            <span className="kpi-label">Active On Floor</span>
            <span className="kpi-num">{activeEmployees}</span>
          </div>
        </div>

        <div className="monitoring-kpi-card blue">
          <div className="kpi-icon">📷</div>
          <div className="kpi-details">
            <span className="kpi-label">Total Detections Today</span>
            <span className="kpi-num">{totalDetectionsToday}</span>
          </div>
        </div>

        <div className="monitoring-kpi-card amber">
          <div className="kpi-icon">📹</div>
          <div className="kpi-details">
            <span className="kpi-label">Showroom Cameras</span>
            <span className="kpi-num">{(cameras || []).length || 27}</span>
          </div>
        </div>
      </div>

      {/* Controls & Search */}
      <div className="monitoring-controls-bar">
        <div className="search-group">
          <span className="search-icon">🔍</span>
          <input 
            type="text" 
            placeholder="Search employee by name (e.g. Gaurav, Rahul), ID, or role..." 
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          {searchTerm && <button className="clear-btn" onClick={() => setSearchTerm('')}>✕</button>}
        </div>

        <div className="filter-group">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="filter-select">
            <option value="ALL">All Statuses</option>
            <option value="ACTIVE">🟢 Active On Floor</option>
            <option value="INACTIVE">⚪ Not Seen Today</option>
          </select>
        </div>
      </div>

      {/* Employee Cards Grid */}
      {loading ? (
        <div className="monitoring-loading">
          <div className="spinner large"></div>
          <p>Loading employee presence &amp; camera detection logs...</p>
        </div>
      ) : filteredSummary.length === 0 ? (
        <div className="monitoring-empty">
          <span className="empty-icon">👥</span>
          <h4>No Employees Found</h4>
          <p>Assign employees in the "Assign Employee" section to enable real-time camera presence monitoring.</p>
        </div>
      ) : (
        <div className="employee-cards-grid">
          {filteredSummary.map((emp) => {
            const hasDetections = emp.total_detections > 0;
            const lastSeenTime = emp.last_seen_timestamp ? new Date(emp.last_seen_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : null;

            return (
              <div 
                key={emp.emp_id} 
                className="employee-card hover-lift"
                onClick={() => handleOpenEmployeeDetails(emp)}
              >
                <div className="card-top">
                  <div className="emp-avatar-wrapper">
                    {emp.face_url ? (
                      <img src={emp.face_url} alt={emp.emp_name} className="emp-card-avatar" />
                    ) : (
                      <div className="emp-card-avatar placeholder">👤</div>
                    )}
                    <span className={`status-dot-badge ${hasDetections ? 'online' : 'offline'}`} />
                  </div>

                  <div className="emp-card-info">
                    <h4 className="emp-card-name">{emp.emp_name}</h4>
                    <div className="emp-card-meta">
                      <span className="badge emp-id-tag">{emp.emp_id}</span>
                      <span className="role-tag">{emp.role}</span>
                    </div>
                  </div>
                </div>

                <div className="card-status-banner">
                  {hasDetections ? (
                    <div className="status-active">
                      <span className="dot pulse"></span>
                      <span>Last seen at <strong>{emp.last_seen_location || emp.last_seen_camera || 'Camera'}</strong> ({lastSeenTime})</span>
                    </div>
                  ) : (
                    <div className="status-inactive">
                      <span className="dot grey"></span>
                      <span>Not detected on cameras today</span>
                    </div>
                  )}
                </div>

                {/* Detected Cameras Pill List */}
                <div className="cameras-detected-row">
                  <span className="row-label">Cameras:</span>
                  {emp.detected_cameras && emp.detected_cameras.length > 0 ? (
                    <div className="cam-pills">
                      {emp.detected_cameras.map((c) => (
                        <span key={c} className="cam-pill">📷 {c.toUpperCase()}</span>
                      ))}
                    </div>
                  ) : (
                    <span className="no-cams">None detected</span>
                  )}
                </div>

                {/* Footer Action */}
                <div className="card-footer">
                  <span className="det-count">📊 {emp.total_detections} Detections</span>
                  <button className="view-details-btn">View Monitoring Details ➔</button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Employee Details & Detection History Modal */}
      {selectedEmp && (
        <div className="modal-backdrop" onClick={() => setSelectedEmp(null)}>
          <div className="modal-content emp-monitoring-modal animate-pop" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-emp-profile">
                {selectedEmp.face_url ? (
                  <img src={selectedEmp.face_url} alt={selectedEmp.emp_name} className="modal-avatar" />
                ) : (
                  <div className="modal-avatar placeholder">👤</div>
                )}
                <div>
                  <h3>{selectedEmp.emp_name}</h3>
                  <div className="modal-tags">
                    <span className="badge emp-id-tag">{selectedEmp.emp_id}</span>
                    <span className="badge role-tag">{selectedEmp.role}</span>
                    <span className="badge shift-tag">{selectedEmp.shift || 'Morning Shift'}</span>
                  </div>
                </div>
              </div>
              <button className="modal-close" onClick={() => setSelectedEmp(null)}>✕</button>
            </div>

            <div className="modal-body">
              {/* Top Stats Banner inside Modal */}
              <div className="modal-stats-banner">
                <div className="modal-stat">
                  <span className="stat-num">{selectedEmp.total_detections}</span>
                  <span className="stat-label">Total Detections</span>
                </div>
                <div className="modal-stat">
                  <span className="stat-num">{selectedEmp.unique_cameras_count}</span>
                  <span className="stat-label">Cameras Detected</span>
                </div>
                <div className="modal-stat">
                  <span className="stat-num">{selectedEmp.last_seen_location || 'N/A'}</span>
                  <span className="stat-label">Last Location</span>
                </div>
              </div>

              {/* Cameras Detected List */}
              <div className="modal-section">
                <h4>Detected Camera Locations</h4>
                <div className="detected-cameras-grid">
                  {(cameras || []).map((cam) => {
                    const isDetected = selectedEmp.detected_cameras?.includes(cam.cam_id);
                    return (
                      <div 
                        key={cam.cam_id} 
                        className={`cam-location-card ${isDetected ? 'detected' : 'normal'}`}
                        onClick={() => handleSimulateDetection(selectedEmp, cam.cam_id)}
                        title={`Click to simulate CV detection on ${cam.name || cam.cam_id}`}
                      >
                        <span className="cam-icon">{isDetected ? '🎥' : '📹'}</span>
                        <div className="cam-info">
                          <span className="cam-name">{cam.name || cam.cam_id}</span>
                          <span className="cam-sec">{cam.section_name || 'Showroom Floor'}</span>
                        </div>
                        {isDetected ? (
                          <span className="badge active-badge">Detected</span>
                        ) : (
                          <span className="badge sim-btn-sm">+ Test Detect</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Snapshots & Detection History Table */}
              <div className="modal-section">
                <div className="section-title-controls">
                  <h4>Camera Snapshots &amp; Detection History Log</h4>
                  <div className="table-filters">
                    <select 
                      value={cameraFilter} 
                      onChange={(e) => setCameraFilter(e.target.value)}
                      className="filter-select-sm"
                    >
                      <option value="ALL">All Cameras</option>
                      {(selectedEmp.detected_cameras || []).map((c) => (
                        <option key={c} value={c}>{c.toUpperCase()}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {loadingDetections ? (
                  <div className="loading-state-sm">
                    <div className="spinner"></div>
                    <span>Loading detection history logs...</span>
                  </div>
                ) : empDetections.length === 0 ? (
                  <div className="empty-state-sm">
                    <p>No detection logs recorded for {selectedEmp.emp_name} yet.</p>
                    <button 
                      className="btn-sim-lg"
                      onClick={() => handleSimulateDetection(selectedEmp)}
                      disabled={simulating}
                    >
                      {simulating ? 'Simulating CV Detection...' : '🚀 Trigger Test Detection Event'}
                    </button>
                  </div>
                ) : (
                  <div className="detections-table-wrapper">
                    <table className="detections-table">
                      <thead>
                        <tr>
                          <th>Snapshot</th>
                          <th>Camera / Location</th>
                          <th>Confidence</th>
                          <th>Timestamp</th>
                        </tr>
                      </thead>
                      <tbody>
                        {empDetections
                          .filter((d) => cameraFilter === 'ALL' || d.cam_id === cameraFilter)
                          .map((det) => (
                            <tr key={det.id}>
                              <td>
                                {det.snapshot_url ? (
                                  <a href={det.snapshot_url} target="_blank" rel="noreferrer">
                                    <img src={det.snapshot_url} alt="Face Snapshot" className="det-snapshot-thumb" />
                                  </a>
                                ) : (
                                  <span className="no-snap">📸 Snapshot</span>
                                )}
                              </td>
                              <td>
                                <div className="location-cell">
                                  <span className="loc-name">{det.location}</span>
                                  <span className="badge cam-tag">{det.cam_id.toUpperCase()}</span>
                                </div>
                              </td>
                              <td>
                                <span className="confidence-pill">
                                  {Math.round((det.confidence || 0.95) * 100)}% Match
                                </span>
                              </td>
                              <td>
                                <span className="time-text">
                                  {det.timestamp ? new Date(det.timestamp).toLocaleString() : 'Just now'}
                                </span>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>

            <div className="modal-footer">
              <button 
                className="btn-sim-action"
                onClick={() => handleSimulateDetection(selectedEmp)}
                disabled={simulating}
              >
                {simulating ? 'Processing CV Event...' : '⚡ Simulate CV Detection Event'}
              </button>
              <button className="btn-primary" onClick={() => setSelectedEmp(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
