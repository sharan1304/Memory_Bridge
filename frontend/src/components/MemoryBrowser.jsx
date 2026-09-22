import { useEffect, useState } from "react";
import { api } from "../api.js";

const TYPE_ORDER = [
  "decision",
  "progress",
  "bottleneck",
  "failed_attempt",
  "test_result",
];
const TYPE_LABELS = {
  decision: "Decisions",
  progress: "Progress",
  bottleneck: "Bottlenecks",
  failed_attempt: "Failed Attempts",
  test_result: "Test Results",
};
const PERMANENT_TYPES = new Set(["decision", "failed_attempt"]);
const ALL_TYPES = [
  "current_state",
  "next_step",
  "decision",
  "progress",
  "bottleneck",
  "failed_attempt",
  "test_result",
];

function MemoryCard({ memory, projectId, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memory.content);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api.patchMemory(projectId, memory.id, draft);
      setEditing(false);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm("Delete this memory?")) return;
    setBusy(true);
    try {
      await api.deleteMemory(projectId, memory.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  const isBottleneck = memory.type === "bottleneck";

  return (
    <div className="card" style={isBottleneck ? { borderColor: "var(--type-bottleneck)" } : undefined}>
      <div className="card-header">
        <span className={`badge ${memory.type} ${PERMANENT_TYPES.has(memory.type) ? "permanent" : ""}`}>
          {memory.type.replace("_", " ")}
        </span>
        <span className="muted">{memory.agent} &middot; {new Date(memory.timestamp).toLocaleString()}</span>
      </div>

      {editing ? (
        <textarea
          rows={3}
          style={{ width: "100%" }}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      ) : (
        <p style={{ margin: "4px 0" }}>{memory.content}</p>
      )}

      <div className="row" style={{ marginTop: 8 }}>
        {editing ? (
          <>
            <button className="primary" disabled={busy} onClick={save}>Save</button>
            <button disabled={busy} onClick={() => { setEditing(false); setDraft(memory.content); }}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button disabled={busy} onClick={() => setEditing(true)}>Edit</button>
            <button className="danger" disabled={busy} onClick={remove}>Delete</button>
          </>
        )}
      </div>
    </div>
  );
}

function NewMemoryForm({ projectId, onCreated }) {
  const [type, setType] = useState("progress");
  const [content, setContent] = useState("");
  const [agent, setAgent] = useState("claude-code");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    try {
      await api.createMemory({ project_id: projectId, type, content, agent });
      setContent("");
      onCreated();
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-header">
        <strong>Force-store a memory</strong>
      </div>
      <div className="row wrap" style={{ marginBottom: 8 }}>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {ALL_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="claude-code">claude-code</option>
          <option value="codex">codex</option>
        </select>
      </div>
      <textarea
        rows={2}
        style={{ width: "100%", marginBottom: 8 }}
        placeholder="Memory content..."
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <button className="primary" disabled={busy} type="submit">Store</button>
    </form>
  );
}

export default function MemoryBrowser({ projectId }) {
  const [memories, setMemories] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await api.listMemories(projectId);
      setMemories(data);
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

  const active = memories.filter((m) => !m.superseded_by);
  const pinned = active.filter((m) => m.type === "current_state" || m.type === "next_step");
  const byType = TYPE_ORDER.map((type) => ({
    type,
    items: active.filter((m) => m.type === type),
  }));

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}

      {pinned.length > 0 && (
        <div className="pinned-section">
          {pinned.map((m) => (
            <MemoryCard key={m.id} memory={m} projectId={projectId} onChanged={load} />
          ))}
        </div>
      )}

      {loading && <div className="empty-state">Loading...</div>}

      {!loading &&
        byType.map(({ type, items }) =>
          items.length === 0 ? null : (
            <div key={type} style={{ marginBottom: 20 }}>
              <h3 style={{ marginBottom: 8 }}>{TYPE_LABELS[type]}</h3>
              {items.map((m) => (
                <MemoryCard key={m.id} memory={m} projectId={projectId} onChanged={load} />
              ))}
            </div>
          )
        )}

      {!loading && active.length === 0 && (
        <div className="empty-state">No memories yet for this project.</div>
      )}

      <NewMemoryForm projectId={projectId} onCreated={load} />
    </div>
  );
}
