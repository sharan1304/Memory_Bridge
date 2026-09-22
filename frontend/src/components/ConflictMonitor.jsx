import { useEffect, useState } from "react";
import { api } from "../api.js";

function MemorySide({ memory }) {
  return (
    <div className="card">
      <div className="card-header">
        <span className={`badge ${memory.type}`}>{memory.type.replace("_", " ")}</span>
        <span className="muted">{memory.agent}</span>
      </div>
      <p style={{ margin: 0 }}>{memory.content}</p>
    </div>
  );
}

export default function ConflictMonitor({ projectId }) {
  const [conflicts, setConflicts] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState(null);

  async function load() {
    setLoading(true);
    try {
      const data = await api.listConflicts(projectId);
      setConflicts(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [projectId]);

  async function keepOne(conflict, keep, discard) {
    const key = `${keep.id}-${discard.id}`;
    setBusyKey(key);
    try {
      await api.deleteMemory(projectId, discard.id);
      await load();
    } finally {
      setBusyKey(null);
    }
  }

  async function discardBoth(conflict) {
    const key = `discard-${conflict.memory_a.id}`;
    setBusyKey(key);
    try {
      await api.deleteMemory(projectId, conflict.memory_a.id);
      await api.deleteMemory(projectId, conflict.memory_b.id);
      await load();
    } finally {
      setBusyKey(null);
    }
  }

  async function merge(conflict) {
    const key = `merge-${conflict.memory_a.id}`;
    setBusyKey(key);
    try {
      const merged = `${conflict.memory_a.content} / ${conflict.memory_b.content}`;
      await api.createMemory({
        project_id: projectId,
        type: conflict.memory_a.type,
        content: merged,
        agent: conflict.memory_a.agent,
      });
      await api.deleteMemory(projectId, conflict.memory_a.id);
      await api.deleteMemory(projectId, conflict.memory_b.id);
      await load();
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="empty-state">Loading...</div>}
      {!loading && conflicts.length === 0 && (
        <div className="empty-state">No conflicts detected for this project.</div>
      )}

      {conflicts.map((conflict, idx) => (
        <div className="card" key={idx}>
          <div className="card-header">
            <strong>
              Similarity {Math.round(conflict.similarity * 100)}%
              {conflict.likely_contradiction ? " • likely contradiction" : ""}
            </strong>
          </div>
          <div className="conflict-pair">
            <MemorySide memory={conflict.memory_a} />
            <MemorySide memory={conflict.memory_b} />
          </div>
          <div className="row wrap" style={{ marginTop: 8 }}>
            <button
              disabled={busyKey !== null}
              onClick={() => keepOne(conflict, conflict.memory_a, conflict.memory_b)}
            >
              Keep A
            </button>
            <button
              disabled={busyKey !== null}
              onClick={() => keepOne(conflict, conflict.memory_b, conflict.memory_a)}
            >
              Keep B
            </button>
            <button disabled={busyKey !== null} onClick={() => merge(conflict)}>
              Merge
            </button>
            <button className="danger" disabled={busyKey !== null} onClick={() => discardBoth(conflict)}>
              Discard both
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
