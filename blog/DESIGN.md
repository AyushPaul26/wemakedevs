# Relay build journal

A standalone English content site for Graph Hacks judges and curious developers. Its job is to explain the company-knowledge problem, the implemented graph and approval workflows, and concrete engineering lessons, with an inviting visual identity. It does not change Relay's runtime.

## Visual direction

The connected notebook: spacious editorial reading paired with a small, explorable dependency map. The signature is the map's evidence path, with a documented backup assumption changing the exposed-dependent count from 3 to 1. The illustration is explicitly local and hypothetical. Avoid generic metrics, stock testimonials, decorative dashboard grids, dark neon, or invented personal anecdotes.

Palette values live once in `src/styles.css` under `:root`: ink #252238, muted #686578, paper #faf9fd, white #ffffff, violet #6246ce, lilac #ede8fc, mint #e3f2eb, green #24674f, clay #b34735. Existing Relay identity informs this separate editorial treatment.

Display: locally hosted Sora, 600. Body: locally hosted DM Sans, 400/500/600. Monospace: system monospace. Main body 18–19px, 1.8 line-height, reading measure about 65 characters. Hero 76px maximum, restrained tracking. A narrow sticky table of contents supports a single long article; it becomes horizontal on mobile.

Layout: 1200px shell, two-column hero, 208px article navigation plus 690px reading column; occasional wide figures. Border radii 14–24px on illustrations, pill links only where helpful. Real screenshots supplement, rather than replace, explanations. Arrows in the graph point from dependents to prerequisites.

## Behavior and accessibility

Document and core links work without JavaScript. Native buttons control dependency scenarios and optional video loading. Video is click-to-load, with a direct YouTube fallback. Diagram controls are labeled as an illustrative demo and never imply live API execution. Status is announced politely. Copy-link has a selectable URL fallback if Clipboard API fails. Keyboard focus is visible, reduced motion is respected, text contrast targets WCAG AA, and no document-level horizontal overflow is allowed at 360px. All content and assets are local except user-initiated YouTube playback and explicit external navigation.

## Content boundaries

Ground facts in the repository README, submission guide, verification record, graph_store.py, and workflow_store.py. Do not invent customers, productivity gains, independent LLM agents, external payment/ticket actions, or participant expertise. AI assistance is disclosed in one ordinary line. Limits remain accessible in the article and linked verification record. Demo account passwords are never published here.

## Delivery

Zero-dependency static build, isolated in `blog/`, deployed as its own Vercel project with root directory `blog`. Existing Render deployment and backend remain unchanged. Verify build, document links, interactive transitions, no-JS reading, keyboard, reduced motion, axe accessibility, and desktop/mobile screenshots before publication.
