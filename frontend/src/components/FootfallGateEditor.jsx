import { useEffect, useState } from 'react';
import { getFootfallGate, saveFootfallGate, getVideoUrl } from '../api/api.js';
import './FootfallGateEditor.css';

const DEFAULT_GATE = {
  line_start: [0.25, 0.5],
  line_end: [0.75, 0.5],
  entry_side: 1,
  enabled: false,
};

export default function FootfallGateEditor({ cameras = [] }) {
  const availableCameras = cameras.filter((camera) => camera?.cam_id);
  const [cameraId, setCameraId] = useState(availableCameras[0]?.cam_id || '');
  const [gate, setGate] = useState(DEFAULT_GATE);
  const [placing, setPlacing] = useState('start');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [aspectRatio, setAspectRatio] = useState('4 / 3');

  useEffect(() => {
    if (!cameraId && availableCameras.length) {
      setCameraId(availableCameras[0].cam_id);
    }
  }, [availableCameras, cameraId]);

  useEffect(() => {
    if (!cameraId) return;

    let cancelled = false;
    setLoading(true);
    setMessage('');

    getFootfallGate(cameraId)
      .then((result) => {
        if (!cancelled) {
          setGate({ ...DEFAULT_GATE, ...result });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setMessage(`Could not load gate: ${error.message}`);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [cameraId]);

  const placePoint = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const point = [
      Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
      Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
    ];

    setGate((current) => ({
      ...current,
      [placing === 'start' ? 'line_start' : 'line_end']: point,
    }));

    setMessage(
      `${placing === 'start' ? 'Start' : 'End'} point updated. Save the gate to apply it.`
    );
    setPlacing(placing === 'start' ? 'end' : 'start');
  };

  const save = async () => {
    if (!cameraId) return;

    setSaving(true);
    setMessage('');

    try {
      const saved = await saveFootfallGate(cameraId, gate);
      setGate({ ...DEFAULT_GATE, ...saved });
      setMessage('Gate saved and applied to the live camera pipeline.');
    } catch (error) {
      setMessage(`Could not save gate: ${error.message}`);
    } finally {
      setSaving(false);
    }
  };

  const start = gate.line_start || DEFAULT_GATE.line_start;
  const end = gate.line_end || DEFAULT_GATE.line_end;
  const selectedCamera = availableCameras.find(
    (camera) => camera.cam_id === cameraId
  );

  return (
    <section className="footfall-gate-card">
      <div className="footfall-feature-header">
        <div>
          <h3>Entry / Exit Line Setup</h3>
          <p>
            Configure a separate crossing line for each camera. Click the live
            view to set the two endpoints.
          </p>
        </div>

        <label className="footfall-inline-field">
          <span>Camera</span>
          <select
            value={cameraId}
            onChange={(event) => setCameraId(event.target.value)}
            disabled={!availableCameras.length}
          >
            {availableCameras.map((camera) => (
              <option key={camera.cam_id} value={camera.cam_id}>
                {camera.name || camera.cam_id}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!availableCameras.length ? (
        <p className="footfall-feature-muted">
          No cameras are available to configure.
        </p>
      ) : (
        <>
          <div className="footfall-gate-layout">
            <div className="footfall-gate-preview-wrap">
              <div
                className="footfall-gate-preview"
                style={{ aspectRatio }}
              >
                {!loading && (
                  <img
                    src={getVideoUrl(cameraId, 60, false)}
                    alt={`${selectedCamera?.name || cameraId} live camera`}
                    onLoad={(event) => {
                      const image = event.currentTarget;
                      if (image.naturalWidth && image.naturalHeight) {
                        setAspectRatio(
                          `${image.naturalWidth} / ${image.naturalHeight}`
                        );
                      }
                    }}
                  />
                )}

                <svg
                  viewBox="0 0 100 100"
                  preserveAspectRatio="none"
                  className="footfall-gate-overlay"
                  onClick={placePoint}
                  role="button"
                  aria-label="Click to place a gate endpoint"
                >
                  <line
                    x1={start[0] * 100}
                    y1={start[1] * 100}
                    x2={end[0] * 100}
                    y2={end[1] * 100}
                  />
                  <circle
                    cx={start[0] * 100}
                    cy={start[1] * 100}
                    r="2.2"
                    className="gate-point gate-point-start"
                  />
                  <circle
                    cx={end[0] * 100}
                    cy={end[1] * 100}
                    r="2.2"
                    className="gate-point gate-point-end"
                  />
                  <text
                    x={start[0] * 100}
                    y={Math.max(5, start[1] * 100 - 4)}
                  >
                    A
                  </text>
                  <text
                    x={end[0] * 100}
                    y={Math.max(5, end[1] * 100 - 4)}
                  >
                    B
                  </text>
                </svg>

                {loading && (
                  <div className="footfall-gate-loading">Loading gate…</div>
                )}
              </div>

              <div className="footfall-point-actions">
                <button
                  type="button"
                  className={placing === 'start' ? 'active' : ''}
                  onClick={() => setPlacing('start')}
                >
                  Set start (A)
                </button>
                <button
                  type="button"
                  className={placing === 'end' ? 'active' : ''}
                  onClick={() => setPlacing('end')}
                >
                  Set end (B)
                </button>
              </div>
            </div>

            <div className="footfall-gate-settings">
              <label className="footfall-checkbox-row">
                <input
                  type="checkbox"
                  checked={Boolean(gate.enabled)}
                  onChange={(event) =>
                    setGate((current) => ({
                      ...current,
                      enabled: event.target.checked,
                    }))
                  }
                />
                <span>Enable crossing detection</span>
              </label>

              <label className="footfall-inline-field">
                <span>Which side represents entry?</span>
                <select
                  value={gate.entry_side}
                  onChange={(event) =>
                    setGate((current) => ({
                      ...current,
                      entry_side: Number(event.target.value),
                    }))
                  }
                >
                  <option value={1}>Positive side of A → B (+1)</option>
                  <option value={-1}>Negative side of A → B (−1)</option>
                </select>
              </label>

              <p className="footfall-feature-muted">
                Side is defined relative to the direction from endpoint A to
                endpoint B. The opposite crossing is recorded as an exit.
              </p>

              <div className="footfall-coordinate-readout">
                <div>
                  <span>A</span>
                  <code>{start.map((value) => value.toFixed(3)).join(', ')}</code>
                </div>
                <div>
                  <span>B</span>
                  <code>{end.map((value) => value.toFixed(3)).join(', ')}</code>
                </div>
              </div>

              <button
                type="button"
                className="footfall-primary-button"
                onClick={save}
                disabled={
                  saving ||
                  loading ||
                  !cameraId ||
                  (start[0] === end[0] && start[1] === end[1])
                }
              >
                {saving ? 'Saving…' : 'Save gate configuration'}
              </button>
            </div>
          </div>

          {message && (
            <p className="footfall-feature-message" role="status">
              {message}
            </p>
          )}
        </>
      )}
    </section>
  );
}