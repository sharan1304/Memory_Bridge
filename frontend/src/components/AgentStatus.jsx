import { useEffect, useState } from "react";
import { api } from "../api.js";

const KNOWN_AGENTS = ["claude-code", "codex"];

export default function AgentStatus({ projectId }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .listAgents(projectId)
      .then((data) => {
        if (!cancelled) {
          setRows(data);
          setError(null);
        }
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const byAgent = Object.fromEntries(rows.map((r) => [r.agent, r]));

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="empty-state">Loading...</div>}

      {!loading && (
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Last session</th>
              <th>Last seen</th>
              <th>Memories written this session</th>
            </tr>
          </thead>
          <tbody>
            {KNOWN_AGENTS.map((agent) => {
              const row = byAgent[agent];
              return (
                <tr key={agent}>
                  <td>{agent}</td>
                  <td>{row ? row.session_id : <span className="muted">no sessions yet</span>}</td>
                  <td>{row ? new Date(row.last_seen).toLocaleString() : "-"}</td>
                  <td>{row ? row.memories_written_this_session : "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
