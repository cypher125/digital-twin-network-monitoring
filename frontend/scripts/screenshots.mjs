// Smoke test and screenshots of every dashboard page (evidence for Chapter 4).
//
//   DT_USER=senior1 DT_PASSWORD=... node scripts/screenshots.mjs [--url http://localhost:3000]
//
// Uses the Microsoft Edge already installed on Windows (no browser download).
// Fails if a page logs a console error, throws, or scrolls sideways on a phone.

import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
};
const BASE = option("--url", process.env.DT_URL ?? "http://localhost:3000");
const OUT = path.resolve(option("--out", "../var/screenshots"));
const USER = process.env.DT_USER;
const PASSWORD = process.env.DT_PASSWORD;
if (!USER || !PASSWORD) {
  console.error("Set DT_USER and DT_PASSWORD.");
  process.exit(2);
}

const problems = [];

async function settle(page) {
  // the dashboard polls every second, so "network idle" never comes: wait for loaders to go
  await page.waitForLoadState("load");
  await page
    .waitForFunction(() => !document.querySelector('[role="status"]'), null, { timeout: 60_000 })
    .catch(() => problems.push(`${page.url()}: still loading after 60 s`));
  await page
    .waitForFunction(() => [...document.querySelectorAll("[data-map-painted]")].every((m) => m.dataset.mapPainted === "true"), null, { timeout: 60_000 })
    .catch(() => problems.push(`${page.url()}: the map did not draw within 60 s`));
  await page.waitForTimeout(1500);
}

async function shoot(page, name, theme) {
  const file = path.join(OUT, theme, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log(`  ${theme}/${name}.png`);
}

const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  for (const theme of ["light", "dark"]) {
    await mkdir(path.join(OUT, theme), { recursive: true });
    const context = await browser.newContext({
      viewport: { width: 1366, height: 768 },
      colorScheme: theme,
      deviceScaleFactor: 1,
      ignoreHTTPSErrors: BASE.startsWith("https://"), // Caddy's local certificate may not be trusted here
    });
    const page = await context.newPage();
    // the development server compiles each page on its first visit, which is slow on a small laptop
    page.setDefaultNavigationTimeout(240_000);
    page.setDefaultTimeout(240_000);
    page.on("console", (message) => {
      if (message.type() === "error") problems.push(`${theme} ${page.url()}: console: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`${theme} ${page.url()}: ${error.message}`));

    await page.goto(`${BASE}/login`);
    await settle(page);
    await shoot(page, "01-login", theme);
    await page.fill("#username", USER);
    await page.fill("#password", PASSWORD);
    await Promise.all([page.waitForURL((url) => url.pathname === "/", { timeout: 120_000 }), page.click('button[type="submit"]')]);

    const topology = await (await page.request.get(`${BASE}/api/v1/topology`)).json();
    const busiest = [...topology.links].sort((a, b) => (b.utilisation_pct ?? 0) - (a.utilisation_pct ?? 0))[0];
    const device = topology.devices.find((d) => d.role === "distribution") ?? topology.devices[0];
    const results = await (await page.request.get(`${BASE}/api/v1/results?limit=1&include=recommendations`)).json();
    const result = results.results?.[0];

    const pages = [
      ["02-overview", "/"],
      ["03-link", `/link?id=${busiest.link_id}`],
      ["04-device", `/device?id=${device.device_id}`],
      ["05-alerts", "/alerts"],
      ["06-simulation", "/simulation"],
      ...(result ? [["07-result", `/result?id=${result.result_id}`]] : []),
      ["08-trends", "/trends"],
      ["09-system", "/system"],
    ];
    for (const [name, url] of pages) {
      await page.goto(`${BASE}${url}`);
      await settle(page);
      await shoot(page, name, theme);
    }

    if (theme === "light") {
      // a phone: no sideways scrolling
      await page.setViewportSize({ width: 390, height: 844 });
      for (const [name, url] of [["10-phone-overview", "/"], ["11-phone-simulation", "/simulation"]]) {
        await page.goto(`${BASE}${url}`);
        await settle(page);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        if (overflow > 0) problems.push(`phone ${url}: page is ${overflow}px wider than the screen`);
        await shoot(page, name, theme);
      }
    }
    await context.close();
  }
} finally {
  await browser.close();
}

if (problems.length) {
  console.error(`\n${problems.length} problem(s):`);
  for (const problem of problems) console.error(`- ${problem}`);
  process.exit(1);
}
console.log("\nNo console errors, page errors or sideways scrolling.");
