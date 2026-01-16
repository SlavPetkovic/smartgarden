let moistureChart = null;
let envChart = null;

function fmtTimeLabel(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit" });
  } catch {
    return iso;
  }
}

function fmtSeconds(s) {
  if (s === null || s === undefined) return "—";
  const n = Number(s);
  if (Number.isNaN(n)) return "—";
  if (n < 60) return `${n.toFixed(0)}s`;
  const m = Math.floor(n / 60);
  const r = Math.round(n % 60);
  return `${m}m ${r}s`;
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  return await res.json();
}


function buildMoistureChart(payload) {
  const canvas = document.getElementById("chart-moisture");

  // IMPORTANT: Chart.js will ignore CSS height unless maintainAspectRatio=false.
  // So make sure the *container* (or the canvas parent) has a fixed height in CSS.
  const ctx = canvas.getContext("2d");

  const labels = payload.readings.map(r => fmtTimeLabel(r.timestamp));
  const moisture = payload.readings.map(r => r.soil_moisture);

  // Support either field name (depending on your API)
  const irrigMarkers = (payload.irrigations || []).map(e => ({
    x: fmtTimeLabel(e.timestamp),
    y: (e.soil_moisture_at_event ?? e.moisture_at_time ?? null),
    seconds: e.duration_seconds,
    reason: e.reason
  }));

  // We display irrigations as scatter points overlaying the line
  const scatterData = irrigMarkers
    .filter(p => p.y !== null && p.y !== undefined)
    .map(p => ({ x: p.x, y: p.y, seconds: p.seconds, reason: p.reason }));

  if (moistureChart) moistureChart.destroy();

  moistureChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Soil Moisture",
          data: moisture,
          tension: 0.25,
          pointRadius: 0,
          borderWidth: 2
        },
        {
          type: "scatter",
          label: "Irrigation Events",
          data: scatterData,
          pointRadius: 5,
          pointHoverRadius: 7
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false, // ✅ THIS is the key to letting height shrink
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { labels: { color: "rgba(255,255,255,0.9)" } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              if (ctx.dataset.type === "scatter") {
                const p = ctx.raw;
                const dose = fmtSeconds(p.seconds);
                const reason = p.reason ? ` — ${p.reason}` : "";
                return `Irrigated ${dose}${reason}`;
              }
              return `Soil Moisture: ${ctx.raw}`;
            }
          }
        }
      },
      scales: {
        x: {
          ticks: {
            color: "rgba(255,255,255,0.8)",
            maxRotation: 35,
            minRotation: 35,
            autoSkip: true,
            maxTicksLimit: 12 // ✅ fewer labels = less vertical space
          },
          grid: { color: "rgba(255,255,255,0.08)" }
        },
        y: {
          ticks: { color: "rgba(255,255,255,0.8)" },
          grid: { color: "rgba(255,255,255,0.08)" }
        }
      }
    }
  });
}



function buildEnvChart(payload) {
  const ctx = document.getElementById("chart-env").getContext("2d");
  const labels = payload.readings.map(r => fmtTimeLabel(r.timestamp));

  const temp = payload.readings.map(r => r.temperature_c);
  const hum = payload.readings.map(r => r.humidity_pct);
  const light = payload.readings.map(r => r.light_lux);

  const showTemp = document.getElementById("toggle-temp").checked;
  const showHum = document.getElementById("toggle-humidity").checked;
  const showLight = document.getElementById("toggle-light").checked;

  const datasets = [];
  if (showTemp) datasets.push({ label: "Temp (°C)", data: temp, tension: 0.25, pointRadius: 0, borderWidth: 2 });
  if (showHum) datasets.push({ label: "Humidity (%)", data: hum, tension: 0.25, pointRadius: 0, borderWidth: 2 });
  if (showLight) datasets.push({ label: "Light (lux)", data: light, tension: 0.25, pointRadius: 0, borderWidth: 2 });

  if (envChart) envChart.destroy();

  envChart = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false, // ✅ match moisture chart behavior
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { labels: { color: "rgba(255,255,255,0.9)" } }
      },
      scales: {
        x: {
          ticks: {
            color: "rgba(255,255,255,0.8)",
            maxRotation: 35,
            minRotation: 35,
            autoSkip: true,
            maxTicksLimit: 12 // ✅ match moisture chart feel
          },
          grid: { color: "rgba(255,255,255,0.08)" }
        },
        y: {
          ticks: { color: "rgba(255,255,255,0.8)" },
          grid: { color: "rgba(255,255,255,0.08)" }
        }
      }
    }
  });
}




function renderDecisionTable(rows) {
  const tbody = document.getElementById("decision-table-body");
  tbody.innerHTML = "";

  if (!rows || rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="opacity:.85;">No decisions yet.</td></tr>`;
    return;
  }

  for (const r of rows) {
    let dotCls = "green";
    if (r.decision === "blocked") dotCls = "amber";
    if (r.decision === "no_action") dotCls = "red";

    const decisionLabel = r.decision === "irrigate" ? "Irrigate" : (r.decision === "blocked" ? "Blocked" : "No action");
    const dose = r.pump_duration_seconds ? fmtSeconds(r.pump_duration_seconds) : "—";

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${fmtTimeLabel(r.timestamp)}</td>
      <td>
        <span class="decision-pill">
          <span class="dot ${dotCls}"></span>${decisionLabel}
        </span>
      </td>
      <td>${r.reason ?? ""}</td>
      <td>${dose}</td>
    `;
    tbody.appendChild(tr);
  }
}

function setText(id, txt) {
  const el = document.getElementById(id);
  if (el) el.textContent = txt;
}

async function loadAnalytics() {
  const hours = document.getElementById("range-hours").value;

  // summary + timeseries
  const summary = await fetchJson(`/api/analytics/summary?hours=${hours}`);
  const ts = await fetchJson(`/api/analytics/timeseries?hours=${hours}`);
  const decisions = await fetchJson(`/api/analytics/decisions?hours=${hours}&limit=20`);

  setText("kpi-avg-moisture", summary.avg_soil_moisture !== null ? `${summary.avg_soil_moisture.toFixed(1)}%` : "--");
  setText("kpi-water-used", `${fmtSeconds(summary.water_used_24h)} / ${fmtSeconds(summary.water_used_7d)}`);
  setText("kpi-stress-avoided", summary.stress_events_avoided_24h ?? "--");
  setText("kpi-gain", summary.absorption_gain_per_sec !== null ? summary.absorption_gain_per_sec.toFixed(3) : "--");

  buildMoistureChart(ts);
  buildEnvChart(ts);
  renderDecisionTable(decisions.items);
}

function wireInteractions() {
  document.getElementById("range-hours").addEventListener("change", () => loadAnalytics());

  for (const id of ["toggle-temp", "toggle-humidity", "toggle-light"]) {
    document.getElementById(id).addEventListener("change", async () => {
      const hours = document.getElementById("range-hours").value;
      const ts = await fetchJson(`/api/analytics/timeseries?hours=${hours}`);
      buildEnvChart(ts);
    });
  }
}

(async function init() {
  wireInteractions();
  await loadAnalytics();
})();
