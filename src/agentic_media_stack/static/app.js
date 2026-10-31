const state = {
  view: "overview",
  selectedRequest: null,
  requests: [],
  token: localStorage.getItem("media-session") || "",
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    $("#login-dialog").showModal();
    throw new Error("authentication required");
  }
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Request failed");
  return payload;
}

function showView(view) {
  state.view = view;
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${view}`));
  $("#page-title").textContent = view[0].toUpperCase() + view.slice(1);
  if (view === "requests") loadRequests();
  if (view === "imports") { loadPlan(); loadDownloads(); }
  if (view === "library") loadLibrary();
  if (view === "activity") loadActivity();
}

function empty(node, message) {
  node.innerHTML = "";
  const item = document.createElement("p");
  item.className = "empty-state";
  item.textContent = message;
  node.append(item);
}

function statusChip(status) {
  const value = String(status || "unknown");
  const tone = ["completed", "verified", "healthy"].includes(value) ? "green" :
    ["failed", "error"].includes(value) ? "red" :
    ["review", "downloading", "queued"].includes(value) ? "amber" : "";
  return `<span class="status ${tone}">${value}</span>`;
}

async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    const counts = data.status.counts;
    $("#stat-grid").innerHTML = [
      [counts.requests, "Requests"], [counts.downloads, "Downloads"],
      [counts.review, "Needs review"], [counts.library, "Verified library"],
    ].map(([value, label]) => `<article class="stat"><p class="eyebrow">${label}</p><div class="value">${value}</div><div class="label">persistent state</div></article>`).join("");
    const list = $("#overview-requests");
    list.innerHTML = "";
    if (!data.requests.length) empty(list, "No requests yet. Search for a title to start.");
    data.requests.slice(0, 5).forEach((request) => {
      const row = document.createElement("button");
      row.className = "row-card";
      row.innerHTML = `<div><strong></strong><div class="meta">${request.kind} · ${request.updated_at}</div></div>${statusChip(request.status)}`;
      row.querySelector("strong").textContent = request.title;
      row.onclick = () => { state.selectedRequest = request.id; showView("requests"); loadCandidates(request.id); };
      list.append(row);
    });
    renderServices(data.status);
    $("#rail-state").textContent = data.status.ok ? "Operational" : "Needs attention";
  } catch (error) {
    $("#rail-state").textContent = "Offline";
    toast(error.message);
  }
}

function renderServices(status) {
  const node = $("#service-list");
  node.innerHTML = "";
  const items = [
    ["Media apps", status.adapters.media_apps.join(", ") || "not configured"],
    ["Download clients", status.adapters.download_clients.join(", ") || "not configured"],
    ["Indexer", status.adapters.indexer || "not configured"],
    ["Jellyfin", status.adapters.jellyfin || "not configured"],
  ];
  items.forEach(([name, value]) => {
    const row = document.createElement("div");
    row.className = "service";
    row.innerHTML = `<span class="service-name"></span><span class="service-state"></span>`;
    row.children[0].textContent = name;
    row.children[1].textContent = value;
    node.append(row);
  });
}

async function loadRequests() {
  const data = await api("/api/requests");
  state.requests = data.items;
  const node = $("#request-list");
  node.innerHTML = "";
  if (!state.requests.length) empty(node, "No requests yet.");
  state.requests.forEach((request) => {
    const row = document.createElement("button");
    row.className = "row-card";
    row.innerHTML = `<div><strong></strong><div class="meta">${request.kind} · ${request.created_at}</div></div>${statusChip(request.status)}`;
    row.querySelector("strong").textContent = request.title;
    row.onclick = () => { state.selectedRequest = request.id; loadCandidates(request.id); };
    node.append(row);
  });
  if (state.selectedRequest) loadCandidates(state.selectedRequest);
}

async function loadCandidates(requestId) {
  const request = state.requests.find((item) => item.id === requestId);
  $("#candidate-title").textContent = request ? request.title : "Candidates";
  const data = await api(`/api/requests/${requestId}/candidates`);
  const node = $("#candidate-list");
  node.classList.remove("empty");
  node.innerHTML = "";
  if (!data.items.length) { empty(node, "No candidate releases yet. The search job may still be running."); return; }
  data.items.forEach((candidate) => {
    const card = document.createElement("article");
    card.className = "candidate-card";
    card.innerHTML = `<div><strong></strong><div class="meta">${candidate.indexer} · ${Math.round(candidate.size_bytes / 1048576)} MB · ${candidate.seeders} seeders</div></div><button class="button primary">Send to qBittorrent</button>`;
    card.querySelector("strong").textContent = candidate.title;
    card.querySelector("button").onclick = async () => {
      try {
        await api(`/api/requests/${requestId}/select`, { method: "POST", body: JSON.stringify({ candidate_id: candidate.id }) });
        toast("Download queued");
        loadRequests();
        loadDownloads();
      } catch (error) { toast(error.message); }
    };
    node.append(card);
  });
}

async function submitRequest(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const body = { title: form.get("title"), kind: form.get("kind") };
  if (form.get("year")) body.year = Number(form.get("year"));
  $("#request-feedback").textContent = "Searching configured indexer…";
  try {
    const request = await api("/api/requests", { method: "POST", body: JSON.stringify(body) });
    state.selectedRequest = request.id;
    $("#request-feedback").textContent = "Search started. Candidates will appear below.";
    toast("Search started");
    loadRequests();
  } catch (error) { $("#request-feedback").textContent = error.message; }
}

async function loadPlan() {
  const data = await api("/api/plan");
  const node = $("#plan-list");
  node.innerHTML = "";
  if (!data.items.length) { empty(node, "No import decisions yet."); return; }
  data.items.forEach((item) => {
    const row = document.createElement("article");
    row.className = "row-card";
    row.innerHTML = `<div><strong></strong><div class="meta"></div></div><div class="row-actions">${statusChip(item.action)}<button class="text-button import-action">Import</button></div>`;
    row.querySelector("strong").textContent = item.match.candidate.title;
    row.querySelector(".meta").textContent = item.explanation;
    const importButton = row.querySelector(".import-action");
    importButton.disabled = item.action !== "import";
    importButton.onclick = async () => {
      try {
        await api("/api/actions/import", { method: "POST", body: JSON.stringify({ download_id: item.match.download.id, candidate_id: item.match.candidate.media_id }) });
        toast("Import verified");
        loadDashboard();
      } catch (error) { toast(error.message); }
    };
    node.append(row);
  });
  loadUndo();
}

async function loadUndo() {
  const data = await api("/api/undo");
  const node = $("#undo-list");
  node.innerHTML = "";
  if (!data.items.length) { empty(node, "No undo records yet."); return; }
  data.items.forEach((item) => {
    const row = document.createElement("article");
    row.className = "row-card";
    row.innerHTML = `<div><strong></strong><div class="meta"></div></div><button class="text-button undo-action">Undo</button>`;
    row.querySelector("strong").textContent = item.media_id;
    row.querySelector(".meta").textContent = `${item.app} · ${item.path} · ${item.status}`;
    const undoButton = row.querySelector(".undo-action");
    undoButton.disabled = item.status !== "available";
    undoButton.onclick = async () => {
      try { await api("/api/actions/undo", { method: "POST", body: JSON.stringify({ undo_id: item.id }) }); toast("Undo requested"); loadPlan(); }
      catch (error) { toast(error.message); }
    };
    node.append(row);
  });
}

async function loadDownloads() {
  const data = await api("/api/downloads");
  const node = $("#download-list");
  node.innerHTML = "";
  if (!data.items.length) { empty(node, "No qBittorrent activity yet."); return; }
  data.items.forEach((item) => {
    const row = document.createElement("article");
    row.className = "row-card";
    row.innerHTML = `<div><strong></strong><div class="progress"><span style="width:${Math.round(item.progress * 100)}%"></span></div><div class="meta">${Math.round(item.progress * 100)}% · ${item.path}</div></div><button class="text-button repair">Repair</button>`;
    row.querySelector("strong").textContent = item.name;
    row.querySelector(".repair").onclick = async () => { await api("/api/actions/repair", { method: "POST", body: JSON.stringify({ download_id: item.id }) }); toast("Repair job queued"); };
    node.append(row);
  });
}

async function loadLibrary() {
  const data = await api("/api/library");
  const node = $("#library-list");
  node.innerHTML = "";
  if (!data.items.length) { empty(node, "No verified Jellyfin items yet. Refresh after an import."); return; }
  data.items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "library-card";
    card.innerHTML = `<div class="cover"></div><strong></strong><div class="meta"></div>${statusChip(item.status)}`;
    card.querySelector("strong").textContent = item.title;
    card.querySelector(".meta").textContent = item.path;
    node.append(card);
  });
}

async function loadActivity() {
  const data = await api("/api/audit?limit=100");
  const node = $("#activity-list");
  node.innerHTML = "";
  if (!data.items.length) { empty(node, "No activity recorded yet."); return; }
  data.items.forEach((item) => {
    const row = document.createElement("article");
    row.className = "activity-card";
    row.innerHTML = `<time></time><div><strong></strong><div class="meta"></div></div>`;
    row.querySelector("time").textContent = item.timestamp;
    row.querySelector("strong").textContent = item.event;
    row.querySelector(".meta").textContent = item.message;
    node.append(row);
  });
  const jobs = await api("/api/jobs");
  const jobNode = $("#job-list");
  jobNode.innerHTML = "";
  if (!jobs.items.length) empty(jobNode, "No background jobs yet.");
  jobs.items.forEach((job) => {
    const row = document.createElement("article");
    row.className = "row-card";
    row.innerHTML = `<div><strong></strong><div class="meta"></div></div><button class="text-button retry-action">Retry</button>`;
    row.querySelector("strong").textContent = job.kind;
    row.querySelector(".meta").textContent = `${job.status} · ${job.message}`;
    const retryButton = row.querySelector(".retry-action");
    retryButton.disabled = job.status !== "failed";
    retryButton.onclick = async () => {
      try { await api(`/api/jobs/${job.id}/retry`, { method: "POST", body: "{}" }); toast("Retry queued"); loadActivity(); }
      catch (error) { toast(error.message); }
    };
    jobNode.append(row);
  });
}

async function login(event) {
  event.preventDefault();
  const token = new FormData(event.target).get("token");
  try {
    await api("/api/auth/login", { method: "POST", body: JSON.stringify({ token }) });
    state.token = token;
    localStorage.setItem("media-session", token);
    $("#login-dialog").close();
    loadDashboard();
  } catch (error) { $("#login-feedback").textContent = error.message; }
}

function bind() {
  $$(".nav-item").forEach((button) => button.onclick = () => showView(button.dataset.view));
  $$("[data-view-link]").forEach((button) => button.onclick = () => showView(button.dataset.viewLink));
  $("#request-form").onsubmit = submitRequest;
  $("#login-form").onsubmit = login;
  $("#refresh-all").onclick = loadDashboard;
  $("#refresh-requests").onclick = loadRequests;
  $("#refresh-plan").onclick = loadPlan;
  $("#refresh-downloads").onclick = loadDownloads;
  $("#refresh-library").onclick = async () => {
    try { await api("/api/library/refresh", { method: "POST", body: "{}" }); toast("Jellyfin refresh queued"); }
    catch (error) { toast(error.message); }
  };
  $("#scan-library").onclick = async () => {
    try { await api("/api/library/scan", { method: "POST", body: "{}" }); toast("Jellyfin scan queued"); }
    catch (error) { toast(error.message); }
  };
}

bind();
loadDashboard();
setInterval(() => {
  if (state.view === "overview") loadDashboard();
  if (state.view === "imports") loadDownloads();
}, 5000);
