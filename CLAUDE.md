# Sentinel

Internal engineering knowledge assistant over the Apache Superset codebase. Backend: FastAPI + ChromaDB + SQLite + sentence-transformers (bge-small) + local Qwen2.5-3B (Claude when a key is set). Frontend: Next.js 16 with a server-side proxy and an admin-only dashboard.

Full architecture, mandatory engineering rules (section 8), and the decision log: @docs/CONTEXT.md
Senior-engineer review and the reasoning behind the roadmap: @docs/SENIOR_REVIEW.md

The 6 planning documents are the hard rules for product, technical, flow, design, schema and phase decisions. Read them before docs/CONTEXT.md wherever they overlap, and update them in the same piece of work whenever a change departs from them:
- Product requirements: @docs/01_PRD.md
- Technical requirements: @docs/02_TRD.md
- App flow: @docs/03_APP_FLOW.md
- UI/UX design brief: @docs/04_UI_UX_DESIGN_BRIEF.md
- Backend schema: @docs/05_BACKEND_SCHEMA.md
- Implementation plan (phase status and definitions of done): @docs/06_IMPLEMENTATION_PLAN.md

Known state (2026-10-19): Phases 1-9 and 11 are done (Phase 5 has one gap: the Claude path has never run against the real API). Phase 10 (CI, containers, Azure deploy) is written but not run. The project model is Qwen2.5-3B-Instruct, whose licence is non-commercial only. Every quality claim must come from the eval suites in `eval/`.

## Hard rule — no unsolicited .md files

Never create, write, or save a new `.md` file anywhere in this project unless the user has explicitly asked for that specific file in that turn. This applies to every kind of markdown file — reviews, plans, summaries, recaps, roadmaps, READMEs, notes — no exceptions for "helpful" or "durable" documentation. Doing analysis, a review, or a recap is fine; the output goes in the chat response, not into a new file, unless the user's message explicitly asks for a file/document to be written or saved. When in doubt, answer in chat and ask before creating a file.
