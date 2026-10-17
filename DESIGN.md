---
version: alpha
name: Relay
description: An evidence-backed company workspace with a dependency map at its center.
colors:
  background: "#f5f6fb"
  surface: "#ffffff"
  sidebar: "#171a2b"
  primary: "#6558d9"
  ink: "#25283d"
  muted: "#666b82"
  border: "#e4e6f0"
  impact: "#bd5446"
  impact-ink: "#a84639"
  success: "#17816f"
  sidebar-muted: "#a9adc4"
typography:
  display:
    fontFamily: "Sora, sans-serif"
  body:
    fontFamily: "DM Sans, sans-serif"
rounded:
  control: "8px"
  card: "14px"
omitted:
  - section: spacing
    reason: "Layout geometry is owned by frontend/src/styles.css; no independent spacing token scale is generated."
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
  modal:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
  status-error:
    textColor: "{colors.impact-ink}"
  graph-impact:
    textColor: "{colors.impact}"
  status-success:
    textColor: "{colors.success}"
  source-button:
    textColor: "{colors.muted}"
  navigation:
    backgroundColor: "{colors.sidebar}"
    textColor: "{colors.sidebar-muted}"
  caption:
    textColor: "{colors.muted}"
  divider:
    backgroundColor: "{colors.border}"
---

# Relay design system

## Overview

Relay feels like a launch coordination room: a quiet working surface around a map of actual dependencies. The audience is a teammate investigating what blocks Meridian's Atlas launch, who owns the next step, and what evidence supports it. Product authority is [the Relay specification](docs/relay-product-spec.md).

This is a product workspace, not a marketing site. The signature is Ripple: the selected service and affected launch form a readable dependency path beside a source-backed investigation. The graph carries the expression; navigation, forms, evidence, and task approval remain familiar and restrained. Avoid decorative dashboards, fictional metrics, unreadable graph tangles, and conversational answers without citations.

The current release is an English sample workspace for a global hackathon audience. No Japan-specific market or language requirement is established. Optimize for a laptop investigation session and preserve every primary operation on a narrow viewport.

**Token ownership is Model B.** `frontend/src/styles.css` owns runtime values. This document mirrors accepted colors, typography, and radii and explains their use; it does not generate CSS. Shared controls consume the stylesheet. Change the runtime owner once, update this mirror in the same change, lint this file, and compare the mapping below and browser computed styles for drift.

## Colors

White content surfaces sit on a cool pale background. A dark sidebar gives the workspace a stable edge. Purple marks the primary operation, active navigation, and selected investigation context. Brick marks dependency impact; green marks healthy or completed state. Every semantic state also has text or an icon. Muted text must remain legible at small sizes; border color is decorative and is never the sole indication of focus or state.

| Document role | Runtime token | Main consumers |
|---|---|---|
| `background`, `surface`, `sidebar` | `--color-bg`, `--color-surface`, `--color-sidebar` | App shell, content panels, navigation |
| `primary`, `ink`, `muted` | `--color-brand`, `--color-ink`, `--color-muted` | Buttons, headings, secondary copy |
| `border`, `sidebar-muted` | `--color-border`, `--color-sidebar-muted` | Dividers, sidebar copy |
| `impact`, `success` | `--color-impact`, `--color-success` | Ripple exposure, status labels |
| `display`, `body` | `--font-display`, `--font-body` | Headings, controls and body copy |
| `control`, `card` | `--radius-control`, `--radius-card` | Controls, panels and overlays |

Impact text uses `colors.impact-ink` → `--color-impact-ink` (#a84639) on pale impact surfaces to maintain AA contrast; `impact` remains the graph stroke and border role.

The stylesheet also owns global `--scrollbar-thumb`, `--scrollbar-track`, `--scrollbar-hover`, and `--scrollbar-active` values. These apply to every application scroll region without a theme opt-in class. Forced-colors mode uses system-operable scrollbars. The current supported visual theme is light content with dark navigation; a dark-mode switch is not offered.

## Typography

Use locally bundled Sora for the logo and restrained display headings; DM Sans for readable body text, controls, source excerpts, and data. Sans-serif fallbacks preserve legibility while fonts load. Sentence case and plain verbs keep task labels easy to scan. Long source excerpts and questions wrap; never truncate the only available evidence. Format dates and counts through `Intl` using the browser locale; stored timestamps remain UTC.

## Layout

The desktop shell separates persistent navigation, the dependency workspace, and an investigation panel. Their hierarchy should make the selected scenario and next action obvious before the user reads every node. Use compact utility labels and generous breathing room around the graph, with denser evidence and activity lists.

At narrow widths, columns stack and navigation remains reachable. Individual graph and long evidence regions may scroll; ordinary content retains document scrolling. Reserve graph, loader, and message geometry so new data does not move primary controls. All critical labels and actions remain visible without hover. CSS is the sole owner of exact spacing and breakpoints.

## Elevation & Depth

Use borders and tonal separation for static panels. Restrained shadow may distinguish floating graph controls and modal layers. Avoid unnecessary glass effects, backdrop ornament, and a separate shadow on every item. Modal elevation communicates a temporary focused task.

## Shapes

Controls use the shared control radius; panels and overlays use the card family. Pills are reserved for short statuses, labels, and compact source references. Nodes must be identifiable by text and kind, with clear selection and impact treatment rather than shape alone.

## Components

`frontend/src/components/ui.tsx` owns `Button`, `Modal`, `Status`, and `SourceButton`. Reuse these across Overview, Knowledge, Memory, and Actions. `Button` variants are `primary`, `secondary`, and `ghost`; primary emphasizes the next deliberate step, secondary an alternative, and ghost a contextual utility. Do not invent screen-local equivalents. Native scenario selection accepts the operating system's popup geometry and keyboard behavior.

Every enabled control has hover, pressed, visible focus, and pointer affordances. Disabled and pending controls suppress duplicate work. Pending text or an app-owned indicator preserves button geometry. Selected and completed states include readable labels; errors include a recovery action or instruction. Loading uses status text or an indicator rather than decorative skeletons.

`Modal` uses Radix Dialog for accessible naming, focus containment, Escape, and scroll locking, with focus returned to its opening control when closed. Source details and note entry use the same modal behavior. `Status` owns shared inline feedback and live-region announcements; critical errors stay visible with their affected workflow. `SourceButton` opens the full citation so evidence is one action away.

Forms have visible labels and app-owned validation. Product forms use `noValidate`; errors preserve values and identify what to correct. Textareas cannot be manually resized and must provide enough space or scrolling for long content. Search includes an explicit accessible clear action. Source upload means storing a note with provenance; copy must not imply semantic extraction occurred.

Lucide supplies consistent stroke icons. Pair icons with labels for unfamiliar operations, and name every icon-only button. Motion communicates impact or progress sparingly; respect `prefers-reduced-motion` and keep all meaning available without animation. Graph data always has a readable textual explanation of the affected entities and supporting sources.

## Do's and Don'ts

- **Do:** Keep the sample workspace and Guided demo labels visible wherever they affect interpretation.
- **Do:** Use the same approval, status, source-viewing, and error patterns across screens.
- **Don't:** Present dependency exposure counts as probabilities or financial forecasts.
- **Don't:** Give an unsupported answer, speculative edge, or hypothetical scenario the visual authority of a sourced fact.
