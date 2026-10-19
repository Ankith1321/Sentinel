# UI/UX Design Brief

**Project:** Sentinel
**Status:** Describes the shipped interface (chat, documents, admin dashboard) as of 2026-10-19. New screens must follow it; a new color or container style is added here first.
**Related:** [`03_APP_FLOW.md`](03_APP_FLOW.md)

## 1. Design philosophy

Dark-only, minimal, content-forward, no decoration. Every rule below is taken from the code, so new screens stay consistent with what already exists.

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
| Primary action (button) | white background, `zinc-950` text: the one deliberately high-contrast element |
| Error | `red-950/40` background, `red-900` border, `red-300` text |
| Review needed (answer checker, stale verified answer) | `amber-950/40` background, `amber-900` border, `amber-200` text |
| Verified answer badge | `emerald-950/40` background, `emerald-900` border, `emerald-200` text, `emerald-400` dot |
| Chart series (dashboard) | `#3987e5`, one hue only, validated against the `zinc-900` card (lightness, chroma and 3:1 contrast all pass) |
| Status dots (dashboard) | good `#0ca30c`, warning `#fab219`, critical `#d03b3b`, neutral `zinc-500`. Always paired with a text label, never color alone |

There is no light mode and none is planned. Changing that is a conscious decision made in this document first.

## 3. Typography

System sans stack, no webfont: a webfont adds load time for a tool with no visual need for one.

- `text-4xl font-bold`: page title
- `text-xl font-semibold`: section headers
- `text-base font-semibold`: dashboard card titles
- `text-3xl font-semibold`: dashboard tile values (proportional figures)
- `text-sm`: body text, answers, source previews
- `text-xs`: metadata, axis labels, hints
- `tabular-nums`: table columns and axis ticks only

## 4. Layout

- Chat and Documents: single column, `max-w-5xl`, centered, `px-6 py-10`. Chat adds a 250 px session sidebar from `md` up.
- Dashboard: `max-w-6xl`, because it holds tables and two-column card rows. Tiles are 2 columns on small screens and 4 on large; card rows are 1 column, then 2 from `lg`.
- Cards: `rounded-2xl`, bordered, **no drop shadow**.
- At 390 px every page is exactly the screen width: long paths break inside their chip, and tables scroll inside their own container.

## 5. Component inventory

- **Chat:** textarea; primary button (disabled under 3 characters); Stop button while streaming; sources-per-answer slider; message bubbles; citation chips (`[S1]` in a bordered mono chip); collapsible source cards; Helpful / Not helpful buttons; review note (amber); verified badge (emerald); inline failed bubble (red).
- **Documents:** drop zone, upload rows with status, Uploaded / Codebase switch, paginated list.
- **Dashboard:**
  - status pills (dot + label) and stat tiles;
  - two hand-drawn SVG charts (columns for questions per day, bars for hit@5 per eval run), each with hover/focus tooltips and a "Show as table" view;
  - data tables;
  - the verified-answer review queue (status tabs, editable answer, approve/reject/delete/re-draft, five items at a time with "Show more");
  - admin sign-in form.

## 6. States

- **Empty:** components that have no data are not rendered, or show a sentence saying what will appear and how to add it.
- **Loading:** persistent, not a toast. Streaming shows "Searching Superset and drafting a grounded answer…" until the first token; the dashboard dims to 70% while it refreshes instead of blanking.
- **Error:** rendered where it happened (inline bubble, card notice), with the reason.
- **Review needed:** amber note under the answer, naming what is missing.
- **Verified:** emerald badge with the approval date and the question it matched.

The chat textarea stays editable while an answer streams, so the next question can be drafted. Double-sends are prevented by the button, which turns into Stop. This is a deliberate exception to rule 8.7 in `CONTEXT.md`.

## 7. Guidance for new screens

- Stay within the palette above; add any new color to this document first.
- Reuse the `rounded-2xl`, `zinc-900`, `zinc-800` card pattern.
- Loading and error states are first-class, persistently rendered states, not toasts.
- Charts: one hue per series, a legend once there are two or more series, solid hairline gridlines, and a table view.
