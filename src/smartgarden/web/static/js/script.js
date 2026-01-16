async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  const data = await response.json();
  if (data && data.error) throw new Error(data.error);
  return data;
}

async function fetchLatest() {
  // Legacy first, then new
  const endpoints = ["/sensors/latest", "/api/sensors/latest"];
  let lastError = null;

  for (const url of endpoints) {
    try {
      return await fetchJson(url);
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError || new Error("Unable to fetch latest data");
}

function setValue(selector, value) {
  const el = document.querySelector(selector);
  if (!el) return;
  el.textContent = (value !== undefined && value !== null) ? value : "--";
}

function setAllError(on) {
  const metricCards = document.querySelectorAll(".metric-card");
  metricCards.forEach(card => {
    if (on) card.classList.add("error");
    else card.classList.remove("error");
  });
}

function setStatusValue(id, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text ?? "--";
  el.classList.remove("good", "warn", "bad");
  if (cls) el.classList.add(cls);
}

function formatSeconds(s) {
  if (s === undefined || s === null || Number.isNaN(Number(s))) return "--";
  const n = Number(s);
  if (n < 60) return `${n.toFixed(0)}s`;
  const m = Math.floor(n / 60);
  const r = Math.round(n % 60);
  return `${m}m ${r}s`;
}

function formatIsoToLocal(iso) {
  if (!iso) return "--";
  try {
    const d = new Date(iso);
    // Show local date/time concisely
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    });
  } catch {
    return iso;
  }
}

async function refreshStatusBar() {
  try {
    const s = await fetchJson("/api/status");

    const within = !!(s.time && s.time.within_watering_window);
    const startH = s.time?.window_start_hour;
    const endH = s.time?.window_end_hour;

    const wateringText = within
      ? `Allowed (${startH}:00–${endH}:00)`
      : `Blocked (${startH}:00–${endH}:00)`;

    setStatusValue("status-watering", wateringText, within ? "good" : "warn");

    const used = s.constraints?.daily_irrigation_used_seconds;
    const total = s.constraints?.daily_irrigation_budget_seconds;
    const remaining = s.constraints?.daily_irrigation_remaining_seconds;

    const budgetText = `${formatSeconds(used)} / ${formatSeconds(total)} (rem ${formatSeconds(remaining)})`;
    // warn if < 20% left
    let budgetClass = "good";
    if (typeof total === "number" && total > 0 && typeof remaining === "number") {
      const frac = remaining / total;
      if (frac <= 0.2) budgetClass = "warn";
      if (frac <= 0.05) budgetClass = "bad";
    }
    setStatusValue("status-budget", budgetText, budgetClass);

    const lastIrr = s.control_state?.last_irrigation_at;
    setStatusValue("status-last-irrigation", formatIsoToLocal(lastIrr), lastIrr ? null : "warn");

    const gain = s.control_state?.absorption_gain_per_sec;
    const gainText = (gain !== undefined && gain !== null) ? Number(gain).toFixed(3) : "--";
    setStatusValue("status-gain", gainText, null);
  } catch (err) {
    console.error("Error fetching /api/status:", err);
    // Don’t turn the whole UI red—just mark status fields unknown
    setStatusValue("status-watering", "--", "warn");
    setStatusValue("status-budget", "--", "warn");
    setStatusValue("status-last-irrigation", "--", "warn");
    setStatusValue("status-gain", "--", "warn");
  }
}

async function refreshUI() {
  try {
    const data = await fetchLatest();

    // Support BOTH payload styles:
    const temperature = (data.temperature !== undefined) ? data.temperature : data.temperature_c;
    const humidity = (data.humidity !== undefined) ? data.humidity : data.humidity_pct;
    const pressure = (data.pressure !== undefined) ? data.pressure : data.pressure_hpa;
    const luminosity = (data.luminosity !== undefined) ? data.luminosity : data.light_lux;
    const soil_moisture = data.soil_moisture;
    const soil_temperature = (data.soil_temperature !== undefined) ? data.soil_temperature : data.soil_temperature_c;

    setValue("#temperature .value", temperature);
    setValue("#humidity .value", humidity);
    setValue("#pressure .value", pressure);
    setValue("#luminosity .value", luminosity);
    setValue("#soil-moisture .value", soil_moisture);
    setValue("#soil-temperature .value", soil_temperature);

    setAllError(false);
  } catch (error) {
    console.error("Error fetching latest sensor data:", error);

    const valueElements = document.querySelectorAll(".metric-value .value");
    valueElements.forEach(el => el.textContent = "--");

    setAllError(true);
  }

  // Independently refresh status bar (even if latest fails)
  await refreshStatusBar();
}

// Load and refresh every 5 seconds
refreshUI();
setInterval(refreshUI, 5000);
