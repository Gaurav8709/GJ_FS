import { useState, useEffect, useCallback } from 'react';
import { getCameras, getFloors } from '../api/api.js';
import Sidebar from '../components/Sidebar.jsx';
import StatsBar from '../components/StatsBar.jsx';
import FootfallView from '../components/FootfallView.jsx';
import FaceAlertsView from '../components/FaceAlertsView.jsx';
import ForensicsView from '../components/ForensicsView.jsx';
import HeatmapView from '../components/HeatmapView.jsx';
import CameraOnboardingView from '../components/CameraOnboardingView.jsx';
import './Dashboard.css';

export default function Dashboard({ user, onLogout }) {
  /* ---- state ---- */
  const [cameras, setCameras] = useState([]);
  const [floors, setFloors] = useState([]);
  const [activeView, setActiveView] = useState('footfall');   // footfall | camera-onboarding | face-alerts | forensics | heatmaps
  const [selectedCam, setSelectedCam] = useState(null);
  const [filterFloor, setFilterFloor] = useState(null);
  const [filterSection, setFilterSection] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const refreshCameras = useCallback(() => {
    getCameras().then(setCameras).catch(() => {});
  }, []);

  /* ---- initial fetch ---- */
  useEffect(() => {
    refreshCameras();
    getFloors().then(setFloors).catch(() => {});
  }, [refreshCameras]);

  /* ---- poll camera status ---- */
  useEffect(() => {
    import('../api/api.js').then(({ getCameraStatus }) => {
      const pollStatus = () => {
        getCameraStatus().then((statuses) => {
          const list = Array.isArray(statuses) ? statuses : statuses.cameras || [];
          setCameras(prev => prev.map(cam => {
            const stat = list.find(s => s.cam_id === cam.cam_id);
            if (!stat) return cam;
            return {
              ...cam,
              status: stat.online ? 'online' : 'offline',
              detected: stat.total_detected || 0,
              person_count: stat.total_detected || 0,
              has_alert: stat.has_alert || false
            };
          }));
        }).catch(() => {});
      };
      const timer = setInterval(pollStatus, 5000);
      return () => clearInterval(timer);
    });
  }, []);

  /* ---- handlers ---- */
  const handleNav = useCallback((view) => {
    setActiveView(view);
    setSelectedCam(null);
  }, []);

  const handleFloorFilter = useCallback((floorId) => {
    setFilterFloor(floorId);
    setFilterSection(null);
  }, []);

  const handleSectionFilter = useCallback((sectionId) => {
    setFilterSection(sectionId);
  }, []);

  const handleCameraClick = useCallback((camId) => {
    const cam = cameras.find((c) => c.id === camId || c.camera_id === camId);
    if (cam) setSelectedCam(cam);
  }, [cameras]);

  /* ---- render content ---- */
  const renderContent = () => {
    switch (activeView) {
      case 'camera-onboarding':
        return <CameraOnboardingView cameras={cameras} floors={floors} onRefresh={refreshCameras} />;
      case 'footfall':
        return <FootfallView cameras={cameras} filterFloor={filterFloor} filterSection={filterSection} />;
      case 'face-alerts':
        return <FaceAlertsView cameras={cameras} filterFloor={filterFloor} filterSection={filterSection} />;
      case 'forensics':
        return <ForensicsView cameras={cameras} />;
      case 'heatmaps':
        return <HeatmapView cameras={cameras} filterFloor={filterFloor} filterSection={filterSection} />;
      default:
        return <FootfallView cameras={cameras} filterFloor={filterFloor} filterSection={filterSection} />;
    }
  };

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dashboard-header">
        <div className="header-left">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarOpen((p) => !p)}
            aria-label="Toggle sidebar"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <div className="header-brand">
            <svg className="header-logo-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
            <span className="header-brand-text">GJ Fashion <span className="header-brand-ai">AI</span></span>
          </div>
        </div>

        <StatsBar cameras={cameras} />

        <div className="header-right">
          {/* User menu */}
          <div className="header-user">
            <div className="header-avatar">
              {(user?.username || 'U')[0].toUpperCase()}
            </div>
            <span className="header-username">{user?.username || 'User'}</span>
            <button className="header-logout" onClick={onLogout} title="Sign out">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* Body */}
      <div className="dashboard-body">
        <Sidebar
          isOpen={sidebarOpen}
          floors={floors}
          cameras={cameras}
          activeView={activeView}
          filterFloor={filterFloor}
          filterSection={filterSection}
          onNav={handleNav}
          onFloorFilter={handleFloorFilter}
          onSectionFilter={handleSectionFilter}
          onCameraClick={handleCameraClick}
        />
        <main className={`dashboard-main ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
          {renderContent()}
        </main>
      </div>
    </div>
  );
}
