import { useEffect, useState } from "react";
import { api } from "../api.js";

function ageLabel(timestamp) {
  const ms = Date.now() - new Date(timestamp).getTime();
  const days = ms / 86400000;
  if (days < 1) return `${Math.max(1, Math.round(days * 24))}h`;
  return `${Math.round(days)}d`;
}

export default function DecayTracker({ projectId }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);

  async function load() {
    setLoading(true);
    try {
      const data = await api.listDecay(projectId);
      setRows(data);
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

  async function reinforce(id) {
    setBusyId(id);
    try {
      await api.reinforceMemory(projectId, id);
      await load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="empty-state">Loading...</div>}
      {!loading && rows.length === 0 && (
        <div className="empty-state">Nothing decaying yet for this project.</div>
      )}

      {!loading && rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Content</th>
              <th>Age</th>
              <th>Importance</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ memory, importance }) => (
              <tr key={memory.id}>
                <td><span className={`badge ${memory.type}`}>{memory.type.replace("_", " ")}</span></td>
                <td>{memory.content}</td>
                <td>{ageLabel(memory.timestamp)}</td>
                <td>
                  <div className="row">
                    <div className="importance-bar">
                      <div style={{ width: `${Math.round(importance * 100)}%` }} />
                    </div>
                    <span className="muted">{importance.toFixed(2)}</span>
                  </div>
                </td>
                <td>
                  <button disabled={busyId === memory.id} onClick={() => reinforce(memory.id)}>
                    Reinforce
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
