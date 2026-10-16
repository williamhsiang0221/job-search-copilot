// Screenshots and a short GIF of the demo, for the README.
//
//   backend/demo/run_demo.sh            # in one terminal
//   cd frontend && npm run screenshots  # in another
//
// Only ever photographs the demo: before taking a picture it checks that the
// server's resume layout is the fictional example profile's, and refuses
// otherwise — so the real app's data can never end up in an image.
import { mkdirSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const MEDIA = join(ROOT, "media");
const FRAMES = join(MEDIA, "frames");
const DEMO_URL = process.env.DEMO_URL ?? "http://localhost:5174";

const layout = await fetch(`${DEMO_URL}/api/resume-layout`).then((r) => r.json()).catch(() => null);
if (!layout?.slots?.some((s) => s.slot === "carewell")) {
  console.error(`${DEMO_URL} is not serving the demo (example profile). Start backend/demo/run_demo.sh first.`);
  process.exit(1);
}

rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });

const browser = await chromium.launch();
const errors = [];
const open = async (scale) => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: scale });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(DEMO_URL, { waitUntil: "networkidle" });
  return page;
};
const nav = async (page, parent, child) => {
  await page.getByRole("button", { name: new RegExp(`^${parent}$`) }).first().click();
  await page.getByRole("button", { name: new RegExp(`^${child}$`) }).first().click();
  await page.waitForTimeout(1200);
};

// Each scene: where to go, what to click, and what to call the picture.
const scenes = [
  ["normalized", async (p) => { await nav(p, "Job descriptions", "Normalized"); await p.getByText("Orbitly").first().click(); }],
  ["evaluations", async (p) => { await nav(p, "Evaluations", "History"); await p.getByText("Orbitly").first().click(); }],
  ["assembler", async (p) => { await nav(p, "Resume Builder", "Assembler"); await p.locator("tbody tr").first().click(); }],
  ["bullet-bank", async (p) => { await nav(p, "Resume Builder", "Bullet Bank"); }],
  ["applications", async (p) => { await nav(p, "Applications", "All Applications"); await p.getByText("Northwind Pay").first().click(); }],
  ["dashboard", async (p) => { await nav(p, "Applications", "Dashboard"); }],
];

// Crisp 2x stills for the README, and 1x frames for the GIF.
for (const [scale, out] of [[2, MEDIA], [1, FRAMES]]) {
  const page = await open(scale);
  for (const [i, [name, go]] of scenes.entries()) {
    await go(page);
    await page.waitForTimeout(900);
    const file = out === MEDIA ? `${name}.png` : `${String(i).padStart(2, "0")}-${name}.png`;
    await page.screenshot({ path: join(out, file) });
  }
  await page.close();
}
await browser.close();

if (errors.length) {
  console.error("Page errors while capturing:", errors);
  process.exit(1);
}

const python = join(ROOT, "backend", ".venv", "bin", "python");
const gif = spawnSync(python, [join(ROOT, "backend", "demo", "make_gif.py"), FRAMES, join(MEDIA, "demo.gif")], { stdio: "inherit" });
rmSync(FRAMES, { recursive: true, force: true });
process.exit(gif.status ?? 1);
