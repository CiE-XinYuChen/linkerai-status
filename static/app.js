const statusLabels = {
  operational: "All Systems Operational",
  degraded_performance: "Degraded Performance",
  partial_outage: "Partial Outage",
  major_outage: "Major Outage",
  unknown: "Status Unknown",
};

const statusOrder = {
  major_outage: 4,
  partial_outage: 3,
  degraded_performance: 2,
  operational: 1,
  unknown: 0,
};

const root = document.getElementById("app");
const pollInterval = Number(root?.dataset?.pollInterval || 60) * 1000;

const formatTime = (iso) => {
  if (!iso) return "–";
  const d = new Date(iso);
  const date = d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  const time = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${date} at ${time}`;
};

const statusClass = (status) => `status-${status || "unknown"}`;

const computeHistory = (incidents) => {
  const days = [];
  const now = new Date();
  for (let i = 6; i >= 0; i -= 1) {
    const day = new Date(now);
    day.setDate(now.getDate() - i);
    day.setHours(0, 0, 0, 0);
    const end = new Date(day);
    end.setHours(23, 59, 59, 999);

    const worst = incidents
      .filter((inc) => {
        const ts = new Date(inc.started_at);
        return ts >= day && ts <= end;
      })
      .reduce((agg, inc) => {
        return statusOrder[inc.status] > statusOrder[agg]
          ? inc.status
          : agg;
      }, "operational");

    days.push({
      label: day.toLocaleDateString(undefined, { weekday: "short" }),
      status: worst,
    });
  }
  return days;
};

const renderComponentRow = (service) => {
  return `
    <div class="component-row">
      <div class="component-name">
        <div>${service.component || service.name}</div>
        <div class="component-subtitle">${service.name}</div>
      </div>
      <div class="component-meta">
        <span class="badge ${statusClass(service.status)}">${statusLabels[service.status] || service.status}</span>
        <div class="meta-note">${service.message || ""}</div>
        ${
          service.response_ms
            ? `<div class="meta-note">${service.response_ms} ms</div>`
            : `<div class="meta-note muted">n/a</div>`
        }
      </div>
    </div>
  `;
};

const renderIncidents = (incidents) => {
  if (!incidents.length) {
    return `<div class="empty">No incidents reported in the configured window.</div>`;
  }

  return incidents
    .map(
      (incident) => `
      <div class="incident">
        <div class="incident-header">
          <div class="incident-title">${incident.service}</div>
          <span class="badge ${statusClass(incident.status)}">${statusLabels[incident.status] || incident.status}</span>
        </div>
        <div class="incident-body">${incident.summary}</div>
        <div class="incident-date">${formatTime(incident.started_at)}</div>
      </div>
    `
    )
    .join("");
};

const renderHistory = (history) => {
  return `
    <div class="history">
      ${history
        .map(
          (day) => `
          <div class="history-day">
            <div class="history-bar ${statusClass(day.status)}"></div>
            <div class="history-label">${day.label}</div>
          </div>
        `
        )
        .join("")}
    </div>
  `;
};

const renderApp = (data) => {
  const overall = data.overall_status || "unknown";
  const services = data.services || [];
  const incidents = data.incidents || [];
  const history = computeHistory(incidents);

  root.innerHTML = `
    <div class="page">
      <header class="navbar">
        <div class="brand">
          <div class="brand-mark"></div>
          <div>LinkerAI Status</div>
        </div>
        <div class="nav-actions">
          <a class="link" href="/api/status">API</a>
          <button class="ghost">Subscribe</button>
        </div>
      </header>

      <section class="banner ${statusClass(overall)}">
        <div class="banner-title">${statusLabels[overall] || overall}</div>
        <div class="banner-meta">Updated ${formatTime(data.last_updated)}</div>
      </section>

      <section class="card">
        <div class="card-header">
          <div>
            <div class="eyebrow">Current status</div>
            <h2>Components</h2>
          </div>
          <div class="tiny">Auto-refreshing every ${Math.round(
            pollInterval / 1000
          )}s</div>
        </div>
        ${services.length ? services.map(renderComponentRow).join("") : `<div class="empty">No services configured. Add endpoints in config.yaml.</div>`}
      </section>

      <section class="card">
        <div class="card-header">
          <div>
            <div class="eyebrow">Historical</div>
            <h2>Past 7 days</h2>
          </div>
        </div>
        ${renderHistory(history)}
      </section>

      <section class="card">
        <div class="card-header">
          <div>
            <div class="eyebrow">Updates</div>
            <h2>Incidents</h2>
          </div>
        </div>
        ${renderIncidents(incidents)}
      </section>
    </div>
  `;
};

const renderError = (message) => {
  root.innerHTML = `
    <div class="page">
      <div class="banner status-major_outage">
        <div class="banner-title">Unable to load status</div>
        <div class="banner-meta">${message}</div>
      </div>
    </div>
  `;
};

const fetchAndRender = async () => {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error(`Request failed with ${res.status}`);
    const data = await res.json();
    renderApp(data);
  } catch (err) {
    renderError(err.message);
  }
};

const bootstrap = () => {
  renderError("Loading status…");
  fetchAndRender();
  setInterval(fetchAndRender, pollInterval);
};

bootstrap();
