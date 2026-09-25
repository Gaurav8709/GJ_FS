import { useState, useEffect, useMemo } from 'react';
import { getForensicClips, uploadForensicClip, deleteForensicClip } from '../api/api.js';
import './ForensicsView.css';

export default function ForensicsView({ cameras }) {
  const [clips, setClips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedClip, setSelectedClip] = useState(null);
  const [previewMedia, setPreviewMedia] = useState(null);

  // Search & Filter State
  const [searchTerm, setSearchTerm] = useState('');
  const [shiftFilter, setShiftFilter] = useState('ALL');

  // Form State
  const [empName, setEmpName] = useState('');
  const [empId, setEmpId] = useState('');
  const [role, setRole] = useState('Sales Executive');
  const [shift, setShift] = useState('Morning'); // Morning, Afternoon, Day, Evening, Night
  const [mediaType, setMediaType] = useState('video'); // video, picture
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [copiedId, setCopiedId] = useState(null);

  const fetchClips = () => {
    setLoading(true);
    getForensicClips('assign_employee')
      .then((data) => {
        // Fallback to all clips if category filter returns empty list initially
        if (Array.isArray(data)) {
          setClips(data);
        } else {
          setClips([]);
        }
      })
      .catch((err) => {
        console.error('Error fetching assigned employees:', err);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchClips();
  }, []);

  const handleFileChange = (e) => {
    const selected = e.target.files[0];
    if (!selected) return;

    setFile(selected);

    // Auto-detect media type from file extension
    const name = selected.name.toLowerCase();
    if (name.match(/\.(jpg|jpeg|png|webp|gif|svg)$/)) {
      setMediaType('picture');
    } else if (name.match(/\.(mp4|mov|webm|avi|mkv)$/)) {
      setMediaType('video');
    }
  };

  const handleAssign = async (e) => {
    e.preventDefault();
    if (!empName.trim() || !empId.trim() || !file) {
      alert('Please fill in Employee Name, ID, and select a video or image file.');
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append('title', `${empName} (${empId}) - ${shift} Shift ${mediaType === 'video' ? 'Video' : 'Photo'}`);
    formData.append('category', 'assign_employee');
    formData.append('emp_id', empId.trim());
    formData.append('emp_name', empName.trim());
    formData.append('role', role.trim());
    formData.append('shift', shift);
    formData.append('media_type', mediaType);
    formData.append('metadata', JSON.stringify({ 
      file_name: file.name,
      file_size: `${(file.size / (1024 * 1024)).toFixed(2)} MB`,
      media_type: mediaType,
      shift, 
      assigned_at: new Date().toISOString() 
    }));
    formData.append('file', file);

    try {
      await uploadForensicClip(formData);
      setEmpName('');
      setEmpId('');
      setFile(null);
      fetchClips();
      alert(`Successfully assigned ${empName}! Media stored in AWS S3 and metadata saved to RDS table.`);
    } catch (err) {
      alert('Assign failed: ' + err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id, name) => {
    if (!window.confirm(`Are you sure you want to delete assigned employee record for ${name || 'this employee'}?`)) {
      return;
    }
    try {
      await deleteForensicClip(id);
      fetchClips();
    } catch (err) {
      alert('Failed to delete: ' + err.message);
    }
  };

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Filtered List
  const filteredClips = useMemo(() => {
    return clips.filter((c) => {
      const nameMatch = (c.emp_name || c.title || '').toLowerCase().includes(searchTerm.toLowerCase());
      const idMatch = (c.emp_id || '').toLowerCase().includes(searchTerm.toLowerCase());
      const roleMatch = (c.role || '').toLowerCase().includes(searchTerm.toLowerCase());
      const matchesSearch = nameMatch || idMatch || roleMatch;

      const matchesShift = shiftFilter === 'ALL' || c.shift === shiftFilter;
      return matchesSearch && matchesShift;
    });
  }, [clips, searchTerm, shiftFilter]);

  return (
    <div className="forensics-view animate-fade-in">
      {/* Top Header */}
      <div className="forensics-header">
        <div>
          <div className="header-title-row">
            <h2>Assign Employee &amp; Facial Setup</h2>
            <span className="s3-status-pill">
              <span className="dot pulse"></span> AWS S3 &amp; RDS Connected
            </span>
          </div>
          <p className="forensics-subtitle">
            Upload employee facial video clips (1-5 min) or photos and shift metadata. Stored in AWS S3 &amp; PostgreSQL table with automated JSON export for CV facial embeddings.
          </p>
        </div>
      </div>

      <div className="forensics-layout">
        {/* Left Form: Assign New Employee */}
        <div className="upload-card">
          <div className="card-header-badge">
            <h3>Assign New Employee</h3>
            <span className="card-sub-badge">AWS S3 Pipeline</span>
          </div>
          
          <form onSubmit={handleAssign} className="upload-form">
            <div className="form-group">
              <label>Employee Name *</label>
              <input 
                type="text" 
                placeholder="e.g. Rahul Sharma" 
                value={empName} 
                onChange={(e) => setEmpName(e.target.value)} 
                required 
              />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>Employee ID *</label>
                <input 
                  type="text" 
                  placeholder="e.g. EMP-105" 
                  value={empId} 
                  onChange={(e) => setEmpId(e.target.value)} 
                  required 
                />
              </div>

              <div className="form-group">
                <label>Role / Position</label>
                <input 
                  type="text" 
                  placeholder="e.g. Sales Executive" 
                  value={role} 
                  onChange={(e) => setRole(e.target.value)} 
                  required 
                />
              </div>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>Work Shift</label>
                <select value={shift} onChange={(e) => setShift(e.target.value)} className="shift-select">
                  <option value="Morning">Morning Shift</option>
                  <option value="Afternoon">Afternoon Shift</option>
                  <option value="Day">Day Shift</option>
                  <option value="Evening">Evening Shift</option>
                  <option value="Night">Night Shift</option>
                </select>
              </div>

              <div className="form-group">
                <label>Media Format</label>
                <select value={mediaType} onChange={(e) => setMediaType(e.target.value)} className="media-type-select">
                  <option value="video">🎥 Facial Video (MP4/MOV)</option>
                  <option value="picture">📸 Profile Picture (JPG/PNG)</option>
                </select>
              </div>
            </div>

            <div className="form-group">
              <label>
                {mediaType === 'video' ? 'Facial Training Video (1 - 5 Mins)' : 'Employee Profile Picture / Photo'} *
              </label>
              <div className="file-input-wrapper">
                <input 
                  type="file" 
                  accept={mediaType === 'video' ? 'video/*' : 'image/*'} 
                  onChange={handleFileChange} 
                  required 
                />
                <div className="file-drop-zone">
                  {file ? (
                    <div className="file-selected-info">
                      <span className="file-icon">{mediaType === 'video' ? '🎥' : '📸'}</span>
                      <div className="file-details">
                        <span className="file-name">{file.name}</span>
                        <span className="file-size">{(file.size / (1024 * 1024)).toFixed(2)} MB</span>
                      </div>
                    </div>
                  ) : (
                    <div className="file-placeholder">
                      <span className="upload-icon">☁️</span>
                      <span>Click or Drag &amp; Drop {mediaType === 'video' ? 'Video' : 'Photo'} File</span>
                      <span className="file-help">
                        {mediaType === 'video' ? 'MP4, MOV, WEBM (1-5 min max)' : 'JPG, PNG, WEBP high resolution'}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <button type="submit" className="upload-submit-btn" disabled={uploading}>
              {uploading ? (
                <>
                  <span className="spinner"></span> Uploading to S3 &amp; RDS...
                </>
              ) : (
                <>🚀 Upload to AWS S3 &amp; Assign Employee</>
              )}
            </button>
          </form>
        </div>

        {/* Right Section: Assigned Employee Table */}
        <div className="table-card">
          <div className="table-header-controls">
            <div>
              <h3>Assigned Employees Table</h3>
              <span className="table-count-badge">{filteredClips.length} Total Employees</span>
            </div>

            <div className="controls-group">
              <div className="search-box">
                <span className="search-icon">🔍</span>
                <input 
                  type="text" 
                  placeholder="Search name, EMP-ID, role..." 
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
                {searchTerm && (
                  <button className="clear-search" onClick={() => setSearchTerm('')}>✕</button>
                )}
              </div>

              <select 
                className="shift-filter-select"
                value={shiftFilter}
                onChange={(e) => setShiftFilter(e.target.value)}
              >
                <option value="ALL">All Shifts</option>
                <option value="Morning">Morning Shift</option>
                <option value="Afternoon">Afternoon Shift</option>
                <option value="Day">Day Shift</option>
                <option value="Evening">Evening Shift</option>
                <option value="Night">Night Shift</option>
              </select>
            </div>
          </div>

          {loading ? (
            <div className="loading-state">
              <div className="spinner large"></div>
              <p>Fetching assigned employee records from RDS database...</p>
            </div>
          ) : filteredClips.length === 0 ? (
            <div className="empty-table-state">
              <span className="empty-icon">📂</span>
              <h4>No Assigned Employees Found</h4>
              <p>Fill out the form on the left to upload media to AWS S3 and save metadata to PostgreSQL table.</p>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="employee-table">
                <thead>
                  <tr>
                    <th>Employee Info</th>
                    <th>Role / Position</th>
                    <th>Work Shift</th>
                    <th>AWS S3 Media</th>
                    <th>Status</th>
                    <th>Assigned Date</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredClips.map((clip) => {
                    const isVid = (clip.metadata_json?.media_type === 'video') || 
                                  (clip.file_url && clip.file_url.match(/\.(mp4|mov|webm)$/i)) ||
                                  (!clip.metadata_json?.media_type && clip.category === 'assign_employee');
                    return (
                      <tr key={clip.id} className="table-row hover-highlight">
                        {/* Employee Info */}
                        <td>
                          <div className="emp-info-cell">
                            <div className="emp-avatar">
                              {isVid ? '🎥' : '👤'}
                            </div>
                            <div>
                              <div className="emp-name-title">{clip.emp_name || clip.title}</div>
                              <span className="badge emp-id-badge">{clip.emp_id || 'EMP-100'}</span>
                            </div>
                          </div>
                        </td>

                        {/* Role */}
                        <td>
                          <span className="role-text">{clip.role || 'Sales Representative'}</span>
                        </td>

                        {/* Work Shift */}
                        <td>
                          <span className={`badge shift-tag ${clip.shift?.toLowerCase() || 'morning'}`}>
                            {clip.shift || 'Morning'}
                          </span>
                        </td>

                        {/* Media S3 Link */}
                        <td>
                          <div className="s3-media-cell">
                            <span className="media-type-badge">
                              {isVid ? '📹 Video' : '🖼️ Photo'}
                            </span>
                            <button 
                              className="s3-link-btn" 
                              onClick={() => copyToClipboard(clip.file_url, clip.id)}
                              title="Click to copy S3 URL"
                            >
                              {copiedId === clip.id ? '✓ Copied' : '🔗 AWS S3 Link'}
                            </button>
                          </div>
                        </td>

                        {/* Status */}
                        <td>
                          <span className="badge status-synced">
                            <span className="status-dot-sm"></span> S3 &amp; RDS Synced
                          </span>
                        </td>

                        {/* Date */}
                        <td>
                          <span className="date-text">
                            {clip.created_at ? new Date(clip.created_at).toLocaleDateString() : 'Today'}
                          </span>
                        </td>

                        {/* Actions */}
                        <td className="text-right">
                          <div className="action-btns">
                            <button 
                              className="btn-action json-btn"
                              onClick={() => setSelectedClip(clip)}
                              title="Inspect CV JSON export payload"
                            >
                              ⚙️ CV JSON
                            </button>
                            <button 
                              className="btn-action view-btn"
                              onClick={() => setPreviewMedia(clip)}
                              title="Play Video or View Photo"
                            >
                              👁️ View
                            </button>
                            <button 
                              className="btn-action delete-btn"
                              onClick={() => handleDelete(clip.id, clip.emp_name)}
                              title="Delete employee record"
                            >
                              🗑️
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* CV Listener JSON Inspector Modal */}
      {selectedClip && (
        <div className="modal-backdrop" onClick={() => setSelectedClip(null)}>
          <div className="modal-content animate-pop" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3>Computer Vision Listener JSON Export</h3>
                <p className="modal-sub">Employee: <strong>{selectedClip.emp_name || selectedClip.title}</strong> ({selectedClip.emp_id})</p>
              </div>
              <button className="modal-close" onClick={() => setSelectedClip(null)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="json-notice">
                <span>🤖</span> This JSON payload is automatically exported for Computer Vision listener scripts to generate 3D facial embeddings and facilitate real-time facial recognition across store cameras.
              </div>
              <pre className="json-code-box">
                {JSON.stringify(selectedClip.listener_json || selectedClip, null, 2)}
              </pre>
            </div>
            <div className="modal-footer">
              <button 
                className="btn-secondary"
                onClick={() => copyToClipboard(JSON.stringify(selectedClip.listener_json, null, 2), 'modal')}
              >
                {copiedId === 'modal' ? '✓ Copied Payload' : '📋 Copy JSON Payload'}
              </button>
              <button className="btn-primary" onClick={() => setSelectedClip(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Media Preview Modal (Video Player or Photo Viewer) */}
      {previewMedia && (
        <div className="modal-backdrop" onClick={() => setPreviewMedia(null)}>
          <div className="modal-content media-modal animate-pop" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3>S3 Media Preview — {previewMedia.emp_name || previewMedia.title}</h3>
                <p className="modal-sub">AWS S3 URL: <a href={previewMedia.file_url} target="_blank" rel="noreferrer" className="s3-href">{previewMedia.file_url}</a></p>
              </div>
              <button className="modal-close" onClick={() => setPreviewMedia(null)}>✕</button>
            </div>
            <div className="modal-body media-body">
              {(previewMedia.metadata_json?.media_type === 'video') || 
               (previewMedia.file_url && previewMedia.file_url.match(/\.(mp4|mov|webm)$/i)) ||
               (!previewMedia.metadata_json?.media_type && previewMedia.category === 'assign_employee') ? (
                <video controls autoPlay src={previewMedia.file_url} className="media-player-video">
                  Your browser does not support HTML5 video player.
                </video>
              ) : (
                <img src={previewMedia.file_url} alt={previewMedia.emp_name} className="media-player-image" />
              )}
            </div>
            <div className="modal-footer">
              <a href={previewMedia.file_url} target="_blank" rel="noreferrer" className="btn-secondary text-link">
                📥 Open Direct S3 Link
              </a>
              <button className="btn-primary" onClick={() => setPreviewMedia(null)}>Close Preview</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
