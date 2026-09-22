import { useState } from "react";

// Scaffold only: project routing is explicit via MENNBRIDGE_PROJECT, never
// inferred from content. This table has no logic behind it yet - it exists
// so the UI shape is ready if keyword-based routing is ever added.
export default function RoutingRules() {
  const [rows, setRows] = useState([]);

  function addRow() {
    setRows((prev) => [...prev, { id: crypto.randomUUID(), keyword: "", project: "" }]);
  }

  function updateRow(id, field, value) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  }

  function deleteRow(id) {
    setRows((prev) => prev.filter((r) => r.id !== id));
  }

  return (
    <div>
      <div className="error-banner" style={{ background: "var(--surface-alt)", color: "var(--text-muted)", borderColor: "var(--border)" }}>
        Scaffold only - no routing logic runs off this table yet. Project ID always comes from the MENNBRIDGE_PROJECT env var.
      </div>

      <table>
        <thead>
          <tr>
            <th>Keyword</th>
            <th>Project</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <input
                  value={row.keyword}
                  onChange={(e) => updateRow(row.id, "keyword", e.target.value)}
                  placeholder="keyword"
                />
              </td>
              <td>
                <input
                  value={row.project}
                  onChange={(e) => updateRow(row.id, "project", e.target.value)}
                  placeholder="project id"
                />
              </td>
              <td>
                <button className="danger" onClick={() => deleteRow(row.id)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {rows.length === 0 && <div className="empty-state">No routing rules yet.</div>}

      <button className="primary" style={{ marginTop: 12 }} onClick={addRow}>+ Add row</button>
    </div>
  );
}
