const state = {
  latest: null,
  history: [],
};

const componentLabels = {
  short_pressure: "Short pressure",
  volume_pressure: "Volume pressure",
  price_momentum: "Price momentum",
  social_heat: "Social heat",
  leader_concentration: "Leader focus",
};

const $ = (id) => document.getElementById(id);

function num(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function compact(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value));
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const cls = Number(value) >= 0 ? "positive" : "negative";
  return `<span class="${cls}">${num(value)}%</span>`;
}

function localTime(iso) {
  if (!iso) return "--";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function scoreClass(score) {
  if (score === null || score === undefined) return "neutral";
  if (score >= 75) return "positive";
  if (score >= 45) return "warning";
  return "negative";
}

async function fetchJson(path) {
  const response = await fetch(`${path}?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

async function loadData() {
  try {
    const [latest, history] = await Promise.all([
      fetchJson("data/latest.json"),
      fetchJson("data/history.json").catch(() => []),
    ]);
    state.latest = latest;
    state.history = Array.isArray(history) ? history : [];
    render();
  } catch (error) {
    setText("verdict", `데이터 로드 실패: ${error.message}`);
    setText("last-updated", "Load failed");
  }
}

function render() {
  const latest = state.latest;
  const spce = latest.symbols.SPCE;
  const gme = latest.symbols.GME;
  const score = spce.score.score;
  const components = spce.score.components;

  setText("last-updated", localTime(latest.generated_at_utc));
  $("score-main").textContent = score === null ? "--" : Math.round(score);
  $("score-main").className = scoreClass(score);
  setText("score-label", spce.score.label);
  setText("verdict", spce.score.verdict_ko);
  setText("confidence-chip", `confidence ${num(spce.score.confidence * 100, 0)}%`);
  setText("window-chip", `${latest.window_hours}h`);

  $("metric-short").innerHTML = `${num(spce.market.short_percent_float)}%`;
  $("metric-move").innerHTML = pct(spce.market.price_change_5d_pct);
  $("metric-volume").textContent = `${num(spce.market.volume_ratio_20d)}x`;
  $("metric-social").textContent = components.social_heat === null ? "--" : `${num(components.social_heat, 0)}`;
  $("metric-leader").textContent = components.leader_concentration === null ? "--" : `${num(components.leader_concentration, 0)}`;

  renderComponents(components);
  renderSocial(spce.social);
  renderWsbTrending(latest.wsb_trending);
  renderComparison(spce, latest.baseline);
  renderGme(gme);
  renderChart();
}

function renderComponents(components) {
  const rows = Object.entries(components).map(([key, value]) => {
    const width = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, Number(value)));
    return `
      <div class="bar-row">
        <div class="bar-meta">
          <span>${componentLabels[key] || key}</span>
          <strong>${value === null || value === undefined ? "--" : num(value, 0)}</strong>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width: ${width}%"></div></div>
      </div>
    `;
  });
  $("component-bars").innerHTML = rows.join("");
}

function renderSocial(social) {
  const rows = ["reddit", "x", "youtube"].map((source) => {
    const item = social[source] || {};
    const top = item.top_author ? `${item.top_author} (${num((item.top_author_share || 0) * 100, 0)}%)` : "--";
    return `
      <tr>
        <td>${source.toUpperCase()}</td>
        <td>${item.mention_count === null || item.mention_count === undefined ? "--" : compact(item.mention_count)}</td>
        <td>${top}</td>
        <td><span class="status-chip">${item.status || "--"}</span></td>
      </tr>
    `;
  });
  $("social-table").innerHTML = rows.join("");
}

function renderWsbTrending(wsb) {
  if (!wsb || !Array.isArray(wsb.items) || !wsb.items.length) {
    setText("wsb-status", "no data");
    $("wsb-method").textContent = "WSB data unavailable";
    $("wsb-chart").innerHTML = `<div class="empty-state">No WSB ranking data yet</div>`;
    $("wsb-table").innerHTML = "";
    return;
  }

  const sourceLabel = wsb.sentiment_source === "reddit_oauth_bow_sample" ? "BoW sentiment sample" : "mentions only";
  setText("wsb-status", `${wsb.window_hours || 24}h · ${sourceLabel}`);
  $("wsb-method").textContent = "ApeWisdom WSB 24h mention ranking; Reddit BoW sentiment when keys exist.";
  $("wsb-method").title = wsb.methodology || "";
  $("wsb-chart").innerHTML = stackedMentionChart(wsb.items.slice(0, 12));
  $("wsb-table").innerHTML = wsb.items.slice(0, 10).map((item) => {
    const prior = item.mentions_24h_ago === null || item.mentions_24h_ago === undefined ? "--" : compact(item.mentions_24h_ago);
    const net = item.net_sentiment === null || item.net_sentiment === undefined ? "--" : `${num(item.net_sentiment * 100, 0)}%`;
    const netClass = item.net_sentiment > 0.05 ? "positive" : item.net_sentiment < -0.05 ? "negative" : "neutral";
    return `
      <tr>
        <td><strong>${esc(item.ticker)}</strong></td>
        <td>${compact(item.mentions)}</td>
        <td>${prior}</td>
        <td class="${netClass}">${net}</td>
      </tr>
    `;
  }).join("");
}

function stackedMentionChart(items) {
  const width = 940;
  const height = 360;
  const pad = { top: 34, right: 16, bottom: 78, left: 54 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const maxMentions = Math.max(1, ...items.map((item) => Number(item.mentions) || 0));
  const gap = 13;
  const barW = Math.max(22, (innerW - gap * (items.length - 1)) / Math.max(1, items.length));
  const y = (value) => pad.top + innerH - (value / maxMentions) * innerH;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => Math.round(maxMentions * ratio));
  const grid = ticks.map((tick) => `
    <line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#dbe2dc"/>
    <text x="12" y="${y(tick) + 4}" fill="#69736f" font-size="12">${compact(tick)}</text>
  `).join("");
  const bars = items.map((item, index) => {
    const x = pad.left + index * (barW + gap);
    const positive = Number(item.positive) || 0;
    const negative = Number(item.negative) || 0;
    const neutral = Number(item.neutral) || 0;
    const total = Math.max(positive + negative + neutral, Number(item.mentions) || 0);
    const posH = (positive / maxMentions) * innerH;
    const negH = (negative / maxMentions) * innerH;
    const neuH = (neutral / maxMentions) * innerH;
    const base = pad.top + innerH;
    const highlight = item.ticker === "SPCE" ? `<rect x="${x - 4}" y="${y(total) - 8}" width="${barW + 8}" height="${(total / maxMentions) * innerH + 12}" rx="7" fill="none" stroke="#2f6fb0" stroke-width="2"/>` : "";
    return `
      ${highlight}
      <rect x="${x}" y="${base - posH}" width="${barW}" height="${posH}" fill="#0f8a5f"/>
      <rect x="${x}" y="${base - posH - negH}" width="${barW}" height="${negH}" fill="#b54242"/>
      <rect x="${x}" y="${base - posH - negH - neuH}" width="${barW}" height="${neuH}" fill="#7b7d86"/>
      <text transform="translate(${x + barW / 2} ${height - 42}) rotate(-34)" text-anchor="end" fill="#18201d" font-size="13" font-weight="700">${esc(item.ticker)}</text>
      <text x="${x + barW / 2}" y="${Math.max(18, y(total) - 10)}" text-anchor="middle" fill="#69736f" font-size="12">${compact(total)}</text>
    `;
  }).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="WallStreetBets trending stock mentions">
      <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
      <text x="${pad.left}" y="18" fill="#69736f" font-size="13">Company mentions</text>
      <circle cx="${width - 280}" cy="15" r="7" fill="#0f8a5f"/><text x="${width - 267}" y="19" fill="#18201d" font-size="13">Positive</text>
      <circle cx="${width - 190}" cy="15" r="7" fill="#b54242"/><text x="${width - 177}" y="19" fill="#18201d" font-size="13">Negative</text>
      <circle cx="${width - 96}" cy="15" r="7" fill="#7b7d86"/><text x="${width - 83}" y="19" fill="#18201d" font-size="13">Neutral</text>
      ${grid}
      <line x1="${pad.left}" x2="${width - pad.right}" y1="${pad.top + innerH}" y2="${pad.top + innerH}" stroke="#aeb9b2"/>
      ${bars}
    </svg>
  `;
}

function renderComparison(spce, baseline) {
  const rows = [
    ["Short float", `${num(spce.market.short_percent_float)}%`, `${num(baseline.short_percent_float)}%`],
    ["Short ratio", num(spce.market.short_ratio), "n/a"],
    ["5D move", pct(spce.market.price_change_5d_pct), "n/a"],
    ["Volume / 20D", `${num(spce.market.volume_ratio_20d)}x`, "n/a"],
    ["Similarity", `${num(spce.score.score, 0)}/100`, "100 anchor"],
  ];
  $("comparison-table").innerHTML = rows
    .map(([metric, current, base]) => `<tr><td>${metric}</td><td>${current}</td><td>${base}</td></tr>`)
    .join("");
}

function renderGme(gme) {
  const items = [
    ["Price", `$${num(gme.market.price)}`],
    ["5D move", `${num(gme.market.price_change_5d_pct)}%`],
    ["Short float", `${num(gme.market.short_percent_float)}%`],
    ["Volume / 20D", `${num(gme.market.volume_ratio_20d)}x`],
    ["Similarity", `${num(gme.score.score, 0)}/100`],
  ];
  $("gme-strip").innerHTML = items
    .map(([label, value]) => `<div class="strip-item"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function renderChart() {
  const points = state.history
    .map((item) => ({
      time: new Date(item.generated_at_utc).getTime(),
      value: item.symbols?.SPCE?.score,
    }))
    .filter((item) => Number.isFinite(item.time) && item.value !== null && item.value !== undefined);
  $("score-chart").innerHTML = lineChart(points);
}

function lineChart(points) {
  const width = 900;
  const height = 290;
  const pad = { top: 18, right: 22, bottom: 34, left: 44 };
  if (!points.length) {
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="No chart data"><text x="44" y="145" fill="#69736f">No history yet</text></svg>`;
  }
  const minX = Math.min(...points.map((d) => d.time));
  const maxX = Math.max(...points.map((d) => d.time));
  const xSpan = Math.max(1, maxX - minX);
  const minY = 0;
  const maxY = 100;
  const x = (value) => pad.left + ((value - minX) / xSpan) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - ((value - minY) / (maxY - minY)) * (height - pad.top - pad.bottom);
  const path = points.map((d, index) => `${index === 0 ? "M" : "L"} ${x(d.time).toFixed(2)} ${y(d.value).toFixed(2)}`).join(" ");
  const last = points[points.length - 1];
  const grid = [0, 25, 50, 75, 100]
    .map((tick) => `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#dbe2dc"/><text x="8" y="${y(tick) + 4}" fill="#69736f" font-size="12">${tick}</text>`)
    .join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="SPCE similarity history">
      <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
      ${grid}
      <line x1="${pad.left}" x2="${width - pad.right}" y1="${height - pad.bottom}" y2="${height - pad.bottom}" stroke="#aeb9b2"/>
      <path d="${path}" fill="none" stroke="#137f8f" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${x(last.time)}" cy="${y(last.value)}" r="6" fill="#0f8a5f"/>
      <text x="${width - pad.right - 110}" y="${pad.top + 12}" fill="#18201d" font-size="13" font-weight="700">Latest ${num(last.value, 0)}/100</text>
    </svg>
  `;
}

$("refresh-button").addEventListener("click", loadData);
loadData();
setInterval(loadData, 300000);
