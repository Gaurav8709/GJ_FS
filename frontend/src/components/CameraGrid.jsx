import CameraCard from './CameraCard.jsx';
import './CameraGrid.css';

export default function CameraGrid({ cameras, onCameraClick }) {
  if (!cameras || cameras.length === 0) {
    return (
      <div className="camera-grid-empty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
          <line x1="3" y1="9" x2="21" y2="9" />
          <line x1="9" y1="21" x2="9" y2="9" />
        </svg>
        <h3>No zones found</h3>
        <p>Select a floor or section from the sidebar to view monitored areas.</p>
      </div>
    );
  }

  return (
    <div className="camera-grid-wrapper animate-fade-in">
      <div className="camera-grid-header">
        <h2 className="camera-grid-title">Monitoring Grid</h2>
        <span className="camera-grid-count">{cameras.length} zone{cameras.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="camera-grid">
        {cameras.map((cam, idx) => (
          <CameraCard
            key={cam.id || cam.camera_id || idx}
            camera={cam}
            onClick={() => onCameraClick(cam)}
            style={{ animationDelay: `${idx * 0.04}s` }}
          />
        ))}
      </div>
    </div>
  );
}
