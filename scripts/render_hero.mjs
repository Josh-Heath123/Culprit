// Renders the README's hero and the social preview (docs/DELIVERY_PLAN.md
// S2; Phase 40 part 2, decision 3). Run it with `just readme-hero`.
//
// docs/brand/hero.html is the source. This script:
//   1. reads the colour tokens from frontend/src/index.css's :root, so the
//      hero wears the dashboard's tokens and names none of its own;
//   2. reads the figure from scripts/accuracy_readme.py (`--figure`), the
//      function the README's accuracy block is built from, over the fault
//      library's committed results;
//   3. renders, with the Playwright frontend/ already installs and the
//      fontsource fonts beside it: hero-dark.png and hero-light.png at
//      3200x800 (1600x400 at twice the density, shown at half size), and
//      social-preview.png at 1280x640;
//   4. records the figure it drew in docs/brand/hero.json, which
//      scripts/tests/test_accuracy_readme.py holds to the committed results.
//
// No dependency is added: Playwright is resolved from frontend/.

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BRAND = join(ROOT, "docs", "brand");
const require = createRequire(join(ROOT, "frontend", "package.json"));
const { chromium } = require("@playwright/test");

//: The tokens hero.html reads. Every one must be in index.css's :root.
const TOKENS = [
  "surface-0",
  "surface-3",
  "fg",
  "fg-muted",
  "brand",
  "brand-fill",
  "culprit",
  "on-culprit",
  "glow-violet",
  "graticule",
  "graticule-mark",
];

function rootTokens() {
  const css = readFileSync(join(ROOT, "frontend", "src", "index.css"), "utf8");
  const block = css.match(/:root\s*\{([\s\S]*?)\n\}/);
  if (!block) throw new Error("index.css has no :root block");
  const body = block[1].replace(/\/\*[\s\S]*?\*\//g, "");
  const all = Object.fromEntries(
    [...body.matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]),
  );
  const resolve = (name, depth = 0) => {
    const value = all[name];
    if (value === undefined) throw new Error(`index.css declares no --${name}`);
    const ref = value.match(/^var\(--([a-z0-9-]+)\)$/);
    if (ref && depth < 10) return resolve(ref[1], depth + 1);
    return value;
  };
  return Object.fromEntries(TOKENS.map((name) => [name, resolve(name)]));
}

function accuracyFigure() {
  const out = execFileSync(
    "uv",
    ["run", "--project", "api", "python", "scripts/accuracy_readme.py", "--figure"],
    { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
  );
  const figure = JSON.parse(out.trim().split("\n").pop());
  for (const key of ["verified", "decided", "share", "planted"]) {
    if (!(key in figure)) throw new Error(`accuracy_readme.py --figure gave no ${key}`);
  }
  return figure;
}

const OUTPUTS = [
  { file: "hero-dark.png", theme: "dark", variant: "hero", width: 1600, height: 400, scale: 2 },
  { file: "hero-light.png", theme: "light", variant: "hero", width: 1600, height: 400, scale: 2 },
  { file: "social-preview.png", theme: "dark", variant: "social", width: 1280, height: 640, scale: 1 },
];

const tokens = rootTokens();
const figure = accuracyFigure();
const browser = await chromium.launch();
try {
  for (const out of OUTPUTS) {
    const page = await browser.newPage({
      viewport: { width: out.width, height: out.height },
      deviceScaleFactor: out.scale,
    });
    await page.addInitScript((hero) => {
      window.HERO = hero;
    }, { theme: out.theme, variant: out.variant, tokens, figure });
    await page.goto(pathToFileURL(join(BRAND, "hero.html")).href);
    await page.evaluate(() => document.fonts.ready);
    const missing = await page.evaluate(() =>
      ['700 10px "Inter"', '500 10px "JetBrains Mono"'].filter((f) => !document.fonts.check(f)),
    );
    if (missing.length) throw new Error(`fonts not loaded: ${missing.join(", ")}`);
    await page.screenshot({ path: join(BRAND, out.file) });
    await page.close();
    console.log(`wrote docs/brand/${out.file} (${out.width * out.scale}x${out.height * out.scale})`);
  }
} finally {
  await browser.close();
}

const record = {
  why:
    "The figure the hero images were rendered with, from scripts/accuracy_readme.py's figure() " +
    "of cli/testdata/faultlib/results.json. Written by `just readme-hero`; " +
    "scripts/tests/test_accuracy_readme.py fails when it is not what the committed results give.",
  figure,
  images: OUTPUTS.map((o) => o.file),
};
writeFileSync(join(BRAND, "hero.json"), JSON.stringify(record, null, 2) + "\n");
console.log("wrote docs/brand/hero.json", JSON.stringify(figure));
