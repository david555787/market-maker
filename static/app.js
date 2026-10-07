// Market Maker frontend: plain JavaScript, no framework, no build step.
//
// The server is the authority: it checks every rule and decides what the
// player may see. This file only sends requests and draws what comes back.
// Every piece of text from the server or the player is put on the page with
// textContent (never innerHTML), so names like "<b>x</b>" show up as plain text.

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const STORAGE_KEY = "marketMakerGameId";
const SERVER_DOWN_MESSAGE = "Server unavailable, please try again";

// The API does not send these backend rules, so we repeat them here.
// If you change them in game_logic.py, change them here too.
const INVENTORY_CAP = 10;        // game_logic.INVENTORY_CAP
const TRADE_SIZE = 1;            // game_logic.TRADE_SIZE
const DEFAULT_MARK_PRICE = 100;  // game_logic.DEFAULT_MARK_PRICE

// Which page sections each screen shows. Everything else gets hidden.
const SCREENS = {
  start: ["start-screen"],
  game: ["game-screen", "charts-section", "history-section"],
  end: ["end-screen", "charts-section", "history-section", "leaderboard-section"],
};
const ALL_SECTION_IDS = [
  "start-screen", "game-screen", "end-screen",
  "charts-section", "history-section", "leaderboard-section",
];

// Buttons that send a request. They are disabled while a request is running.
const BUSY_BUTTON_IDS = ["start-button", "submit-button", "end-early-button", "confirm-end-button"];

// ---------------------------------------------------------------------------
// The one state object
// ---------------------------------------------------------------------------
const state = {
  gameId: null,                          // id of the game being played
  screen: null,                          // "start", "game" or "end"
  busy: false,                           // true while a request is in flight
  charts: { quotes: null, pnl: null },   // Chart.js objects, so we can destroy them before redrawing
};

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
function $(id) {
  return document.getElementById(id);
}

function formatMoney(value) {
  return value === null ? "–" : value.toFixed(2);
}

function formatPnl(value) {
  const text = value.toFixed(2);
  return value > 0 ? "+" + text : text;
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

// Read a color from the CSS variables, so the theme block in style.css
// controls the charts as well.
function cssColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function showMessage(text) {
  const box = $("message");
  box.textContent = text;
  box.hidden = false;
}

function clearMessage() {
  const box = $("message");
  box.textContent = "";
  box.hidden = true;
}

// Disable the request buttons while waiting, so a double click cannot send
// the same request twice. The state.busy check in each handler is a second
// safety net.
function setBusy(isBusy) {
  state.busy = isBusy;
  for (const id of BUSY_BUTTON_IDS) {
    $(id).disabled = isBusy;
  }
}

// ---------------------------------------------------------------------------
// Talking to the server
// ---------------------------------------------------------------------------
function makeError(message, status) {
  const err = new Error(message);
  err.status = status;   // 0 means "no usable answer from our API"
  return err;
}

// The only place that calls fetch. It always returns the parsed JSON data or
// throws an Error whose message is safe to show to the player.
async function api(path, method = "GET", body = null) {
  const options = { method };
  if (body !== null) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, options);
  } catch (err) {
    // fetch only fails like this when there was no answer at all
    // (server stopped, no network).
    throw makeError(SERVER_DOWN_MESSAGE, 0);
  }

  let data;
  try {
    data = await response.json();
  } catch (err) {
    // For example an HTML error page from a proxy or a sleeping server.
    throw makeError("Unexpected response from the server, please try again", 0);
  }

  if (!response.ok) {
    // Our API sends {"error": "..."} for 400, 404 and 409.
    const message = (data && data.error) || `Request failed (${response.status})`;
    throw makeError(message, response.status);
  }
  return data;
}

