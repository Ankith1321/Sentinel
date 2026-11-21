# Sentinel — frontend

Next.js 16 chat page for Sentinel. See the [root README](../README.md).

## Dev

```bash
npm install
npm run dev
```

Open http://localhost:3000. Use `localhost`, not `127.0.0.1`: the dev server blocks its own dev resources for other origins and the page will not become interactive.

`.env.local` (server-side only, never `NEXT_PUBLIC_`):

```
SENTINEL_API_URL=http://127.0.0.1:8000
SENTINEL_API_KEY=<the same value as SENTINEL_API_KEY in the root .env>
```

## How requests flow

The browser calls only `/api/*`. `src/app/api/[...path]/route.ts` forwards an allow-list of routes (`query`, `search`, `sessions`, `messages`) to the API and adds the key on the server, so the key never reaches the browser.

## Checks

```bash
npm run lint && npx tsc --noEmit && npm run build
```
