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

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 1,
    notation: "compact",
    style: "currency",
  }).format(Number(value));
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

function signedCompact(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const sign = Number(value) > 0 ? "+" : "";
  const cls = Number(value) >= 0 ? "negative" : "positive";
  return `<span class="${cls}">${sign}${compact(value)}</span>`;
}

function signedPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const sign = Number(value) > 0 ? "+" : "";
  const cls = Number(value) >= 0 ? "negative" : "positive";
  return `<span class="${cls}">${sign}${num(value, 1)}%</span>`;
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
    setText("last-updated", "Load failed");
  }
}

function render() {
  const latest = state.latest;
  const spce = latest.symbols.SPCE;
  const gme = latest.symbols.GME;
  const components = spce.score.components;

  setText("last-updated", localTime(latest.generated_at_utc));
  setText("confidence-chip", `confidence ${num(spce.score.confidence * 100, 0)}%`);
  setText("window-chip", `${latest.window_hours}h`);

  $("metric-short").innerHTML = `${num(spce.market.short_percent_float)}%`;
  $("metric-move").innerHTML = pct(spce.market.price_change_5d_pct);
  $("metric-volume").textContent = `${num(spce.market.volume_ratio_20d)}x`;
  $("metric-social").textContent = components.social_heat === null ? "--" : `${num(components.social_heat, 0)}`;
  $("metric-leader").textContent = components.leader_concentration === null ? "--" : `${num(components.leader_concentration, 0)}`;

  renderComponents(components);
  renderSocial(spce.social);
  renderShortDeepDive(spce.market);
  renderShortExposureContext(latest.short_exposure_context);
  renderGme2021Case(latest.gme_2021_case);
  renderWsbTrending(latest.wsb_trending);
  renderWsbMentionHistory();
  renderComparison(spce, latest.baseline);
  renderGme(gme);
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

function renderShortDeepDive(market) {
  const detail = market.short_deep_dive || {};
  const interest = market.finra_short_interest || {};
  const volume = market.finra_short_volume || {};
  const settlement = detail.official_settlement_date || "--";
  const volumeDate = detail.daily_short_volume_date || "--";
  setText("short-source-chip", settlement === "--" ? "FINRA" : `SI ${settlement} | flow ${volumeDate}`);
  $("short-metric-grid").innerHTML = [
    {
      label: "Shares short",
      value: compact(detail.shares_short),
      sub: `${detail.shares_short_source || "--"} open interest`,
    },
    {
      label: "Short / float",
      value: `${num(detail.short_percent_float)}%`,
      sub: `${compact(detail.float_shares)} float shares`,
    },
    {
      label: "Days to cover",
      value: num(detail.official_days_to_cover),
      sub: `${compact(detail.official_average_daily_volume)} avg vol`,
    },
    {
      label: "Change vs prior",
      value: signedPct(detail.short_interest_change_percent),
      sub: signedCompact(detail.short_interest_change_shares),
    },
    {
      label: "Short notional",
      value: money(detail.short_notional),
      sub: "shares short x price",
    },
    {
      label: "Short / market cap",
      value: `${num(detail.short_notional_to_market_cap_pct)}%`,
      sub: `${money(detail.short_notional)} / ${money(detail.market_cap)}`,
    },
    {
      label: "Daily short volume",
      value: detail.daily_short_volume_ratio === null || detail.daily_short_volume_ratio === undefined ? "--" : `${num(detail.daily_short_volume_ratio * 100, 1)}%`,
      sub: `${detail.daily_short_volume_date || "--"} | 5D ${detail.average_short_volume_ratio_5d === null || detail.average_short_volume_ratio_5d === undefined ? "--" : `${num(detail.average_short_volume_ratio_5d * 100, 1)}%`}`,
    },
  ].map((item) => `
    <article class="short-metric">
      <span>${item.label}</span>
      <strong>${item.value}</strong>
      <small>${item.sub}</small>
    </article>
  `).join("");
  $("short-interest-chart").innerHTML = shortSeriesChart(
    (interest.history || []).map((item) => ({
      label: item.settlement_date,
      time: new Date(item.settlement_date).getTime(),
      value: item.shares_short,
      extra: `DTC ${num(item.days_to_cover)}`,
    })),
    { aria: "SPCE short interest shares", color: "#2f6fb0", formatter: compact, minZero: false },
  );
  $("short-volume-chart").innerHTML = shortSeriesChart(
    (volume.history || []).map((item) => ({
      label: item.trade_date,
      time: new Date(item.trade_date).getTime(),
      value: item.short_volume_ratio,
      extra: `${compact(item.short_volume)} short vol`,
    })),
    { aria: "SPCE daily short volume ratio", color: "#b77a18", formatter: (value) => `${num(value * 100, 0)}%`, minZero: true },
  );
  $("short-caveat").textContent = detail.caveat || "";
}

function renderShortExposureContext(context) {
  if (!context) {
    setText("exposure-status", "no data");
    $("exposure-grid").innerHTML = "";
    $("exposure-top-list").innerHTML = `<div class="empty-state">No short exposure rank data yet</div>`;
    $("exposure-notes").innerHTML = "";
    return;
  }
  const spce = context.spce || {};
  const benchmarks = context.benchmarks || {};
  const top = context.top_short_float || [];
  const rank = spce.rank_in_top100_short_float ? `#${spce.rank_in_top100_short_float}` : ">100";
  const cutoff = benchmarks.top100_cutoff_short_float_pct;
  setText("exposure-status", context.status === "ok" ? "top-100 context" : context.status || "--");
  $("exposure-method").textContent = context.methodology || "SPCE short exposure versus current high-short-interest stocks";
  $("exposure-grid").innerHTML = [
    {
      label: "SPCE short / mkt cap",
      value: `${num(spce.short_notional_to_market_cap_pct)}%`,
      sub: `${money(spce.short_notional)} / ${money(spce.market_cap)}`,
    },
    {
      label: "SPCE short / float",
      value: `${num(spce.short_percent_float)}%`,
      sub: `${num(spce.high_threshold_multiple, 1)}x vs 10% high threshold`,
    },
    {
      label: "Top-100 rank",
      value: rank,
      sub: spce.rank_in_top100_short_float ? "in current public list" : `${spce.top100_count_above_spce ?? "--"} names above SPCE in top list`,
    },
    {
      label: "Top-100 cutoff",
      value: `${num(cutoff)}%`,
      sub: `SPCE is ${num(spce.top100_cutoff_ratio_pct, 1)}% of cutoff`,
    },
    {
      label: "Highest observed",
      value: `${num(benchmarks.top_observed_short_float_pct)}%`,
      sub: benchmarks.top_observed_symbol || "--",
    },
    {
      label: "GME 2021 proxy",
      value: `${num(benchmarks.gme_2021_short_market_cap_proxy_pct)}%+`,
      sub: `${num(benchmarks.gme_2021_short_float_pct)}% short / float`,
    },
  ].map((item) => `
    <article class="exposure-card">
      <span>${item.label}</span>
      <strong>${item.value}</strong>
      <small>${item.sub}</small>
    </article>
  `).join("");
  $("exposure-top-list").innerHTML = top.length ? top.map((item) => `
    <div class="rank-row">
      <span>#${item.rank}</span>
      <strong>${esc(item.symbol)}</strong>
      <em>${num(item.short_percent_float)}%</em>
      <small>${esc(item.company)} · ${esc(item.market_cap || "--")}</small>
    </div>
  `).join("") : `<div class="empty-state">${esc(context.note || "No top short-float list parsed")}</div>`;
  $("exposure-notes").innerHTML = [
    ["Read", spce.classification || "--"],
    ["High threshold", `Short float above ${num(benchmarks.high_short_float_threshold_pct)}% is commonly treated as high; SPCE is ${num(spce.short_percent_float)}%.`],
    ["Top-list caveat", spce.rank_in_top100_short_float ? "SPCE is currently inside the external top-100 short-float list." : "SPCE is below the current top-100 short-float cutoff, so this source cannot give an exact full-universe percentile."],
    ["Source", context.source || "--"],
  ].map(([label, value]) => `
    <div class="benchmark-row">
      <span>${label}</span>
      <strong>${esc(value)}</strong>
    </div>
  `).join("");
}

function renderGme2021Case(caseData) {
  if (!caseData) {
    setText("gme-case-chip", "no data");
    $("gme-case-chart").innerHTML = `<div class="empty-state">No GME baseline data yet</div>`;
    $("gme-case-grid").innerHTML = "";
    $("gme-social-benchmark").innerHTML = "";
    return;
  }
  setText("gme-case-chip", caseData.window || "2021");
  $("gme-case-method").textContent = caseData.methodology_note || "Historical baseline for the meme squeeze regime";
  const peak = caseData.peak || {};
  const base = caseData.base || {};
  const social = caseData.social_benchmark || {};
  const shortInterestPeak = caseData.short_interest_peak || {};
  const shortFlowPeak = caseData.daily_short_sale_volume_peak || {};
  $("gme-case-grid").innerHTML = [
    {
      label: "Short / float peak",
      value: `${num(caseData.short_interest_peak_percent_float)}%`,
      sub: "SEC January 2021",
    },
    {
      label: "Short / mkt cap proxy",
      value: `${num(caseData.short_notional_to_market_cap_pct)}%+`,
      sub: "SEC shares outstanding",
    },
    {
      label: "SI shares peak",
      value: compact(shortInterestPeak.shares_short),
      sub: shortInterestPeak.settlement_date || "--",
    },
    {
      label: "Short volume peak",
      value: compact(shortFlowPeak.short_volume),
      sub: `${shortFlowPeak.trade_date || "--"} | ratio ${shortFlowPeak.short_volume_ratio === null || shortFlowPeak.short_volume_ratio === undefined ? "--" : `${num(shortFlowPeak.short_volume_ratio * 100, 1)}%`}`,
    },
    {
      label: "January gain",
      value: `+${num(caseData.jan_2021_gain_pct, 0)}%`,
      sub: "CNBC recap",
    },
    {
      label: "COVID low to peak",
      value: peak.normalized ? `${num(peak.normalized, 1)}x` : "--",
      sub: base.date && peak.date ? `${base.date} -> ${peak.date}` : peak.date || "--",
    },
    {
      label: "Reddit mentions",
      value: compact(social.reddit_mentions),
      sub: social.window || "--",
    },
    {
      label: "Tweets",
      value: compact(social.tweets),
      sub: social.window || "--",
    },
    {
      label: "YouTube videos",
      value: compact(social.youtube_videos),
      sub: social.window || "--",
    },
  ].map((item) => `
    <article class="case-card">
      <span>${item.label}</span>
      <strong>${item.value}</strong>
      <small>${item.sub}</small>
    </article>
  `).join("");
  $("gme-case-chart").innerHTML = gmeCaseChart(caseData.series || [], caseData.milestones || []);
  $("gme-short-interest-chart").innerHTML = shortSeriesChart(
    (caseData.short_interest_history || []).map((item) => ({
      label: item.settlement_date,
      time: new Date(item.settlement_date).getTime(),
      value: item.shares_short,
      extra: `DTC ${num(item.days_to_cover)} | change ${item.change_percent === null || item.change_percent === undefined ? "--" : `${num(item.change_percent, 1)}%`}`,
    })),
    { aria: "GME 2021 FINRA short interest shares", color: "#7a3e8e", formatter: compact, minZero: false },
  );
  $("gme-short-flow-chart").innerHTML = shortSeriesChart(
    (caseData.daily_short_sale_volume_history || []).map((item) => ({
      label: item.trade_date,
      time: new Date(item.trade_date).getTime(),
      value: item.short_volume_ratio,
      extra: `${compact(item.short_volume)} short / ${compact(item.total_volume)} total`,
    })),
    { aria: "GME 2021 daily short-sale volume ratio", color: "#b77a18", formatter: (value) => `${num(value * 100, 1)}%`, minZero: true },
  );
  $("gme-social-benchmark").innerHTML = [
    ["Source", social.source || "--"],
    ["Window", social.window || "--"],
    ["GME short-cap note", caseData.short_market_cap_note || "--"],
    ["GME short data", `${caseData.short_interest_history_source || "FINRA short interest"}; ${caseData.daily_short_sale_volume_source || "FINRA daily short-sale files"}`],
    ["Current metric caveat", social.note || "--"],
    ["SEC volume note", caseData.sec_volume_note || "--"],
  ].map(([label, value]) => `
    <div class="benchmark-row">
      <span>${label}</span>
      <strong>${esc(value)}</strong>
    </div>
  `).join("");
}

function gmeCaseChart(series, milestones) {
  const points = series
    .map((item) => ({
      date: item.date,
      time: new Date(`${item.date}T00:00:00Z`).getTime(),
      value: item.normalized,
      close: item.close,
    }))
    .filter((item) => Number.isFinite(item.time) && item.value !== null && item.value !== undefined);
  const width = 900;
  const height = 300;
  const pad = { top: 22, right: 28, bottom: 46, left: 58 };
  if (!points.length) {
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="No GME 2021 price data"><text x="58" y="150" fill="#69736f">No GME 2021 price data yet</text></svg>`;
  }
  const minX = Math.min(...points.map((point) => point.time));
  const maxX = Math.max(...points.map((point) => point.time));
  const xSpan = Math.max(1, maxX - minX);
  const maxY = Math.max(2, Math.max(...points.map((point) => Number(point.value))) * 1.12);
  const x = (value) => pad.left + ((value - minX) / xSpan) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - (value / maxY) * (height - pad.top - pad.bottom);
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.time).toFixed(2)} ${y(point.value).toFixed(2)}`).join(" ");
  const grid = [1, Math.round(maxY / 3), Math.round((maxY / 3) * 2), Math.round(maxY)]
    .filter((tick, index, arr) => arr.indexOf(tick) === index)
    .map((tick) => `
      <line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#dbe2dc"/>
      <text x="12" y="${y(tick) + 4}" fill="#69736f" font-size="12">${tick}x</text>
    `).join("");
  const labels = milestones.filter(Boolean).map((milestone, index) => {
    const time = new Date(`${milestone.date}T00:00:00Z`).getTime();
    if (!Number.isFinite(time) || time < minX || time > maxX) return "";
    const labelY = pad.top + 12 + (index % 3) * 15;
    const lineX = x(time);
    const labelX = lineX > width - 250 ? lineX - 5 : lineX + 5;
    const anchor = lineX > width - 250 ? "end" : "start";
    return `
      <line x1="${lineX}" x2="${lineX}" y1="${pad.top}" y2="${height - pad.bottom}" stroke="#b77a18" stroke-dasharray="4 5"/>
      <text x="${labelX}" y="${labelY}" text-anchor="${anchor}" fill="#69736f" font-size="11">${esc(milestone.label)}</text>
    `;
  }).join("");
  const peak = points.reduce((best, point) => (point.value > best.value ? point : best), points[0]);
  const hitMarkers = points.map((point) => {
    const original = series.find((item) => item.date === point.date) || {};
    return `
      <circle class="chart-hit-target" cx="${x(point.time)}" cy="${y(point.value)}" r="7" fill="transparent" stroke="transparent">
        <title>${point.date} | ${num(point.value, 1)}x | close ${num(point.close)} | volume ${compact(original.volume)}</title>
      </circle>
    `;
  }).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="GME 2021 normalized price trend">
      <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
      ${grid}
      ${labels}
      <line x1="${pad.left}" x2="${width - pad.right}" y1="${height - pad.bottom}" y2="${height - pad.bottom}" stroke="#aeb9b2"/>
      <path d="${path}" fill="none" stroke="#b54242" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
      <circle cx="${x(peak.time)}" cy="${y(peak.value)}" r="6" fill="#b54242">
        <title>${peak.date} | peak ${num(peak.value, 1)}x | close ${num(peak.close)}</title>
      </circle>
      ${hitMarkers}
      <text x="${pad.left}" y="${height - 12}" fill="#69736f" font-size="12">${points[0].date}</text>
      <text x="${width - pad.right}" y="${height - 12}" text-anchor="end" fill="#69736f" font-size="12">${points[points.length - 1].date}</text>
    </svg>
  `;
}

function shortSeriesChart(points, options) {
  const filtered = points.filter((point) => Number.isFinite(point.time) && point.value !== null && point.value !== undefined);
  const width = 760;
  const height = 240;
  const pad = { top: 18, right: 20, bottom: 42, left: 58 };
  if (!filtered.length) {
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${options.aria}"><text x="58" y="120" fill="#69736f">No data yet</text></svg>`;
  }
  const values = filtered.map((point) => Number(point.value));
  const minX = Math.min(...filtered.map((point) => point.time));
  const maxX = Math.max(...filtered.map((point) => point.time));
  const xSpan = Math.max(1, maxX - minX);
  const rawMin = options.minZero ? 0 : Math.min(...values);
  const rawMax = Math.max(...values);
  const padding = Math.max((rawMax - rawMin) * 0.18, options.minZero ? rawMax * 0.08 : rawMax * 0.02);
  const minY = options.minZero ? 0 : Math.max(0, rawMin - padding);
  const maxY = Math.max(minY + 0.01, rawMax + padding);
  const x = (value) => pad.left + ((value - minX) / xSpan) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - ((value - minY) / (maxY - minY)) * (height - pad.top - pad.bottom);
  const path = filtered.map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.time).toFixed(2)} ${y(point.value).toFixed(2)}`).join(" ");
  const ticks = [0, 0.5, 1].map((ratio) => minY + (maxY - minY) * ratio);
  const grid = ticks.map((tick) => `
    <line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#dbe2dc"/>
    <text x="8" y="${y(tick) + 4}" fill="#69736f" font-size="12">${options.formatter(tick)}</text>
  `).join("");
  const markers = filtered.map((point) => `
    <circle class="chart-hit-target" cx="${x(point.time)}" cy="${y(point.value)}" r="5.5" fill="${options.color}">
      <title>${point.label} | ${options.formatter(point.value)} | ${point.extra || ""}</title>
    </circle>
  `).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${options.aria}">
      <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
      ${grid}
      <line x1="${pad.left}" x2="${width - pad.right}" y1="${height - pad.bottom}" y2="${height - pad.bottom}" stroke="#aeb9b2"/>
      <path d="${path}" fill="none" stroke="${options.color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"></path>
      ${markers}
      <text x="${pad.left}" y="${height - 12}" fill="#69736f" font-size="12">${filtered[0].label}</text>
      <text x="${width - pad.right}" y="${height - 12}" text-anchor="end" fill="#69736f" font-size="12">${filtered[filtered.length - 1].label}</text>
    </svg>
  `;
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