// Decide what to do with a failed request.
async function handleError(err) {
  if (err.status === 404) {
    // The game does not exist on the server any more (for example the
    // free-tier database was reset), so go back to the start screen.
    forgetGame();
    showScreen("start");
    showMessage("That game no longer exists. Please start a new one.");
    return;
  }
  showMessage(err.message);
  if (err.status === 409) {
    // The game was already finished (for example in another tab).
    // Fetch its final state so the screen matches the server.
    try {
      await loadGame();
    } catch (innerErr) {
      showMessage(innerErr.message);
    }
  }
}

// ---------------------------------------------------------------------------
// Remembering the game across page refreshes
// ---------------------------------------------------------------------------
// localStorage can throw (for example when the browser blocks storage). The
// game still works then; it just cannot resume after a refresh.
function saveGameId(id) {
  state.gameId = id;
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch (err) {
    // ignore: resuming is a convenience, not a requirement
  }
}

function loadSavedGameId() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch (err) {
    return null;
  }
}

function forgetGame() {
  state.gameId = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (err) {
    // ignore, same reason as above
  }
}

// ---------------------------------------------------------------------------
// Screens
// ---------------------------------------------------------------------------
function showScreen(name) {
  for (const id of ALL_SECTION_IDS) {
    $(id).hidden = !SCREENS[name].includes(id);
  }
  // Jump to the top when the screen changes (for example when the game ends
  // while the player is scrolled down), but not after every round.
  if (state.screen !== name) {
    window.scrollTo(0, 0);
    state.screen = name;
  }
}

// Draw everything for the latest game state that the server sent.
function renderState(game) {
  if (game.finished) {
    showScreen("end");
    renderEnd(game);
    loadLeaderboard();
  } else {
    showScreen("game");
    renderGame(game);
  }
  renderHistory(game);
  renderCharts(game);
}

function describeRound(round) {
  if (round.action === "buy") {
    return `Round ${round.round}: a trader bought ${TRADE_SIZE} from you at ${formatMoney(round.price)}.`;
  }
  if (round.action === "sell") {
    return `Round ${round.round}: a trader sold ${TRADE_SIZE} to you at ${formatMoney(round.price)}.`;
  }
  return `Round ${round.round}: no trader traded.`;
}

function renderGame(game) {
  // current_round counts finished rounds, so the round being played is one more.
  $("round-heading").textContent = `Round ${game.current_round + 1} of ${game.total_rounds}`;
  $("cash-value").textContent = formatMoney(game.cash);
  $("inventory-value").textContent = `${game.inventory} (limit ±${INVENTORY_CAP})`;
  $("pnl-value").textContent = formatPnl(game.mark_to_market_pnl);

  // The last round comes from the history (not from a separate variable),
  // so the text is still right after a page refresh.
  const history = game.rounds_history;
  $("outcome-text").textContent = history.length === 0
    ? "Post your first quote to start."
    : describeRound(history[history.length - 1]);

  hideEndConfirm();
}

function renderEnd(game) {
  const result = game.result;
  $("true-value").textContent = formatMoney(game.true_value);
  $("final-pnl").textContent = formatPnl(result.final_pnl);
  $("informed-pnl").textContent = formatPnl(result.informed_pnl);
  $("uninformed-pnl").textContent = formatPnl(result.uninformed_pnl);

  // Same rule as the server: only games played through every round are ranked.
  const playedAllRounds = game.current_round >= game.total_rounds;
  $("ranked-note").textContent = playedAllRounds
    ? "This game is ranked: you played all rounds."
    : `This game is NOT ranked: it ended after ${game.current_round} of ${game.total_rounds} rounds. Only games played through all ${game.total_rounds} rounds appear on the leaderboard.`;
}

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------
function addCell(row, tag, text) {
  const cell = document.createElement(tag);
  cell.textContent = text;
  row.appendChild(cell);
}

