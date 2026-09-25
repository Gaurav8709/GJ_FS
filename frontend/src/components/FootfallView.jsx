import { useState, useEffect } from 'react';
import { getFootfallStats, updateFootfall } from '../api/api.js';
import './FootfallView.css';

export default function FootfallView({ cameras }) {
  const [stats, setStats] = useState(null);
  const [selectedCam, setSelectedCam] = useState('');
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);

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

  return (
    <div className="footfall-view animate-fade-in">
      <div className="footfall-header">
        <div>
          <h2>Footfall Analytics & Demographics</h2>
          <p className="footfall-subtitle">Real-time listener tracking for showroom entries, exits, gender, and age distribution.</p>
        </div>
        <div className="footfall-controls">
          <select 
            className="cam-select" 
            value={selectedCam} 
            onChange={(e) => setSelectedCam(e.target.value)}
          >
            <option value="">All Cameras</option>
            {(cameras || []).map((c) => (
              <option key={c.id || c.cam_id} value={c.cam_id}>{c.name || c.cam_id}</option>
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

          {/* Age Group Distribution */}
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
    </div>
  );
}
