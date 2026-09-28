# UI/UX Design Brief

**Project:** Sentinel
**Status:** Formalizes an existing direction — this documents what's already in the code, it does not propose a redesign
**Related:** [`03_APP_FLOW.md`](03_APP_FLOW.md)

## 1. Design philosophy

Dark-first, minimal, content-forward, no decoration. Every rule below is extracted directly from `frontend/src/app/page.tsx` as it exists today, not invented — the point of this doc is to keep every future screen consistent with what's already shipped, not to define a new look.

## 2. Color palette

Base: Tailwind's `zinc` scale.

| Role | Token |
|---|---|
| Page background | `zinc-950` |
| Card / panel background | `zinc-900` |
| Default border | `zinc-800` |
| Input border | `zinc-700` |
| Primary text | `zinc-100` |
| Secondary / muted text | `zinc-400`, `zinc-500` |
| Primary action (button) | white background, `zinc-950` text — the one deliberately high-contrast element on the page |
| Error state | `red-950/40` background, `red-900` border, `red-300` text — follows the same "dark fill, lighter readable text" pattern as everything else, doesn't introduce a jarring bright red |

There is no light mode and none is planned. This is a deliberate dark-only tool, not a gap — if that ever changes, it's a conscious call to revisit this document first, not a default assumption to slip in through one new screen.

## 3. Typography

System default sans stack (Tailwind default) — no custom webfont is loaded, and none should be added without a specific reason, since a webfont adds load latency for a tool that currently has zero visual need for one.

Scale in current use:
- `text-4xl font-bold` — page title
- `text-xl font-semibold` — section headers ("Answer", "Sources")
- `text-sm` — body text, source previews
- `text-xs` — metadata (language, distance score)

## 4. Layout

- Single column, `max-w-5xl`, centered, `px-6 py-10` outer padding.
- Cards: `rounded-2xl`, bordered, **no drop shadow** — flat design throughout, consistent with the palette above.
- No sidebar, no top nav today — this is a single-tool page, not yet a multi-screen app.

## 5. Component inventory (current)

- Textarea — question input
- Primary button — "Ask Sentinel," with a disabled state below 3 characters
- Loading indicator — inline text swap on the button plus a persistent helper caption, not a spinner
- Error panel — new this session, renders inline above the answer area
- Answer panel — pre-formatted (`<pre>`) text block, preserves the model's citation formatting
- Source card list — id, title, language, distance score, path, content preview, one card per retrieved chunk

## 6. States

- **Empty:** only the input is visible — answer/source panels are conditionally rendered, not hidden with CSS, confirmed in code.
- **Loading:** button text changes, helper caption appears, button disabled, textarea stays editable. This state is intentionally persistent (not a toast) because generation currently takes 50-60 seconds on the local model — see [`02_TRD.md`](02_TRD.md) — and a state that disappears before the request resolves would read as broken.
- **Error:** red panel renders above the answer area, error text from the caught fetch failure.
- **Success:** answer panel and source cards render, no auto-scroll — worth reconsidering once answers routinely run long enough to push the input off-screen.

## 7. Guidance for new screens

Whatever gets built next per the Implementation Plan (Phase 6 conversation memory, Phase 8 chat thread / upload / feedback UI) must:

- Stay within the zinc / white / red palette above — no new color introduced without updating this document first.
- Reuse the `rounded-2xl`, `zinc-900` background, `zinc-800` border card pattern rather than inventing a new container style per screen.
- Treat loading and error states as first-class, persistently rendered states, not toasts — this page's slow local-model latency is exactly why that matters here, and it won't stop mattering just because a new screen gets added.