function renderHistory(game) {
  const rounds = game.rounds_history;
  const table = $("history-table");
  table.replaceChildren();
  $("history-empty").hidden = rounds.length > 0;
  if (rounds.length === 0) {
    return;
  }

  // The server only sends trader_informed once the game is finished.
  const showTrader = game.finished;
  const titles = ["Round", "Bid", "Ask", "Action", "Price"];
  if (showTrader) {
    titles.push("Trader");
  }

  const headRow = document.createElement("tr");
  for (const title of titles) {
    addCell(headRow, "th", title);
  }
  const head = document.createElement("thead");
  head.appendChild(headRow);

  const body = document.createElement("tbody");
  // Newest round first, so the latest result is visible without scrolling.
  for (const round of [...rounds].reverse()) {
    const row = document.createElement("tr");
    addCell(row, "td", round.round);
    addCell(row, "td", formatMoney(round.bid));
    addCell(row, "td", formatMoney(round.ask));
    addCell(row, "td", round.action);
    addCell(row, "td", formatMoney(round.price));
    if (showTrader) {
      addCell(row, "td", round.trader_informed ? "Informed" : "Uninformed");
      if (round.trader_informed) {
        row.classList.add("informed-row");
      }
    }
    body.appendChild(row);
  }
  table.append(head, body);
}

async function loadLeaderboard() {
  const status = $("leaderboard-status");
  $("leaderboard-table").replaceChildren();
  status.textContent = "Loading leaderboard…";
  try {
    const data = await api("/api/leaderboard");
    renderLeaderboard(data.leaderboard);
  } catch (err) {
    // A leaderboard problem must not hide the player's own results.
    status.textContent = "Leaderboard unavailable: " + err.message;
  }
}

function renderLeaderboard(entries) {
  const table = $("leaderboard-table");
  table.replaceChildren();
  if (entries.length === 0) {
    $("leaderboard-status").textContent = "No ranked games yet.";
    return;
  }
  $("leaderboard-status").textContent = "";

  const headRow = document.createElement("tr");
  for (const title of ["Rank", "Player", "Final PnL"]) {
    addCell(headRow, "th", title);
  }
  const head = document.createElement("thead");
  head.appendChild(headRow);

  const body = document.createElement("tbody");
  entries.forEach((entry, index) => {
    const row = document.createElement("tr");
    addCell(row, "td", index + 1);
    addCell(row, "td", entry.player_name);   // textContent, so names cannot inject HTML
    addCell(row, "td", formatPnl(entry.final_score));
    body.appendChild(row);
  });
  table.append(head, body);
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------
// Replay the history to get the numbers for the charts. The server only sends
// the current cash and inventory, but the charts need them after every round.
// Mark-to-market uses the same definition as the backend: the average of all
// trade prices so far, or DEFAULT_MARK_PRICE if there has been no trade.
function buildSeries(history) {
  const series = { labels: [], bids: [], asks: [], buys: [], sells: [], pnl: [], inventory: [] };
  let cash = 0;
  let inventory = 0;
  let tradePriceTotal = 0;
  let tradeCount = 0;

  for (const round of history) {
    if (round.action === "buy") {          // a trader bought from us: we sold
      cash += round.price * TRADE_SIZE;
      inventory -= TRADE_SIZE;
    } else if (round.action === "sell") {  // a trader sold to us: we bought
      cash -= round.price * TRADE_SIZE;
      inventory += TRADE_SIZE;
    }
    if (round.price !== null) {
      tradePriceTotal += round.price;
      tradeCount += 1;
    }
    const markPrice = tradeCount > 0 ? tradePriceTotal / tradeCount : DEFAULT_MARK_PRICE;

    series.labels.push(round.round);
    series.bids.push(round.bid);
    series.asks.push(round.ask);
    // null leaves a gap, so a marker only appears in rounds with that kind of trade.
    series.buys.push(round.action === "buy" ? round.price : null);
    series.sells.push(round.action === "sell" ? round.price : null);
    series.pnl.push(round2(cash + inventory * markPrice));
    series.inventory.push(inventory);
  }
  return series;
}

// Options shared by both charts.
function baseOptions(yTitle) {
  return {
    responsive: true,
    maintainAspectRatio: false,   // the CSS height of .chart-box decides the height
    animation: false,             // the charts are redrawn after every round
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { position: "bottom", labels: { usePointStyle: true } } },
    scales: {
      x: { title: { display: true, text: "Round" } },
      y: { title: { display: true, text: yTitle } },
    },
  };
}

