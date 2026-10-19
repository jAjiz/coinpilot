// Fails the build when the platform's CSP (script-src 'self') or the install
// requirements would be broken. Run after `vite build`.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const dist = path.resolve(import.meta.dirname, "..", "dist");
const problems = [];

const html = readFileSync(path.join(dist, "index.html"), "utf8");
const inline = [...html.matchAll(/<script\b([^>]*)>/gi)].filter(
  ([, attributes]) => !/\bsrc\s*=/i.test(attributes),
);
if (inline.length > 0)
  problems.push("dist/index.html has an inline <script> (no src=)");

const manifestPath = path.join(dist, "manifest.webmanifest");
if (!existsSync(manifestPath)) {
  problems.push("dist/manifest.webmanifest is missing");
} else {
  const { icons = [] } = JSON.parse(readFileSync(manifestPath, "utf8"));
  for (const size of ["192x192", "512x512"]) {
    if (!icons.some((icon) => String(icon.sizes).split(/\s+/).includes(size))) {
      problems.push(`dist/manifest.webmanifest has no ${size} icon`);
    }
  }
}

const swPath = path.join(dist, "sw.js");
if (!existsSync(swPath)) {
  problems.push("dist/sw.js is missing");
} else if (!/denylist:\s*\[[^\]]*api/.test(readFileSync(swPath, "utf8"))) {
  problems.push("dist/sw.js does not deny /api navigations the shell fallback");
}

if (problems.length > 0) {
  for (const problem of problems) console.error(`check:build: ${problem}`);
  process.exit(1);
}
console.log("check:build: ok");
