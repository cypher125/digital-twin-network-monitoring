// E5 Responsiveness (NFR1): how long after the twin receives a cycle's readings the
// overview shows it. Plan section 11: timed from received_at to the screen, with the full
// stack running, at real time and at demo speed; target: maximum within 5 s.
//
//   set DT_SENIOR=senior1:password
//   node scripts/e5_responsiveness.mjs --url https://localhost --samples 30 --label speed10
//
// For each new cycle it records: received_at (the engine got the readings, server clock),
// when the API first reports the stored cycle, and when the overview page shows its time.
// The browser and the server run on the same laptop, so the clocks are the same clock.
// Writes backend/evaluation/results/E5/<label>.samples.json; evaluation/e5_report.py makes
// the summary and the chart.

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
};
const BASE = option("--url", "https://localhost");
const SAMPLES = Number(option("--samples", "30"));
const LABEL = option("--label", "run");
const OUT = path.resolve("../backend/evaluation/results/E5");
const [USER, PASSWORD] = (() => {
  const value = process.env.DT_SENIOR ?? "";
  const split = value.indexOf(":");
  if (split < 1) {
    console.error("Set DT_SENIOR=username:password");
    process.exit(2);
  }
  return [value.slice(0, split), value.slice(split + 1)];
})();

// exactly as the dashboard formats times (lib/format.ts fmtDateTime)
const wat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Africa/Lagos",
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({ viewport: { width: 1366, height: 768 }, ignoreHTTPSErrors: BASE.startsWith("https://") });
const page = await context.newPage();
page.setDefaultTimeout(240_000);
const live = async () => {
  const response = await page.request.get(`${BASE}/api/v1/live`, { headers: { "X-Poll": "1" } });
  return response.ok() ? response.json() : null;
};

const samples = [];
let speed = null;
try {
  await page.goto(`${BASE}/login`);
  await page.fill("#username", USER);
  await page.fill("#password", PASSWORD);
  await Promise.all([page.waitForURL((url) => url.pathname === "/"), page.click('button[type="submit"]')]);
  await page.getByRole("heading", { name: "Network overview" }).waitFor();
  let last = (await live())?.last_cycle ?? null;
  while (samples.length < SAMPLES) {
    const waitingFrom = Date.now();
    let now = null;
    for (;;) {
      now = await live();
      if (now && now.last_cycle && now.last_cycle !== last) break;
      if (Date.now() - waitingFrom > 600_000) throw new Error("no new cycle within 10 minutes");
      await sleep(100);
    }
    const apiSeen = Date.now();
    speed = now.speed;
    const shown = wat.format(new Date(now.last_cycle));
    await page.waitForFunction((text) => document.body.innerText.includes(text), shown, { timeout: 60_000, polling: 50 });
    const onScreen = Date.now();
    const received = now.received_at ? Date.parse(now.received_at) : null;
    const sample = {
      cycle: now.last_cycle,
      received_at: now.received_at,
      received_to_screen_s: received ? (onScreen - received) / 1000 : null,
      received_to_api_s: received ? (apiSeen - received) / 1000 : null,
      api_to_screen_s: (onScreen - apiSeen) / 1000,
      speed: now.speed,
      mode: now.mode,
    };
    samples.push(sample);
    console.log(`${samples.length}/${SAMPLES} cycle ${sample.cycle}: ${sample.received_to_screen_s?.toFixed(2)} s from received to screen`);
    last = now.last_cycle;
  }
} finally {
  await browser.close();
}

await mkdir(OUT, { recursive: true });
await writeFile(
  path.join(OUT, `${LABEL}.samples.json`),
  JSON.stringify({ label: LABEL, url: BASE, speed, when: new Date().toISOString(), samples }, null, 2),
);
console.log(`written ${samples.length} samples to ${path.join(OUT, `${LABEL}.samples.json`)}`);
