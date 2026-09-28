# Sentinel

RAG pipeline for the Apache Superset codebase. Backend: FastAPI + ChromaDB + sentence-transformers. Frontend: Next.js.

Full architecture, mandatory engineering rules, and the current bug list: @docs/CONTEXT.md
Prioritized plan for turning this into a resume-ready project: @docs/SENIOR_REVIEW.md
Plan for the 6 pre-build docs (PRD/TRD/App Flow/UI-UX/Schema/Implementation): @docs/PLANNING_DOCS_PLAN.md

Known state: the Phase 1 bugs listed in docs/CONTEXT.md (section 6) are not fixed yet. Do not add new features before those are fixed.

## Hard rule — no unsolicited .md files

Never create, write, or save a new `.md` file anywhere in this project unless the user has explicitly asked for that specific file in that turn. This applies to every kind of markdown file — reviews, plans, summaries, recaps, roadmaps, READMEs, notes — no exceptions for "helpful" or "durable" documentation. Doing analysis, a review, or a recap is fine; the output goes in the chat response, not into a new file, unless the user's message explicitly asks for a file/document to be written or saved. When in doubt, answer in chat and ask before creating a file.
