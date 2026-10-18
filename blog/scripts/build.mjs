import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));
const out = path.join(root, "dist");
await rm(out, { recursive: true, force: true });
await mkdir(path.join(out, "assets"), { recursive: true });
await cp(path.join(root, "public"), out, { recursive: true });
await cp(
  path.join(root, "src/styles.css"),
  path.join(out, "assets/styles.css"),
);
await cp(path.join(root, "src/main.js"), path.join(out, "assets/main.js"));
let html = await readFile(path.join(root, "index.html"), "utf8");
const productionDomain = process.env.VERCEL_PROJECT_PRODUCTION_URL;
if (productionDomain && /^[a-z0-9.-]+$/i.test(productionDomain)) {
  const origin = `https://${productionDomain}`;
  html = html.replace(
    'content="/assets/social-cover.png"',
    `content="${origin}/assets/social-cover.png"`,
  );
  html = html.replace(
    "</head>",
    `<link rel="canonical" href="${origin}/" />\n<meta property="og:url" content="${origin}/" />\n</head>`,
  );
}
await writeFile(path.join(out, "index.html"), html);
await writeFile(
  path.join(out, "404.html"),
  `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Page not found · Relay</title><link rel="stylesheet" href="/assets/styles.css"><main class="not-found"><a class="wordmark" href="/">relay.</a><h1>This path ends here.</h1><p>The story is still waiting for you.</p><a class="button button-primary" href="/">Back to the journal <span aria-hidden="true">↗</span></a></main></html>`,
);
console.log(
  "Built Relay journal → blog/dist (static assets only; no credentials or runtime configuration).",
);
