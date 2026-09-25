/* ====================================================
   API Layer — GJ Fashion AI Smart Showroom
   ==================================================== */

let rawBase = import.meta.env.VITE_API_URL || '';
if (typeof window !== 'undefined' && window.location.protocol === 'https:' && rawBase.startsWith('http://')) {
  rawBase = '';
}
const BASE = rawBase;

/* ---------- Token helpers ---------- */
export const getToken  = () => localStorage.getItem('gj_token');
export const setToken  = (t) => localStorage.setItem('gj_token', t);
export const clearToken = () => localStorage.removeItem('gj_token');

/* ---------- Authenticated fetch wrapper ---------- */
export async function apiFetch(path, opts = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, { ...opts, headers });
  if (res.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.message || `API error ${res.status}`);
  }
  return res.json();
}

/* ---------- Auth ---------- */
export async function login(username, password) {
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    let errMsg = body.detail || 'Login failed';
    if (Array.isArray(errMsg)) errMsg = errMsg[0].msg;
    throw new Error(errMsg);
  }
  const data = await res.json();
  setToken(data.token);
  return data;
}

export const getMe = () => apiFetch('/api/auth/me');

/* ---------- Floors / Sections ---------- */
export const getFloors   = () => apiFetch('/api/floors');
export const getSections = (floorId) =>
  apiFetch(`/api/floors/${floorId}/sections`);

/* ---------- Cameras ---------- */
export const getCameras      = () => apiFetch('/api/cameras');
export const getCameraStatus = () => apiFetch('/api/cameras/status/all');
export const getCameraDetail = (camId) => apiFetch(`/api/cameras/${camId}`);
export const onboardCamera   = (data) => apiFetch('/api/cameras', { method: 'POST', body: JSON.stringify(data) });
export const updateCamera    = (camId, data) => apiFetch(`/api/cameras/${camId}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteCamera    = (camId) => apiFetch(`/api/cameras/${camId}`, { method: 'DELETE' });
export const clearAllCameras = () => apiFetch('/api/cameras/clear-all', { method: 'DELETE' });

/* ---------- Zones ---------- */
export const getZones = (camId) => apiFetch(`/api/cameras/${camId}/zones`);

/* ---------- Workers ---------- */
export const getWorkers     = () => apiFetch('/api/workers');
export const createWorker   = (data) =>
  apiFetch('/api/workers', { method: 'POST', body: JSON.stringify(data) });
export const getAssignments = () => apiFetch('/api/assignments');
export const assignWorker   = (data) =>
  apiFetch('/api/assignments', { method: 'POST', body: JSON.stringify(data) });
export const deleteAssignment = (id) =>
  apiFetch(`/api/assignments/${id}`, { method: 'DELETE' });

/* ---------- Alerts ---------- */
export const getAlerts        = (limit = 50) => apiFetch(`/api/alerts?limit=${limit}`);
export const acknowledgeAlert = (id) =>
  apiFetch(`/api/alerts/${id}/acknowledge`, { method: 'POST' });

/* ---------- Analytics ---------- */
export const getAnalytics = () => apiFetch('/api/analytics');

export const getVideoUrl = (camId, quality = 60, showZones = true) =>
  `${BASE}/api/streams/${camId}/mjpeg?q=${quality}&show_zones=${showZones}`;

export const getSnapshotUrl = (camId) =>
  `${BASE}/api/streams/${camId}/snapshot`;

export const getWsStreamUrl = (camId, quality = 60, fps = 30, showZones = true) => {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = BASE ? new URL(BASE).host : window.location.host;
  return `${proto}://${host}/ws/streams/${camId}?q=${quality}&fps=${fps}&show_zones=${showZones}`;
};

/* ---------- WebSocket ---------- */
export function connectAlertWS(onMessage) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = BASE ? new URL(BASE).host : window.location.host;
  const token = getToken();
  const ws = new WebSocket(`${proto}://${host}/ws/alerts?token=${token}`);
  ws.onmessage = (e) => {
    try { onMessage(JSON.parse(e.data)); } catch { onMessage(e.data); }
  };
  ws.onclose = () => {
    // Reconnect after 3 seconds
    setTimeout(() => connectAlertWS(onMessage), 3000);
  };
  return ws;
}

/* ---------- Footfall ---------- */
export const getFootfallStats = (camId) => apiFetch(`/api/footfall/stats${camId ? `?cam_id=${camId}` : ''}`);
export const updateFootfall = (payload) => apiFetch('/api/footfall/listener-update', { method: 'POST', body: JSON.stringify(payload) });

/* ---------- Face Alerts & Employee Monitoring ---------- */
export const getEmployees = () => apiFetch('/api/face-alerts/employees');
export const triggerFaceAlert = (payload) => apiFetch('/api/face-alerts/detect', { method: 'POST', body: JSON.stringify(payload) });
export const getEmployeeMonitoringSummary = () => apiFetch('/api/face-alerts/monitoring-summary');
export const getEmployeeDetections = (empId, camId, date) =>
  apiFetch(`/api/face-alerts/detections?${empId ? `emp_id=${empId}&` : ''}${camId ? `cam_id=${camId}&` : ''}${date ? `date=${date}&` : ''}`);

export async function registerEmployee(formData) {
  const token = getToken();
  const res = await fetch(`${BASE}/api/face-alerts/employees`, {
    method: 'POST',
    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    body: formData,
  });
  if (!res.ok) throw new Error('Failed to register employee');
  return res.json();
}


/* ---------- Forensics & FRS ---------- */
export const getForensicClips = (category, camId) =>
  apiFetch(`/api/forensics/list?${category ? `category=${category}&` : ''}${camId ? `cam_id=${camId}` : ''}`);

export async function uploadForensicClip(formData) {
  const token = getToken();
  const res = await fetch(`${BASE}/api/forensics/upload`, {
    method: 'POST',
    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    body: formData,
  });
  if (!res.ok) throw new Error('Failed to upload clip');
  return res.json();
}

export const deleteForensicClip = (id) =>
  apiFetch(`/api/forensics/${id}`, { method: 'DELETE' });


/* ---------- Heatmaps ---------- */
export const getLatestHeatmaps = () => apiFetch('/api/heatmaps/latest');
export const getHeatmapForCamera = (camId) => apiFetch(`/api/heatmaps/camera/${camId}`);
export async function uploadHeatmap(formData) {
  const token = getToken();
  const res = await fetch(`${BASE}/api/heatmaps/upload`, {
    method: 'POST',
    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    body: formData,
  });
  if (!res.ok) throw new Error('Failed to upload heatmap');
  return res.json();
}