function renderWsbMentionHistory() {
  const points = state.history
    .map((item) => ({
      time: new Date(item.generated_at_utc).getTime(),
      value: item.wsb?.spce_mentions,
      rank: item.wsb?.spce_rank,
    }))
    .filter((item) => Number.isFinite(item.time) && item.value !== null && item.value !== undefined);
  const latestItem = state.latest?.wsb_trending?.items?.find((item) => item.ticker === "SPCE");
  const latestTime = new Date(state.latest?.generated_at_utc || 0).getTime();
  if (latestItem && Number.isFinite(latestTime) && !points.some((item) => item.time === latestTime)) {
    points.push({
      time: latestTime,
      value: latestItem.mentions,
      rank: latestItem.rank,
    });
  }
  points.sort((a, b) => a.time - b.time);
  const latestPoint = points[points.length - 1];
  setText(
    "wsb-history-latest",
    latestPoint ? `latest ${compact(latestPoint.value)} · rank #${latestPoint.rank || "--"}` : "--",
  );
  $("wsb-history-chart").innerHTML = mentionHistoryChart(points);
}

function mentionHistoryChart(points) {
  const width = 940;
  const height = 280;
  const pad = { top: 22, right: 28, bottom: 44, left: 58 };
  if (!points.length) {
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="No WSB mention history"><text x="58" y="140" fill="#69736f">No SPCE mention history yet</text></svg>`;
  }
  const values = points.map((point) => Number(point.value) || 0);
  const minX = Math.min(...points.map((point) => point.time));
  const maxX = Math.max(...points.map((point) => point.time));
  const xSpan = Math.max(1, maxX - minX);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const padding = Math.max(20, (rawMax - rawMin) * 0.18);
  const minY = Math.max(0, Math.floor(rawMin - padding));
  const maxY = Math.max(minY + 1, Math.ceil(rawMax + padding));
  const x = (value) => pad.left + ((value - minX) / xSpan) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - ((value - minY) / (maxY - minY)) * (height - pad.top - pad.bottom);
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.time).toFixed(2)} ${y(point.value).toFixed(2)}`).join(" ");
  const areaPath = `${path} L ${x(points[points.length - 1].time).toFixed(2)} ${height - pad.bottom} L ${x(points[0].time).toFixed(2)} ${height - pad.bottom} Z`;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => Math.round(minY + (maxY - minY) * ratio));
  const grid = ticks.map((tick) => `
    <line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#dbe2dc"/>
    <text x="10" y="${y(tick) + 4}" fill="#69736f" font-size="12">${compact(tick)}</text>
  `).join("");
  const markers = points.map((point) => `
    <circle class="chart-hit-target" cx="${x(point.time)}" cy="${y(point.value)}" r="5.5" fill="#2f6fb0">
      <title>${new Date(point.time).toLocaleString()} | ${point.value} mentions | rank #${point.rank || "--"}</title>
    </circle>
  `).join("");
  const firstLabel = localTime(new Date(points[0].time).toISOString());
  const lastLabel = localTime(new Date(points[points.length - 1].time).toISOString());
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="SPCE WallStreetBets mention history">
      <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
      ${grid}
      <line x1="${pad.left}" x2="${width - pad.right}" y1="${height - pad.bottom}" y2="${height - pad.bottom}" stroke="#aeb9b2"/>
      <path d="${areaPath}" fill="rgba(47, 111, 176, 0.10)"></path>
      <path d="${path}" fill="none" stroke="#2f6fb0" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
      ${markers}
      <text x="${pad.left}" y="${height - 12}" fill="#69736f" font-size="12">${firstLabel}</text>
      <text x="${width - pad.right}" y="${height - 12}" text-anchor="end" fill="#69736f" font-size="12">${lastLabel}</text>
    </svg>
  `;
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
      <g class="chart-hit-target">
        <title>${item.ticker} | mentions ${compact(total)} | positive ${compact(positive)} | negative ${compact(negative)} | neutral ${compact(neutral)} | rank #${item.rank || "--"}</title>
        ${highlight}
        <rect x="${x}" y="${base - posH}" width="${barW}" height="${posH}" fill="#0f8a5f"/>
        <rect x="${x}" y="${base - posH - negH}" width="${barW}" height="${negH}" fill="#b54242"/>
        <rect x="${x}" y="${base - posH - negH - neuH}" width="${barW}" height="${neuH}" fill="#7b7d86"/>
        <text transform="translate(${x + barW / 2} ${height - 42}) rotate(-34)" text-anchor="end" fill="#18201d" font-size="13" font-weight="700">${esc(item.ticker)}</text>
        <text x="${x + barW / 2}" y="${Math.max(18, y(total) - 10)}" text-anchor="middle" fill="#69736f" font-size="12">${compact(total)}</text>
      </g>
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
  const shortDetail = spce.market.short_deep_dive || {};
  const rows = [
    ["Short float", `${num(spce.market.short_percent_float)}%`, `${num(baseline.short_percent_float)}%`],
    ["Short / market cap", `${num(shortDetail.short_notional_to_market_cap_pct)}%`, `${num(baseline.short_notional_to_market_cap_pct)}%+`],
    ["Short ratio", num(spce.market.short_ratio), "n/a"],
    ["5D move", pct(spce.market.price_change_5d_pct), "n/a"],
    ["Volume / 20D", `${num(spce.market.volume_ratio_20d)}x`, "n/a"],
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
  ];
  $("gme-strip").innerHTML = items
    .map(([label, value]) => `<div class="strip-item"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function activateTab(tabName, updateHash = true) {
  const selected = tabName === "gme" ? "gme" : "main";
  document.querySelectorAll("[data-tab-target]").forEach((button) => {
    const active = button.dataset.tabTarget === selected;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.tabPanel !== selected;
  });
  if (updateHash) {
    const hash = selected === "gme" ? "#gme-compare" : "#main";
    history.replaceState(null, "", `${location.pathname}${location.search}${hash}`);
  }
}

function initTabs() {
  document.querySelectorAll("[data-tab-target]").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tabTarget || "main"));
  });
  const initial = location.hash === "#gme-compare" || location.hash === "#gme" ? "gme" : "main";
  activateTab(initial, false);
}

initTabs();
$("refresh-button").addEventListener("click", loadData);
loadData();
setInterval(loadData, 300000);
