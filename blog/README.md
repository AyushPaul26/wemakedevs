# Relay build journal

A standalone, public article about Relay for Graph Hacks. This is a static site, independent of the authenticated Relay application on Render. No database, API credentials, environment variables, or npm dependencies are required for the site.

## Build and preview

From `blog/`, with Node.js 22+:

```sh
npm run check
npm run build
npm run preview
```

Preview uses Python 3. The production output is `dist/`.

## Deploy as a new Vercel project

Import `AyushPaul26/wemakedevs`, branch `work`, and name the new project `relay-build-journal` (or an available alternative). Set **Root Directory** to `blog`, **Framework Preset** to `Other`, **Build Command** to `npm run build`, and **Output Directory** to `dist`. No environment variables are needed. The existing Render app is unaffected.

The `vercel.json` in this folder sets the build/output and security headers. Ensure the resulting production deployment is public so judges can read it without Vercel authentication. Use the actual production URL returned by Vercel; no URL is assumed here.

[Create a new Vercel project from this blog](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FAyushPaul26%2Fwemakedevs%2Ftree%2Fwork%2Fblog&project-name=relay-build-journal&repository-name=relay-build-journal). This uses Vercel's template import flow and creates a separate copy of the blog. To keep it connected to the existing Relay repository instead, use the manual import settings above.

## Content and behavior

- Static article remains readable without JavaScript.
- Dependency toggle is a labeled local illustration, not a live backend operation.
- YouTube player loads only after the reader presses Play; an ordinary YouTube link remains available.
- Core facts are grounded in the repository and verification documentation; limits and AI assistance are disclosed.
- The included product screenshot contains fictional demo data. Fonts use their included SIL Open Font Licenses.

Visual intent, design tokens, and accessibility requirements are recorded in `DESIGN.md`.
