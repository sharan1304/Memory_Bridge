import { useEffect, useState } from "react";
import { api } from "./api.js";
import LiveFeed from "./components/LiveFeed.jsx";
import MemoryBrowser from "./components/MemoryBrowser.jsx";
import ConflictMonitor from "./components/ConflictMonitor.jsx";
import AgentStatus from "./components/AgentStatus.jsx";
import DecayTracker from "./components/DecayTracker.jsx";
import RoutingRules from "./components/RoutingRules.jsx";

const TABS = [
  { key: "feed", label: "Live Feed" },
  { key: "memories", label: "Memory Browser" },
  { key: "conflicts", label: "Conflict Monitor" },
  { key: "agents", label: "Agent Status" },
  { key: "decay", label: "Decay Tracker" },
  { key: "routing", label: "Routing Rules" },
];

const PROJECTS_KEY = "mennbridge.projects";
const LAST_PROJECT_KEY = "mennbridge.lastProject";

// Projects the user has manually added via "+ Add" - kept in localStorage so
// a project with no events yet (nothing calls get_context/checkpoint for it
// yet) still survives a refresh, even though the backend can't know about it.
function loadLocalProjects() {
  try {
    const raw = localStorage.getItem(PROJECTS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function loadLastProject() {
  try {
    return localStorage.getItem(LAST_PROJECT_KEY) || "";
  } catch {
    return "";
  }
}

export default function App() {
  const [projects, setProjects] = useState(loadLocalProjects);
  const [projectId, setProjectId] = useState(loadLastProject);
  const [activeTab, setActiveTab] = useState("feed");
  const [projectsLoading, setProjectsLoading] = useState(true);

  // On load, fetch the backend's known projects (distinct project_ids the
  // event log has seen) and merge them with any locally-added ones. Only
  // fall back to the backend's default (MENNBRIDGE_PROJECT) when nothing was
  // already selected - a returning user's last choice still wins.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { projects: fetched, default: defaultProject } = await api.listProjects();
        if (cancelled) return;
        setProjects((prev) => {
          const merged = [...fetched, ...prev.filter((p) => !fetched.includes(p))];
          return merged.length ? merged : [defaultProject];
        });
        setProjectId((prev) => prev || defaultProject);
      } catch {
        // Backend unreachable - fall back to whatever's local, or "default".
        setProjectId((prev) => prev || loadLocalProjects()[0] || "default");
      } finally {
        if (!cancelled) setProjectsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(PROJECTS_KEY, JSON.stringify(projects));
    } catch {
      /* ignore persistence failures */
    }
  }, [projects]);

  useEffect(() => {
    if (!projectId) return;
    try {
      localStorage.setItem(LAST_PROJECT_KEY, projectId);
    } catch {
      /* ignore persistence failures */
    }
  }, [projectId]);

  function addProject() {
    const name = window.prompt("Project ID (matches MENNBRIDGE_PROJECT):");
    if (!name) return;
    setProjects((prev) => (prev.includes(name) ? prev : [...prev, name]));
    setProjectId(name);
  }

  return (
    <div className="app-shell">
      <div className="topbar">
        <h1>MENNBridge</h1>
        <div className="project-switcher">
          <label className="muted" htmlFor="project-select">
            Project
          </label>
          <select
            id="project-select"
            value={projectId}
            disabled={projectsLoading}
            onChange={(e) => setProjectId(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <button onClick={addProject}>+ Add</button>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={`tab ${activeTab === tab.key ? "active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="panel">
        {projectsLoading || !projectId ? (
          <div className="empty-state">Loading projects...</div>
        ) : (
          <>
            {activeTab === "feed" && <LiveFeed projectId={projectId} />}
            {activeTab === "memories" && <MemoryBrowser projectId={projectId} />}
            {activeTab === "conflicts" && <ConflictMonitor projectId={projectId} />}
            {activeTab === "agents" && <AgentStatus projectId={projectId} />}
            {activeTab === "decay" && <DecayTracker projectId={projectId} />}
            {activeTab === "routing" && <RoutingRules />}
          </>
        )}
      </div>
    </div>
  );
}