function quotesChartConfig(series, game) {
  const datasets = [
    {
      label: "Your bid",
      data: series.bids,
      borderColor: cssColor("--color-bid"),
      backgroundColor: cssColor("--color-bid"),
      pointRadius: 3,
      tension: 0,
    },
    {
      label: "Your ask",
      data: series.asks,
      borderColor: cssColor("--color-ask"),
      backgroundColor: cssColor("--color-ask"),
      pointRadius: 3,
      tension: 0,
    },
    {
      // A trader bought from us, so the trade price is our ask.
      label: "Trader bought from you",
      data: series.buys,
      showLine: false,
      pointStyle: "triangle",
      pointRadius: 8,
      borderColor: cssColor("--color-buy"),
      backgroundColor: cssColor("--color-buy"),
    },
    {
      // A trader sold to us, so the trade price is our bid.
      label: "Trader sold to you",
      data: series.sells,
      showLine: false,
      pointStyle: "rectRot",
      pointRadius: 8,
      borderColor: cssColor("--color-sell"),
      backgroundColor: cssColor("--color-sell"),
    },
  ];

  // V is only known (and only sent by the server) once the game is over.
  if (game.finished) {
    datasets.push({
      label: "True value V",
      data: series.labels.map(() => game.true_value),
      borderColor: cssColor("--color-value"),
      backgroundColor: cssColor("--color-value"),
      borderDash: [6, 4],
      pointRadius: 0,
    });
  }
  return { type: "line", data: { labels: series.labels, datasets }, options: baseOptions("Price") };
}

function pnlChartConfig(series) {
  const options = baseOptions("PnL (mark-to-market)");
  // Inventory gets its own axis on the right because its scale is very
  // different from PnL. The axis runs from -cap to +cap so you can see how
  // close you are to the limit.
  options.scales.y2 = {
    position: "right",
    min: -INVENTORY_CAP,
    max: INVENTORY_CAP,
    title: { display: true, text: "Inventory" },
    grid: { drawOnChartArea: false },   // no second set of grid lines on top of the first
  };

  const datasets = [
    {
      label: "Mark-to-market PnL",
      data: series.pnl,
      yAxisID: "y",
      borderColor: cssColor("--color-pnl"),
      backgroundColor: cssColor("--color-pnl"),
      pointRadius: 3,
      tension: 0,
    },
    {
      label: "Inventory",
      data: series.inventory,
      yAxisID: "y2",
      stepped: true,   // inventory jumps in whole units, so draw steps
      borderColor: cssColor("--color-inventory"),
      backgroundColor: cssColor("--color-inventory"),
      pointRadius: 3,
    },
  ];
  return { type: "line", data: { labels: series.labels, datasets }, options };
}

// Destroy the old chart on this canvas first; Chart.js refuses to draw two
// charts on one canvas.
function drawChart(key, canvasId, config) {
  if (state.charts[key]) {
    state.charts[key].destroy();
  }
  state.charts[key] = new Chart($(canvasId), config);
}

function renderCharts(game) {
  if (typeof Chart === "undefined") {
    // The Chart.js script did not load (for example no internet).
    // The game works without charts, so just hide that section.
    $("charts-section").hidden = true;
    return;
  }
  Chart.defaults.color = cssColor("--color-text");
  Chart.defaults.borderColor = cssColor("--color-border");
  Chart.defaults.font.family = cssColor("--font-body");

  const series = buildSeries(game.rounds_history);
  drawChart("quotes", "quotes-chart", quotesChartConfig(series, game));
  drawChart("pnl", "pnl-chart", pnlChartConfig(series));
}

