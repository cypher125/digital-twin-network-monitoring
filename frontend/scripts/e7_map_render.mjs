// E7 helper: time how long the network map takes to draw for a given topology size.
//
//   node scripts/e7_map_render.mjs <elements.json> [runs]
//
// Loads Cytoscape.js (the dashboard's map library) into a headless Edge page, builds the map
// from the elements with preset positions, and times creation until the first frame is drawn.
// Prints {"devices": n, "links": m, "runs_ms": [...], "median_ms": x} as JSON.

import { readFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const [file, runsArg] = process.argv.slice(2);
const runs = Number(runsArg ?? "5");
const elements = JSON.parse(await readFile(file, "utf-8"));
const cytoscapePath = path.resolve("node_modules/cytoscape/dist/cytoscape.min.js");

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
await page.setContent('<div id="cy" style="width:1200px;height:700px"></div>');
await page.addScriptTag({ path: cytoscapePath });
const times = [];
for (let i = 0; i < runs; i += 1) {
  const ms = await page.evaluate(
    (els) =>
      new Promise((resolve) => {
        const container = document.getElementById("cy");
        container.innerHTML = "";
        const began = performance.now();
        // eslint-disable-next-line no-undef
        const cy = cytoscape({
          container,
          elements: els,
          layout: { name: "preset", fit: true, padding: 28 },
          style: [
            { selector: "node", style: { width: 22, height: 22, label: "data(label)", "font-size": 15, "text-valign": "bottom" } },
            { selector: "edge", style: { width: "data(width)", "line-color": "#0ca30c", "curve-style": "straight" } },
          ],
        });
        cy.one("render", () => {
          const elapsed = performance.now() - began;
          cy.destroy();
          resolve(elapsed);
        });
      }),
    elements,
  );
  times.push(ms);
}
await browser.close();
times.sort((a, b) => a - b);
const nodes = elements.filter((e) => e.group === "nodes").length;
console.log(JSON.stringify({ devices: nodes, links: elements.length - nodes, runs_ms: times, median_ms: times[Math.floor(times.length / 2)] }));
