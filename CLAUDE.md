# Sentinel

RAG pipeline for the Apache Superset codebase. Backend: FastAPI + ChromaDB + sentence-transformers. Frontend: Next.js.

Full architecture, mandatory engineering rules, and the historical bug list: @docs/CONTEXT.md
Prioritized plan for turning this into a resume-ready project: @docs/SENIOR_REVIEW.md
Plan for the 6 pre-build docs (PRD/TRD/App Flow/UI-UX/Schema/Implementation): @docs/PLANNING_DOCS_PLAN.md

The 6 pre-build docs (source of truth for product, technical, and design decisions — read these before docs/CONTEXT.md for anything they overlap on):
- Product requirements: @docs/01_PRD.md
- Technical requirements: @docs/02_TRD.md
- App flow: @docs/03_APP_FLOW.md
- UI/UX design brief: @docs/04_UI_UX_DESIGN_BRIEF.md
- Backend schema: @docs/05_BACKEND_SCHEMA.md
- Implementation plan (current phase roadmap, supersedes docs/CONTEXT.md section 9): @docs/06_IMPLEMENTATION_PLAN.md

Known state: the Phase 1 bugs listed in docs/CONTEXT.md (section 6) were fixed and verified live in a working session — see docs/06_IMPLEMENTATION_PLAN.md Phase 1. Current priority per the Implementation Plan's sequencing note: build a minimal eval set before starting Phase 2, since Phase 2 and 3 can't be verified without one.

## Hard rule — no unsolicited .md files

Never create, write, or save a new `.md` file anywhere in this project unless the user has explicitly asked for that specific file in that turn. This applies to every kind of markdown file — reviews, plans, summaries, recaps, roadmaps, READMEs, notes — no exceptions for "helpful" or "durable" documentation. Doing analysis, a review, or a recap is fine; the output goes in the chat response, not into a new file, unless the user's message explicitly asks for a file/document to be written or saved. When in doubt, answer in chat and ask before creating a file.
