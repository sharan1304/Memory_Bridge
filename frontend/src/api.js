const BASE = "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  listProjects: () => request(`/dashboard/projects`),
  listMemories: (projectId) =>
    request(`/dashboard/memories?project_id=${encodeURIComponent(projectId)}`),
  getMemory: (projectId, id) =>
    request(`/dashboard/memories/${id}?project_id=${encodeURIComponent(projectId)}`),
  patchMemory: (projectId, id, content) =>
    request(`/dashboard/memories/${id}?project_id=${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      body: JSON.stringify({ content }),
    }),
  deleteMemory: (projectId, id) =>
    request(`/dashboard/memories/${id}?project_id=${encodeURIComponent(projectId)}`, {
      method: "DELETE",
    }),
  createMemory: (payload) =>
    request(`/dashboard/memories`, { method: "POST", body: JSON.stringify(payload) }),
  pauseManager: () => request(`/dashboard/manager/pause`, { method: "POST" }),
  resumeManager: () => request(`/dashboard/manager/resume`, { method: "POST" }),
  listEvents: (projectId, limit = 50) =>
    request(`/dashboard/events?project_id=${encodeURIComponent(projectId)}&limit=${limit}`),
  listAgents: (projectId) =>
    request(`/dashboard/agents?project_id=${encodeURIComponent(projectId)}`),
  listConflicts: (projectId) =>
    request(`/dashboard/conflicts?project_id=${encodeURIComponent(projectId)}`),
  listDecay: (projectId) =>
    request(`/dashboard/decay?project_id=${encodeURIComponent(projectId)}`),
  reinforceMemory: (projectId, id) =>
    request(`/dashboard/decay/${id}/reinforce?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST",
    }),
};

export function wsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/dashboard/ws`;
}
