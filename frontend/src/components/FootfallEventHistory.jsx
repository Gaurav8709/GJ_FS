import { useCallback, useEffect, useState } from 'react';
import { getFootfallEvents, getImageUrl } from '../api/api.js';
import './FootfallEventHistory.css';

export default function FootfallEventHistory({ cameras = [] }) {
  const [cameraId, setCameraId] = useState('');
  const [eventType, setEventType] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [page, setPage] = useState(0);
  const [data, setData] = useState({
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedImage, setSelectedImage] = useState(null);
  const pageSize = 20;

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');

    try {
      const result = await getFootfallEvents({
        cam_id: cameraId,
        event_type: eventType,
        start_date: startDate,
        end_date: endDate,
        start_time: startTime,
        end_time: endTime,
        limit: pageSize,
        offset: page * pageSize,
      });

      setData({
        items: result.items || [],
        total: result.total || 0,
        limit: result.limit || pageSize,
        offset: result.offset || 0,
      });
    } catch (err) {
      setError(err.message || 'Could not load crossing events.');
    } finally {
      setLoading(false);
    }
  }, [
    cameraId,
    eventType,
    startDate,
    endDate,
    startTime,
    endTime,
    page,
  ]);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 15000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const clearFilters = () => {
    setCameraId('');
    setEventType('');
    setStartDate('');
    setEndDate('');
    setStartTime('');
    setEndTime('');
    setPage(0);
  };

  const formatTimestamp = (value) => {
    if (!value) return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
  };

  return (
    <section className="footfall-event-history-card">
      <div className="footfall-feature-header">
        <div>
          <h3>Entry / Exit Event History</h3>
          <p>
            Individual line-crossing records and their saved person snapshots.
            These records are separate from the aggregate charts above.
          </p>
        </div>

        <button
          type="button"
          className="footfall-history-refresh"
          onClick={refresh}
          disabled={loading}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {loading && (
        <div
          className="footfall-loading-progress"
          role="progressbar"
          aria-label="Loading footfall events"
          aria-valuetext="Loading"
        >
          <div className="footfall-loading-progress-bar" />
        </div>
      )}
      <div className="footfall-event-filters">
        <label>
          <span>Camera</span>
          <select
            value={cameraId}
            onChange={(event) => {
              setCameraId(event.target.value);
              setPage(0);
            }}
          >
            <option value="">All cameras</option>
            {cameras
              .filter((camera) => camera?.cam_id)
              .map((camera) => (
                <option key={camera.cam_id} value={camera.cam_id}>
                  {camera.name || camera.cam_id}
                </option>
              ))}
          </select>
        </label>

        <label>
          <span>Event</span>
          <select
            value={eventType}
            onChange={(event) => {
              setEventType(event.target.value);
              setPage(0);
            }}
          >
            <option value="">Entry and exit</option>
            <option value="ENTRY">Entry</option>
            <option value="EXIT">Exit</option>
          </select>
        </label>

        <label>
          <span>Start date</span>
          <input
            type="date"
            value={startDate}
            onChange={(event) => {
              setStartDate(event.target.value);
              setPage(0);
            }}
          />
        </label>

        <label>
          <span>Start time</span>
          <input
            type="time"
            value={startTime}
            onChange={(event) => {
              setStartTime(event.target.value);
              setPage(0);
            }}
          />
        </label>

        <label>
          <span>End date</span>
          <input
            type="date"
            value={endDate}
            onChange={(event) => {
              setEndDate(event.target.value);
              setPage(0);
            }}
          />
        </label>

        <label>
          <span>End time</span>
          <input
            type="time"
            value={endTime}
            onChange={(event) => {
              setEndTime(event.target.value);
              setPage(0);
            }}
          />
        </label>

        <button
          type="button"
          className="footfall-history-clear"
          onClick={clearFilters}
        >
          Clear filters
        </button>
      </div>

      {error && <p className="footfall-history-error">{error}</p>}

      {!loading && !error && data.items.length === 0 ? (
        <div className="footfall-history-empty">
          No crossing events match these filters yet. Confirm that a gate is
          enabled and a person crosses the configured line.
        </div>
      ) : (
        <div className="footfall-event-grid">
          {data.items.map((item) => (
            <article
              className="footfall-event-item"
              key={item.event_id || item.id}
            >
              <button
                type="button"
                className="footfall-event-thumb"
                onClick={() => setSelectedImage(item)}
                title="View full-size snapshot"
              >
                <img
                  src={getImageUrl(item.snapshot_url)}
                  alt={`${item.event_type} snapshot from ${item.cam_id}`}
                  loading="lazy"
                />
              </button>

              <div className="footfall-event-info">
                <div
                  className={`footfall-event-pill ${String(
                    item.event_type
                  ).toLowerCase()}`}
                >
                  {item.event_type}
                </div>
                <strong>{item.camera_name || item.cam_id}</strong>
                <span>Tracking ID: {item.tracking_id}</span>
                <time>{formatTimestamp(item.timestamp)}</time>
              </div>
            </article>
          ))}
        </div>
      )}

      <div className="footfall-history-pagination">
        <span>
          {data.total
            ? `${data.offset + 1}–${Math.min(
                data.offset + data.items.length,
                data.total
              )} of ${data.total} events`
            : '0 events'}
        </span>

        <div>
          <button
            type="button"
            onClick={() => setPage((current) => Math.max(0, current - 1))}
            disabled={page === 0 || loading}
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => setPage((current) => current + 1)}
            disabled={loading || (page + 1) * pageSize >= data.total}
          >
            Next
          </button>
        </div>
      </div>

      {selectedImage && (
        <div
          className="footfall-image-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Footfall event snapshot"
          onClick={() => setSelectedImage(null)}
        >
          <div
            className="footfall-image-modal-content"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className="footfall-image-modal-close"
              onClick={() => setSelectedImage(null)}
              aria-label="Close snapshot"
            >
              ×
            </button>

            <img
              src={getImageUrl(selectedImage.snapshot_url)}
              alt={`${selectedImage.event_type} event snapshot`}
            />

            <div>
              <strong>
                {selectedImage.event_type} ·{' '}
                {selectedImage.camera_name || selectedImage.cam_id}
              </strong>
              <span>
                {formatTimestamp(selectedImage.timestamp)} · Tracking ID{' '}
                {selectedImage.tracking_id}
              </span>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}