// ---------------------------------------------------------------------------
// Player actions
// ---------------------------------------------------------------------------
async function startGame(event) {
  event.preventDefault();   // stop the browser from reloading the page on submit
  if (state.busy) return;
  clearMessage();

  setBusy(true);
  try {
    const name = $("name-input").value.trim();
    const data = await api("/api/games", "POST", { player_name: name });
    saveGameId(data.game_id);
    renderState(data.state);
  } catch (err) {
    showMessage(err.message);
  } finally {
    setBusy(false);
  }
}

// Quick checks so obvious typos do not cost a round trip. The server checks
// everything again (range, rounding, bid < ask), and its messages are shown.
function findQuoteProblem(bidText, askText) {
  if (bidText === "" || askText === "") {
    return "Enter both a bid and an ask.";
  }
  const bid = Number(bidText);
  const ask = Number(askText);
  if (!Number.isFinite(bid) || !Number.isFinite(ask)) {
    return "Bid and ask must be numbers.";
  }
  if (bid >= ask) {
    return "Your bid must be lower than your ask.";
  }
  return null;
}

async function submitQuote(event) {
  event.preventDefault();
  if (state.busy) return;
  clearMessage();

  const bidText = $("bid-input").value.trim();
  const askText = $("ask-input").value.trim();
  const problem = findQuoteProblem(bidText, askText);
  if (problem) {
    showMessage(problem);
    return;
  }

  setBusy(true);
  try {
    const data = await api(`/api/games/${state.gameId}/quote`, "POST", {
      bid: Number(bidText),
      ask: Number(askText),
    });
    renderState(data.state);
  } catch (err) {
    await handleError(err);
  } finally {
    setBusy(false);
  }
}

// "End game early" only opens a confirmation box. The game ends when the
// player clicks "Yes, end the game".
function showEndConfirm() {
  $("end-confirm").hidden = false;
  $("end-early-button").hidden = true;
}

function hideEndConfirm() {
  $("end-confirm").hidden = true;
  $("end-early-button").hidden = false;
}

async function finishEarly() {
  if (state.busy) return;
  clearMessage();

  setBusy(true);
  try {
    // The name was already stored when the game started, so we send no body.
    const data = await api(`/api/games/${state.gameId}/finish`, "POST");
    renderState(data.state);
  } catch (err) {
    await handleError(err);
  } finally {
    setBusy(false);
  }
}

// Ask the server for the current state of the game and draw it.
async function loadGame() {
  const data = await api(`/api/games/${state.gameId}`);
  renderState(data.state);
}

function playAgain() {
  forgetGame();
  clearMessage();
  $("start-form").reset();
  $("quote-form").reset();
  showScreen("start");
}

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------
async function init() {
  $("start-form").addEventListener("submit", startGame);
  $("quote-form").addEventListener("submit", submitQuote);
  $("end-early-button").addEventListener("click", showEndConfirm);
  $("cancel-end-button").addEventListener("click", hideEndConfirm);
  $("confirm-end-button").addEventListener("click", finishEarly);
  $("play-again-button").addEventListener("click", playAgain);

  // Resume the saved game after a refresh, if there is one.
  const savedId = loadSavedGameId();
  if (savedId === null) {
    showScreen("start");
    return;
  }
  try {
    const data = await api(`/api/games/${savedId}`);
    state.gameId = savedId;
    renderState(data.state);
  } catch (err) {
    if (err.status === 404) {
      forgetGame();
      showMessage("Your saved game no longer exists. Start a new one.");
    } else {
      // For example the server is down: keep the saved id, so a later refresh can still resume.
      showMessage(err.message);
    }
    showScreen("start");
  }
}

init();