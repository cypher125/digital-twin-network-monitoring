// Use-case walkthrough (plan phase P5 exit; evidence for Chapter 4).
//
//   set DT_SENIOR=senior1:password
//   set DT_JUNIOR=junior1:password
//   node scripts/walkthrough.mjs [--url http://localhost:3000] [--surge]
//
// Works through UC1-UC4 and their extensions in the browser as a Senior and a Junior
// Administrator, and takes a first NFR1 measurement: how long after the twin stores a
// cycle the overview shows it. With --surge it also injects a traffic surge into the
// emulator (the test harness's lab interface) and waits for the predictive alert (UC2).
// Uses the Microsoft Edge that comes with Windows. Writes var/walkthrough/report.json.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
};
const BASE = option("--url", process.env.DT_URL ?? "http://localhost:3000");
const EMULATOR = option("--emulator", "http://127.0.0.1:9161");
const SURGE = args.includes("--surge");
const OUT = path.resolve("../var/walkthrough");
const account = (name) => {
  const value = process.env[name] ?? "";
  const split = value.indexOf(":");
  if (split < 1) {
    console.error(`Set ${name}=username:password`);
    process.exit(2);
  }
  return { username: value.slice(0, split), password: value.slice(split + 1) };
};
const SENIOR = account("DT_SENIOR");
const JUNIOR = account("DT_JUNIOR");

const steps = [];
const problems = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function step(name, body) {
  const began = Date.now();
  try {
    const detail = await body();
    steps.push({ name, ok: true, seconds: (Date.now() - began) / 1000, detail: detail ?? null });
    console.log(`PASS ${name}${detail ? ` - ${typeof detail === "string" ? detail : JSON.stringify(detail)}` : ""}`);
  } catch (error) {
    steps.push({ name, ok: false, seconds: (Date.now() - began) / 1000, error: String(error?.message ?? error).slice(0, 400) });
    console.log(`FAIL ${name} - ${String(error?.message ?? error).split("\n")[0]}`);
  }
}

// formatted exactly as the dashboard shows it (lib/format.ts fmtDateTime)
const wat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Africa/Lagos",
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

async function apiGet(page, route) {
  const response = await page.request.get(`${BASE}/api/v1/${route}`, { headers: { "X-Poll": "1" } });
  if (!response.ok()) throw new Error(`GET ${route}: HTTP ${response.status()}`);
  return response.json();
}

async function csrf(context) {
  const cookie = (await context.cookies()).find((c) => c.name === "csrftoken");
  return cookie?.value ?? "";
}

