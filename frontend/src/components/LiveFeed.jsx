import { useEffect, useRef, useState } from "react";
import { api, wsUrl } from "../api.js";

function formatTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return ts;
  }
}

export default function LiveFeed({ projectId }) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState(null);
  const socketRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listEvents(projectId, 50)
      .then((initial) => {
        if (!cancelled) setEvents(initial);
      })
      .catch((err) => setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    const socket = new WebSocket(wsUrl());
    socketRef.current = socket;

    socket.onopen = () => {
      setConnected(true);
      setError(null);
    };
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setError("Live Feed WebSocket connection error");
    socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        setEvents((prev) => [parsed, ...prev].slice(0, 200));
      } catch {
        /* ignore malformed frames */
      }
    };

    return () => socket.close();
  }, []);

  async function togglePause() {
    try {
      if (paused) {
        await api.resumeManager();
        setPaused(false);
      } else {
        await api.pauseManager();
        setPaused(true);
      }
    } catch (err) {
      setError(err.message);
    }
  }

  const visible = events.filter((e) => e.project_id === projectId);

  return (
    <div>
      <div className="card-header">
        <div className="row">
          <span className={`status-dot ${connected ? "on" : "off"}`} />
          <span className="muted">{connected ? "connected" : "disconnected"}</span>
        </div>
        <button className={paused ? "primary" : "danger"} onClick={togglePause}>
          {paused ? "Resume manager" : "Pause manager"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {visible.length === 0 && (
        <div className="empty-state">No events yet for this project.</div>
      )}

      {visible.map((event) => (
        <div className="feed-item" key={event.id}>
          <div className="meta">
            [{formatTime(event.timestamp)}] {event.agent} &rarr; {event.tool}() &middot;{" "}
            {event.memories_affected.length} memories
          </div>
          {event.memories_affected.length > 0 && (
            <div className="memory-line">
              {event.memories_affected.map((id) => (
                <div key={id}>&#8627; {id}</div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
