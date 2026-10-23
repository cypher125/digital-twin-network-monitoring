// E5 Responsiveness (NFR1): how long after the twin receives a cycle's readings the
// overview shows it. Plan section 11: timed from received_at to the screen, with the full
// stack running, at real time and at demo speed; target: maximum within 5 s.
//
//   set DT_SENIOR=senior1:password
//   node scripts/e5_responsiveness.mjs --url https://localhost --samples 30 --label speed10 [--max-minutes 400]
//
// It keeps going through service restarts (for example during the E6 soak test): a failed request
// counts as "no new data yet", and a cycle the page never shows within 60 s is recorded as timed
// out (a breach, unless e5_report.py is told to leave out a fault window). Samples are saved
// after each one, so an interrupted run keeps what it measured.
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
const MAX_MINUTES = Number(option("--max-minutes", "0"));
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
  try {
    const response = await page.request.get(`${BASE}/api/v1/live`, { headers: { "X-Poll": "1" }, timeout: 10_000 });
    return response.ok() ? await response.json() : null;
  } catch {
    return null; // Caddy or the API is restarting
  }
};
const signIn = async () => {
  await page.goto(`${BASE}/login`);
  await page.fill("#username", USER);
  await page.fill("#password", PASSWORD);
  await Promise.all([page.waitForURL((url) => url.pathname === "/"), page.click('button[type="submit"]')]);
  await page.getByRole("heading", { name: "Network overview" }).waitFor();
};
const save = async () => {
  await mkdir(OUT, { recursive: true });
  await writeFile(
    path.join(OUT, `${LABEL}.samples.json`),
    JSON.stringify({ label: LABEL, url: BASE, speed, when: new Date().toISOString(), samples }, null, 2),
  );
};
const began = Date.now();

const samples = [];
let speed = null;
try {
  await signIn();
  let last = (await live())?.last_cycle ?? null;
  while (samples.length < SAMPLES && !(MAX_MINUTES && Date.now() - began > MAX_MINUTES * 60_000)) {
    const waitingFrom = Date.now();
    let now = null;
    for (;;) {
      now = await live();
      if (now && now.last_cycle && now.last_cycle !== last) break;
      if (Date.now() - waitingFrom > 1_800_000) throw new Error("no new cycle within 30 minutes");
      await sleep(100);
    }
    const apiSeen = Date.now();
    speed = now.speed;
    const shown = wat.format(new Date(now.last_cycle));
    const received = now.received_at ? Date.parse(now.received_at) : null;
    let sample;
    try {
      await page.waitForFunction((text) => document.body.innerText.includes(text), shown, { timeout: 60_000, polling: 50 });
      const onScreen = Date.now();
      sample = {
        cycle: now.last_cycle,
        received_at: now.received_at,
        received_to_screen_s: received ? (onScreen - received) / 1000 : null,
        received_to_api_s: received ? (apiSeen - received) / 1000 : null,
        api_to_screen_s: (onScreen - apiSeen) / 1000,
        speed: now.speed,
        mode: now.mode,
      };
      console.log(`${samples.length + 1}/${SAMPLES} cycle ${sample.cycle}: ${sample.received_to_screen_s?.toFixed(2)} s from received to screen`);
    } catch {
      sample = { cycle: now.last_cycle, received_at: now.received_at, received_to_screen_s: null, timed_out: true,
                 received_to_api_s: received ? (apiSeen - received) / 1000 : null, speed: now.speed, mode: now.mode };
      console.log(`${samples.length + 1}/${SAMPLES} cycle ${sample.cycle}: not on screen within 60 s; reloading`);
      try {
        await page.goto(`${BASE}/`);
        if (new URL(page.url()).pathname.startsWith("/login")) await signIn();
      } catch {
        // the system is still restarting; the next cycle tries again
      }
    }
    samples.push(sample);
    await save();
    last = now.last_cycle;
  }
} finally {
  await browser.close();
  await save();
}
console.log(`written ${samples.length} samples to ${path.join(OUT, `${LABEL}.samples.json`)}`);