async function newPage(browser) {
  // over https://localhost, Caddy's local certificate may not be trusted on this machine (caddy trust)
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 }, ignoreHTTPSErrors: BASE.startsWith("https://") });
  const page = await context.newPage();
  page.setDefaultNavigationTimeout(240_000);
  page.setDefaultTimeout(60_000);
  page.on("pageerror", (error) => problems.push(`${page.url()}: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("status of 4")) problems.push(`${page.url()}: console: ${message.text()}`);
  });
  return { context, page };
}

async function signIn(page, user) {
  await page.goto(`${BASE}/login`);
  await page.fill("#username", user.username);
  await page.fill("#password", user.password);
  await Promise.all([page.waitForURL((url) => url.pathname === "/", { timeout: 240_000 }), page.click('button[type="submit"]')]);
  await page.getByRole("heading", { name: "Network overview" }).waitFor();
}

async function shot(page, name) {
  // a network map draws a moment after the page: wait for its first frame so the screenshot shows it
  await page
    .waitForFunction(() => [...document.querySelectorAll("[data-map-painted]")].every((m) => m.dataset.mapPainted === "true"), null, { timeout: 60_000 })
    .catch(() => problems.push(`${page.url()}: the map did not draw within 60 s`));
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const nfr1 = [];

try {
  const { context, page } = await newPage(browser);

  await step("Sign-in refuses a wrong password", async () => {
    await page.goto(`${BASE}/login`);
    await page.fill("#username", SENIOR.username);
    await page.fill("#password", "not-the-password");
    await page.click('button[type="submit"]');
    await page.getByRole("alert").filter({ hasText: /Incorrect username or password|Too many failed attempts/ }).waitFor();
  });

  await step("Senior Administrator signs in", async () => {
    await signIn(page, SENIOR);
    await shot(page, "01-overview");
  });

  // ------------------------------------------------------------------ UC1
  await step("UC1 overview shows the live map and summary", async () => {
    await page.getByText("Devices up").waitFor();
    await page.locator('[aria-label^="Network map"] canvas').first().waitFor();
    await page.getByText("Congestion predicted", { exact: true }).first().waitFor();
    const live = await apiGet(page, "live");
    if (live.engine_state !== "running") throw new Error(`engine is ${live.engine_state}`);
    return `engine running, state version ${live.state_version}`;
  });

  await step("NFR1: the overview shows each new cycle within 5 s of it being stored", async () => {
    let last = (await apiGet(page, "live")).last_cycle;
    while (nfr1.length < 5) {
      const waitedFrom = Date.now();
      let now;
      for (;;) {
        now = await apiGet(page, "live");
        if (now.last_cycle && now.last_cycle !== last) break;
        if (Date.now() - waitedFrom > 180_000) throw new Error("no new cycle within 3 minutes");
        await sleep(100);
      }
      const stored = Date.now();
      const expected = wat.format(new Date(now.last_cycle));
      await page.waitForFunction((text) => document.body.innerText.includes(text), expected, { timeout: 30_000 });
      nfr1.push((Date.now() - stored) / 1000);
      last = now.last_cycle;
    }
    const worst = Math.max(...nfr1);
    if (worst > 5) throw new Error(`slowest update ${worst.toFixed(2)} s`);
    return `seconds: ${nfr1.map((s) => s.toFixed(2)).join(", ")}`;
  });

  let linkId = null;
  await step("UC1 extension: open a link's detail from the links table", async () => {
    const card = page.locator("section", { hasText: "Live network map" });
    await card.getByRole("radio", { name: /Table/ }).click();
    const first = card.locator('a[href^="/link?id="]').first();
    linkId = Number(new URL(await first.getAttribute("href"), BASE).searchParams.get("id"));
    await first.click();
    await page.waitForURL(/\/link\?id=/);
    await page.getByText("Utilisation and forecast").waitFor();
    await page.getByText("Forecast by horizon").waitFor();
    await shot(page, "02-link");
    return `link ${linkId}`;
  });

  await step("UC1 extension: open a device's detail", async () => {
    await page.locator('a[href^="/device?id="]').first().click();
    await page.waitForURL(/\/device\?id=/);
    await page.getByText("CPU utilisation").waitFor();
    await page.getByText("Connected links").waitFor();
    await shot(page, "03-device");
  });

  // ------------------------------------------------------------------ UC2
  if (SURGE) {
    await step("UC2: a surge in the network raises a predictive alert", async () => {
      const token = (await readFile(path.resolve("../var/netemu/lab_token"), "utf-8")).trim();
      // size the surge to the time of day: a tripled video load is nothing at 3 a.m. but saturates the
      // hostel Wi-Fi in the evening, so scale it from the hostel access point's utilisation now
      const topology = await apiGet(page, "topology");
      const hostel = topology.links.find((l) => l.label.includes("AP-HOSTEL-01"));
      const now = Math.max(3, hostel?.utilisation_pct ?? 10);
      const multiplier = Math.round(Math.min(30, Math.max(3, 300 / now)));
      const response = await fetch(`${EMULATOR}/lab/surge`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Lab-Token": token },
        body: JSON.stringify({ zone: "HOSTEL", cls: "video", multiplier, ramp_minutes: 20, hold_minutes: 30 }),
      });
      if (!response.ok) throw new Error(`lab surge: HTTP ${response.status}`);
      const began = Date.now();
      for (;;) {
        const alerts = await apiGet(page, "alerts/active");
        const found = alerts.alerts.find((a) => a.kind === "predicted") ?? alerts.alerts[0];
        if (found) {
          const waited = ((Date.now() - began) / 1000).toFixed(0);
          return `video x${multiplier} (hostel AP at ${now.toFixed(0)}%): ${found.label}: ${found.kind}, ${found.minutes_until ?? "?"} min ahead, ${found.confidence_band} confidence, after ${waited} s`;
        }
        if (Date.now() - began > 480_000) throw new Error(`no alert within 8 minutes (video x${multiplier}, hostel AP at ${now.toFixed(0)}%)`);
        await sleep(2000);
      }
    });
  }

  await step("UC2 alerts page shows alerts (or that none are expected) and the history", async () => {
    await page.goto(`${BASE}/alerts`);
    await page.getByRole("heading", { name: "Predictive congestion alerts" }).waitFor();
    await page.getByText("Alert history").waitFor();
    const active = await apiGet(page, "alerts/active");
    if (active.alerts.length) {
      await page.getByText("Recommended actions").first().waitFor();
    } else if (active.model) {
      await page.getByText(/No link is expected to reach 90%/).waitFor();
    }
    await shot(page, "04-alerts");
    return `${active.alerts.length} active alert(s)`;
  });

  // ------------------------------------------------------------------ UC3
  let resultUrl = null;
  await step("UC3: create and run a link-failure scenario with the guided form", async () => {
    await page.goto(`${BASE}/simulation`);
    await page.getByRole("heading", { name: "Simulation console" }).waitFor();
    await page.getByRole("button", { name: /^Link failure/ }).click();
    const name = `Walkthrough link failure ${new Date().toISOString().slice(11, 19)}`;
    await page.getByLabel("Scenario name").fill(name);
    await page.locator("#field-link_id").selectOption({ index: 1 });
    await Promise.all([page.waitForURL(/\/result\?id=/, { timeout: 120_000 }), page.getByRole("button", { name: /Save and run/ }).click()]);
    resultUrl = page.url();
    await page.getByText("What would happen").waitFor({ timeout: 120_000 });
    await shot(page, "05-result");
    return name;
  });

  await step("UC3 extension: compare the result with the network now", async () => {
    if (!resultUrl) throw new Error("no result to compare");
    await page.getByRole("radio", { name: "The network now" }).click();
    await page.getByText("Utilisation measured now, and after the change").waitFor();
    await page.locator("section", { hasText: "Links that change most" }).getByRole("radio", { name: /Table/ }).click();
    await page.getByRole("columnheader", { name: /Measured now/ }).first().waitFor();
  });

  // ------------------------------------------------------------------ UC4
  await step("UC4: trends, weekly pattern and capacity planning", async () => {
    await page.goto(`${BASE}/trends`);
    await page.getByRole("heading", { name: "Trends and capacity planning" }).waitFor();
    await page.getByText("Weekly pattern", { exact: false }).first().waitFor();
    await page.getByRole("heading", { name: "Capacity planning", exact: true }).waitFor();
    await shot(page, "06-trends");
  });

  await step("System page shows the engine, models and database", async () => {
    await page.goto(`${BASE}/system`);
    await page.getByText("Digital Twin Engine").waitFor();
    await page.getByText("Forecasting models").waitFor();
    const status = await apiGet(page, "system/status");
    await shot(page, "07-system");
    return `last cycle took ${status.engine?.timings?.total_ms ?? "?"} ms in the engine`;
  });

  await step("Senior Administrator signs out", async () => {
    await page.getByRole("button", { name: /senior|Senior/ }).first().click();
    // the account panel is a disclosure of plain buttons (no menu roles); it is hidden until opened
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login/);
    const me = await page.request.get(`${BASE}/api/v1/auth/me`);
    if (me.status() !== 403) throw new Error(`auth/me after sign-out: HTTP ${me.status()}`);
  });
  await context.close();

  // ------------------------------------------------------------------ roles
  const junior = await newPage(browser);
  await step("Junior Administrator can look but not change anything", async () => {
    const page2 = junior.page;
    await signIn(page2, JUNIOR);
    await page2.goto(`${BASE}/simulation`);
    await page2.getByText("Only a Senior Administrator can create or run scenarios.").waitFor();
    if (await page2.getByRole("button", { name: /Save and run/ }).count()) throw new Error("a junior sees Save and run");
    if (linkId) {
      await page2.goto(`${BASE}/link?id=${linkId}`);
      await page2.getByText("Configuration (Topology Store)").waitFor();
      // the card shows at once while its record loads, and a senior's Edit button only once it has
      // loaded: wait for the record, or the check below would pass before Edit could appear
      await page2.getByText("Link ID", { exact: true }).waitFor();
      if (await page2.getByRole("button", { name: "Edit" }).count()) throw new Error("a junior sees Edit");
      const refused = await page2.request.patch(`${BASE}/api/v1/links/${linkId}`, {
        data: { capacity_mbps: 1 },
        headers: { "X-CSRFToken": await csrf(junior.context) },
      });
      if (refused.status() !== 403) throw new Error(`junior PATCH: HTTP ${refused.status()}`);
    }
    await shot(page2, "08-junior-simulation");
  });
  await junior.context.close();
} finally {
  await browser.close();
}

const report = {
  when: new Date().toISOString(),
  url: BASE,
  surge: SURGE,
  passed: steps.filter((s) => s.ok).length,
  failed: steps.filter((s) => !s.ok).length,
  nfr1_seconds: nfr1,
  nfr1_max_seconds: nfr1.length ? Math.max(...nfr1) : null,
  steps,
  problems,
};
await writeFile(path.join(OUT, "report.json"), JSON.stringify(report, null, 2));
console.log(`\n${report.passed} passed, ${report.failed} failed; NFR1 worst ${report.nfr1_max_seconds ?? "-"} s`);
if (problems.length) {
  console.log(`${problems.length} page problem(s):`);
  for (const problem of problems) console.log(`- ${problem}`);
}
process.exit(report.failed || problems.length ? 1 : 0);
