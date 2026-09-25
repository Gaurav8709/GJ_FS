import { useState, useEffect } from 'react';
import { getWorkers, createWorker, getAssignments, assignWorker, deleteAssignment, getCameras } from '../api/api.js';
import './WorkerAssignment.css';

export default function WorkerAssignment() {
  const [workers, setWorkers] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [cameras, setCameras] = useState([]);
  
  // New Worker Form
  const [newWorkerName, setNewWorkerName] = useState('');
  const [newWorkerRole, setNewWorkerRole] = useState('sales');
  
  // Assignment Form
  const [selectedWorkerId, setSelectedWorkerId] = useState('');
  const [selectedCamId, setSelectedCamId] = useState('');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [wRes, aRes, cRes] = await Promise.all([
        getWorkers(),
        getAssignments(),
        getCameras()
      ]);
      setWorkers(wRes);
      setAssignments(aRes);
      setCameras(cRes);
    } catch (error) {
      console.error('Error fetching worker data:', error);
    }
  };

  const handleAddWorker = async (e) => {
    e.preventDefault();
    if (!newWorkerName) return;
    try {
      const wid = `W-${Math.floor(1000 + Math.random() * 9000)}`;
      await createWorker({ worker_id: wid, name: newWorkerName, role: newWorkerRole, is_active: true });
      setNewWorkerName('');
      alert(`Worker ${newWorkerName} added successfully! Check the dropdown.`);
      fetchData();
    } catch (err) {
      console.error(err);
      alert('Failed to create worker');
    }
  };

  const handleAssignWorker = async (e) => {
    e.preventDefault();
    if (!selectedWorkerId || !selectedCamId) return;
    try {
      const cam = cameras.find(c => (c.id || c.camera_id) === selectedCamId);
      const sectionId = cam?.section_id || 1; // Use camera's section or fallback
      await assignWorker({ worker_id: parseInt(selectedWorkerId), section_id: sectionId });
      setSelectedWorkerId('');
      setSelectedCamId('');
      alert('Worker assigned successfully!');
      fetchData();
    } catch (err) {
      console.error(err);
      alert('Failed to assign worker');
    }
  };

  const handleRemoveAssignment = async (id) => {
    try {
      await deleteAssignment(id);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="worker-assignment">
      <div className="wa-header">
        <h2>Worker Management</h2>
        <p>Assign staff to camera zones for AI tracking</p>
      </div>

      <div className="wa-grid">
        {/* Left Column: Forms */}
        <div className="wa-forms">
          {/* Add Worker Form */}
          <div className="wa-card">
            <h3>Add New Worker</h3>
            <form onSubmit={handleAddWorker} className="wa-form">
              <div className="form-group">
                <label>Name</label>
                <input 
                  type="text" 
                  value={newWorkerName} 
                  onChange={e => setNewWorkerName(e.target.value)} 
                  placeholder="e.g. John Doe"
                  required
                />
              </div>
              <div className="form-group">
                <label>Role</label>
                <select value={newWorkerRole} onChange={e => setNewWorkerRole(e.target.value)}>
                  <option value="sales">Sales Associate</option>
                  <option value="manager">Manager</option>
                  <option value="security">Security</option>
                </select>
              </div>
              <button type="submit" className="btn-primary">Add Worker</button>
            </form>
          </div>

          {/* Assign Worker Form */}
          <div className="wa-card">
            <h3>Assign to Zone</h3>
            <form onSubmit={handleAssignWorker} className="wa-form">
              <div className="form-group">
                <label>Worker</label>
                <select 
                  value={selectedWorkerId} 
                  onChange={e => setSelectedWorkerId(e.target.value)}
                  required
                >
                  <option value="">Select a worker...</option>
                  {workers.map(w => (
                    <option key={w.id} value={w.id}>{w.name} ({w.role})</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>Camera / Zone</label>
                <select 
                  value={selectedCamId} 
                  onChange={e => setSelectedCamId(e.target.value)}
                  required
                >
                  <option value="">Select a camera...</option>
                  {cameras.map(c => (
                    <option key={c.id || c.camera_id} value={c.id || c.camera_id}>
                      {c.name || c.id || c.camera_id}
                    </option>
                  ))}
                </select>
              </div>
              <button type="submit" className="btn-primary">Assign</button>
            </form>
          </div>
        </div>

        {/* Right Column: Assignments List */}
        <div className="wa-list">
          <div className="wa-card full-height">
            <h3>Active Assignments</h3>
            {assignments.length === 0 ? (
              <div className="empty-state">No workers assigned to zones.</div>
            ) : (
              <ul className="assignment-list">
                {assignments.map(a => {
                  const worker = workers.find(w => w.id === a.worker_id) || {};
                  const camera = cameras.find(c => (c.id || c.camera_id) === a.camera_id) || {};
                  
                  return (
                    <li key={a.id} className="assignment-item">
                      <div className="assignment-info">
                        <div className="worker-info">
                          <span className="worker-avatar">
                            {worker.name ? worker.name.charAt(0).toUpperCase() : '?'}
                          </span>
                          <div>
                            <strong>{worker.name || `Worker #${a.worker_id}`}</strong>
                            <span className="worker-role">{worker.role || 'Unknown'}</span>
                          </div>
                        </div>
                        <div className="camera-info">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                            <circle cx="12" cy="13" r="4" />
                          </svg>
                          {camera.name || a.camera_id}
                        </div>
                      </div>
                      <button 
                        className="btn-remove" 
                        onClick={() => handleRemoveAssignment(a.id)}
                        title="Remove Assignment"
                      >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <line x1="18" y1="6" x2="6" y2="18" />
                          <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
