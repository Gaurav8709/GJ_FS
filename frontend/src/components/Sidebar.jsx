import { useState, useMemo } from 'react';
import './Sidebar.css';

/* SVG icon helper */
const Icon = ({ d, size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    {Array.isArray(d) ? d.map((p, i) => <path key={i} d={p} />) : <path d={d} />}
  </svg>
);

const NAV_ITEMS = [
  { id: 'grid',              label: 'Dashboard',         icon: ['M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z'] },
  { id: 'camera-onboarding', label: 'Camera Onboarding', icon: ['M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z'] },
  { id: 'footfall',          label: 'Footfall',          icon: ['M18 20V10M12 20V4M6 20v-6'] },
  { id: 'face-alerts',       label: 'Employee Monitoring', icon: ['M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2', 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z'] },
  { id: 'forensics',         label: 'Assign Employee',   icon: ['M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z'] },
  { id: 'heatmaps',          label: 'Heatmaps',          icon: ['M1 6v12M23 6v12M1 12h22'] },
  { id: 'workers',           label: 'Workers',           icon: ['M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2', 'M9 7a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M23 21v-2a4 4 0 0 0-3-3.87', 'M16 3.13a4 4 0 0 1 0 7.75'] },
  { id: 'alerts',            label: 'Alerts',            icon: ['M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z', 'M12 9v4', 'M12 17h.01'] },
];

export default function Sidebar({
  isOpen, floors, cameras, activeView,
  filterFloor, filterSection,
  onNav, onFloorFilter, onSectionFilter, onCameraClick,
  alerts,
}) {
  const [expandedFloors, setExpandedFloors] = useState({});

  /* group cameras by floor and section */
  const floorTree = useMemo(() => {
    const tree = (floors || []).map((f) => {
      const sections = (f.sections || []).map((s) => ({
        ...s,
        cameras: (cameras || []).filter(
          (c) => c.section_id === s.id || c.section_id === s.section_id
        ),
        alertCount: (alerts || []).filter(
          (a) => !a.acknowledged && (a.section_id === s.id || a.section_id === s.section_id)
        ).length,
      }));
      return { ...f, sections };
    });
    return tree;
  }, [floors, cameras, alerts]);

  const toggleFloor = (fid) => {
    setExpandedFloors((prev) => ({ ...prev, [fid]: !prev[fid] }));
  };

  return (
    <aside className={`sidebar ${isOpen ? 'sidebar--open' : 'sidebar--closed'}`}>
      {/* Navigation */}
      <nav className="sidebar-nav">
        <div className="sidebar-section-label">Navigation</div>
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`sidebar-nav-item ${activeView === item.id ? 'active' : ''}`}
            onClick={() => onNav(item.id)}
          >
            <Icon d={item.icon} />
            <span>{item.label}</span>
            {item.id === 'alerts' && alerts?.filter((a) => !a.acknowledged).length > 0 && (
              <span className="sidebar-badge">{alerts.filter((a) => !a.acknowledged).length}</span>
            )}
          </button>
        ))}
      </nav>

      {/* Floor / Section tree */}
      <div className="sidebar-tree">
        <div className="sidebar-section-label">Floors &amp; Sections</div>

        <button
          className={`sidebar-nav-item ${!filterFloor && !filterSection ? 'active' : ''}`}
          onClick={() => { onFloorFilter(null); onSectionFilter(null); }}
        >
          <Icon d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" />
          <span>All Cameras</span>
          <span className="sidebar-count">{cameras?.length || 0}</span>
        </button>

        {floorTree.map((floor) => {
          const fid = floor.id || floor.floor_id;
          const expanded = expandedFloors[fid];
          const floorAlerts = floor.sections?.reduce((s, sec) => s + (sec.alertCount || 0), 0) || 0;

          return (
            <div key={fid} className="sidebar-floor">
              <button
                className={`sidebar-nav-item sidebar-floor-btn ${filterFloor === fid ? 'active' : ''}`}
                onClick={() => { toggleFloor(fid); onFloorFilter(fid); }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  className={`sidebar-chevron ${expanded ? 'expanded' : ''}`}>
                  <polyline points="9 18 15 12 9 6" />
                </svg>
                <Icon d={['M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16', 'M1 21h22', 'M9 7h6', 'M9 11h6', 'M9 15h2']} size={16} />
                <span>{floor.name || `Floor ${fid}`}</span>
                {floorAlerts > 0 && <span className="sidebar-badge red">{floorAlerts}</span>}
              </button>

              {expanded && floor.sections?.map((section) => {
                const sid = section.id || section.section_id;
                return (
                  <div key={sid} className="sidebar-section">
                    <button
                      className={`sidebar-nav-item sidebar-section-btn ${filterSection === sid ? 'active' : ''}`}
                      onClick={() => onSectionFilter(sid)}
                    >
                      <Icon d="M4 4h16v16H4z" size={14} />
                      <span>{section.name || `Section ${sid}`}</span>
                      {section.alertCount > 0 && (
                        <span className="sidebar-badge red">{section.alertCount}</span>
                      )}
                      <span className="sidebar-count">{section.cameras?.length || 0}</span>
                    </button>

                    {/* Camera list under section */}
                    {section.cameras?.map((cam) => {
                      const cid = cam.id || cam.camera_id;
                      return (
                        <button
                          key={cid}
                          className="sidebar-nav-item sidebar-cam-btn"
                          onClick={() => onCameraClick(cid)}
                        >
                          <span className={`status-dot ${cam.status === 'offline' ? 'offline' : 'online'}`} />
                          <span>{cam.name || `Cam ${cid}`}</span>
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="sidebar-footer">
        <div className="sidebar-footer-text">
          <span className="status-dot online" />
          System Online
        </div>
      </div>
    </aside>
  );
}
