// Render the as-built diagrams (docs/diagrams/*.svg) to PNG for the Word document.
//
//   node scripts/render_diagrams.mjs
//
// Uses the installed Microsoft Edge (as the other scripts do), at twice the drawing size.

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const folder = path.resolve("../docs/diagrams");
const files = (await readdir(folder)).filter((f) => f.endsWith(".svg"));
const browser = await chromium.launch({ channel: "msedge", headless: true });
for (const file of files) {
  const svg = await readFile(path.join(folder, file), "utf-8");
  const width = Number(/width="(\d+)"/.exec(svg)[1]);
  const height = Number(/height="(\d+)"/.exec(svg)[1]);
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1.5 });
  await page.setContent(`<html><body style="margin:0">${svg}</body></html>`);
  await page.locator("svg").screenshot({ path: path.join(folder, file.replace(".svg", ".png")) });
  await page.close();
  console.log("rendered", file);
}
await browser.close();
