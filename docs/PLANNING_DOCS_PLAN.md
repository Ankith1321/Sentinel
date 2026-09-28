# Plan: writing Sentinel's 6 pre-build documents

## What the PDF is actually saying

The framework is simple: before an AI agent (or you) writes a line of code, you write six short documents, in a specific order, because each one answers a category of question the AI would otherwise have to guess at. Skip them and the agent fills the gaps with assumptions — some right, most not, and you spend your time undoing bad architectural calls instead of building.

The six, in the order the doc wants them written:

1. **PRD (Product Requirements Doc)** — what you're building and for whom. The north star everything else flows from.
2. **TRD (Technical Requirements Doc)** — which stack, tools, APIs. Locks in decisions so the agent stays consistent file to file.
3. **App Flow** — every screen, every click, every navigation path. What makes separate pages feel like one product instead of parts built in isolation.
4. **UI/UX Design Brief** — how it looks and feels. Palette, type, component style, dark/light.
5. **Backend Schema** — tables, columns, relationships, auth, permissions. The one that's genuinely painful to change after the fact.
6. **Implementation Plan** — the literal build order, phase by phase, with a "done" definition for each phase.

The suggested workflow is: fill each one conversationally with an AI's help rather than writing from a blank page, then paste all six at the start of every agent session as the source of truth.

## Where this actually lands on Sentinel

Here's the honest part: this framework is written for greenfield projects — write the docs, then write the code. Sentinel's not that. You've already got code, and it's got known bugs. So this isn't "plan before building," it's "retrofit the plan onto what exists, and let it drive everything from here forward." That's still worth doing — arguably more so, since right now your only planning document is `docs/CONTEXT.md`, which mixes PRD content, TRD content, and roadmap content together in one file. Splitting it into these six sharpens each piece and gives you something genuinely reusable for the next project too, not just this one.

Doc by doc, what already exists versus what's a real gap:

**PRD** — partially exists. `docs/CONTEXT.md` section 2 has the purpose and goal, but there's no target user persona, no explicit must-have vs nice-to-have split, no success metrics. This needs real writing, not just reformatting — and it's the right place to lock in the "internal engineering knowledge assistant" framing instead of "RAG chatbot."

**TRD** — mostly exists already. Section 3 of `docs/CONTEXT.md` (the tech stack table) and section 10 (decision log) cover almost everything this template asks for. Quick to formalize, not much new thinking required.

**App Flow** — doesn't exist at all, and it's the one you actually need most. Right now the frontend is one page with no navigation. But your own roadmap (Phase 6 sessions, Phase 8 chat UI, file upload) is about to turn it into a multi-screen app with auth-adjacent state, conversation history, and upload flows. Write this now, before Phase 6-8 work starts, or you'll end up with exactly the "pages that work individually but don't connect" problem the doc warns about.

**UI/UX Design Brief** — doesn't exist as a document, but a real direction already exists in the code — `page.tsx` is dark mode, zinc/white palette, rounded-2xl cards, no heavy shadows. This one's mostly transcription: pull the existing choices out of the code and write them down so they stay consistent as you add screens, instead of drifting.

**Backend Schema** — thin, and this is the trickiest one for Sentinel specifically, because there isn't really a relational database yet. Storage today is a JSONL file plus ChromaDB collections. But Phase 6 (conversation memory) and Phase 4 (document uploads with hash tracking) both need real tables — sessions, messages, documents, users eventually. Write this now so those two phases don't get built on an improvised schema you have to redo later.

**Implementation Plan** — exists in spirit as the Phase 1-9 roadmap already in `docs/CONTEXT.md`, but it's not in this framework's shape: numbered phases with explicit "done" criteria per phase. Mostly a restructure of what you already decided, not new thinking.

## The actual plan — order to write these, and why that order

Given it's a retrofit, I'd write them in a different order than the doc's default, because some are nearly free and some need real thought:

1. **TRD first** — almost entirely already decided, gets you a quick win and a clean reference doc.
2. **PRD second** — needs the most actual thinking (the reframe, the persona, success metrics), and everything else should be checked against it once it's written.
3. **UI/UX Brief third** — quick, just formalizing what the code already does.
4. **Backend Schema fourth** — needs real design work since Phase 4 and Phase 6 depend on getting it right the first time.
5. **App Flow fifth** — needs the schema decided first, since navigation and session state depend on what a "session" and a "document" actually are.
6. **Implementation Plan last** — folds all five of the above into one phased build sequence with done-criteria, replacing the current roadmap section in `docs/CONTEXT.md`.

Practically: each becomes its own file in `docs/` — `docs/01_PRD.md` through `docs/06_IMPLEMENTATION_PLAN.md` — and `CLAUDE.md` at the root gets updated to point at all six instead of just `CONTEXT.md`, so they load automatically every session instead of needing to be pasted in.

## What I'd do next

I already have enough context on Sentinel — the stack, the bugs, the roadmap, the target market — to draft real first versions of all six rather than handing you templates to fill in yourself. Say the word and I'll write them straight into `docs/` in that order.
