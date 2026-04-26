import * as readline from "readline";
import TradingView from "@mathieuc/tradingview";

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false,
});

function send(result) {
  process.stdout.write(JSON.stringify(result) + "\n");
}

function sendError(code, message) {
  send({ error: true, code, message });
}

// ── get_chart ────────────────────────────────────────────────
async function getChart(params) {
  const { symbol, timeframe, range, to: toTs } = params;

  const client = new TradingView.Client();

  return new Promise((resolve) => {
    const chart = new client.Session.Chart();

    chart.onError((...err) => {
      client.end();
      resolve({ error: true, message: String(err) });
    });

    chart.onSymbolLoaded(() => {
      chart.onUpdate(() => {
        if (!chart.periods || chart.periods.length === 0) return;
        const periods = chart.periods.map((p) => ({
          time: p.time,
          open: p.open ?? 0,
          high: p.max ?? p.high ?? 0,
          low: p.min ?? p.low ?? 0,
          close: p.close ?? 0,
          volume: p.volume ?? 0,
        }));
        client.end();
        resolve({
          symbol: chart.infos.symbol || symbol,
          description: chart.infos.description,
          currency: chart.infos.currency_id,
          timeframe,
          periods,
        });
      });
    });

    const opts = { timeframe };
    if (range != null) opts.range = range;
    if (toTs != null) opts.to = toTs;

    chart.setMarket(symbol, opts);
  });
}

// ── get_indicator ───────────────────────────────────────────
async function getIndicator(params) {
  const { symbol, timeframe, indicator, range } = params;

  const client = new TradingView.Client();

  return new Promise((resolve) => {
    const chart = new client.Session.Chart();

    chart.onError((...err) => {
      client.end();
      resolve({ error: true, message: String(err) });
    });

    chart.setMarket(symbol, { timeframe });
    chart.onSymbolLoaded(async () => {
      try {
        const ind = await TradingView.getIndicator(indicator);
        const study = new chart.Study(ind);
        study.onUpdate(() => {
          const periods = study.periods.map((p) => ({ time: p.time, value: p.$value }));
          const pricePeriods = (chart.periods || []).map((p) => ({
            time: p.time,
            open: p.open ?? 0,
            high: p.max ?? 0,
            low: p.min ?? 0,
            close: p.close ?? 0,
            volume: p.volume ?? 0,
          }));
          client.end();
          resolve({
            symbol: chart.infos.symbol || symbol,
            description: chart.infos.description,
            indicator: ind.description,
            timeframe,
            pricePeriods,
            indicatorPeriods: periods,
          });
        });
      } catch (e) {
        client.end();
        resolve({ error: true, message: String(e) });
      }
    });
  });
}

// ── get_technical ────────────────────────────────────────────
async function getTechnical(params) {
  const { symbol, timeframe } = params;

  return new Promise((resolve) => {
    TradingView.getTA(symbol, timeframe || "1D")
      .then((ta) => resolve(ta))
      .catch((e) => resolve({ error: true, message: String(e) }));
  });
}

// ── search_symbol ───────────────────────────────────────────
async function searchSymbol(params) {
  const { query, type } = params;
  try {
    const results = await TradingView.searchMarketV3(query);
    const filtered = (results || []).filter((r) => {
      if (!type) return true;
      if (type === "crypto" && r.exchange === "crypto") return true;
      if (type === "stock" && r.exchange !== "crypto") return true;
      return false;
    });
    return { results: filtered.slice(0, 20) };
  } catch (e) {
    return { error: true, message: String(e) };
  }
}

// ── Command router ───────────────────────────────────────────
const COMMANDS = {
  get_chart: getChart,
  get_indicator: getIndicator,
  get_technical: getTechnical,
  search_symbol: searchSymbol,
};

let pendingOps = 0;
let stdinClosed = false;

function checkExit() {
  if (stdinClosed && pendingOps === 0) {
    process.exit(0);
  }
}

rl.on("line", async (line) => {
  let request;
  try {
    request = JSON.parse(line.trim());
  } catch {
    sendError("PARSE_ERROR", "Invalid JSON input");
    return;
  }

  const { id, command, ...params } = request;

  if (!command || !COMMANDS[command]) {
    send({
      id,
      error: true,
      code: "UNKNOWN_COMMAND",
      message: `Unknown command: ${command}. Available: ${Object.keys(COMMANDS).join(", ")}`,
    });
    return;
  }

  pendingOps++;
  try {
    const result = await COMMANDS[command](params);
    send({ id, ...result });
  } catch (e) {
    send({ id, error: true, message: String(e) });
  } finally {
    pendingOps--;
    checkExit();
  }
});

rl.on("close", () => {
  stdinClosed = true;
  checkExit();
});

process.stderr.write(JSON.stringify({ ready: true }) + "\n");
