# Sentinel — frontend

Next.js 16 app for Sentinel: chat, documents, and the admin dashboard. See the [root README](../README.md) and [`docs/03_APP_FLOW.md`](../docs/03_APP_FLOW.md).

## Dev

```bash
npm install
npm run dev
```

Open http://localhost:3000. Use `localhost`, not `127.0.0.1`: the dev server blocks its own dev resources for other origins and the page will not become interactive.

`.env.local` (server-side only, never `NEXT_PUBLIC_`):

```
SENTINEL_API_URL=http://127.0.0.1:8000
SENTINEL_API_KEY=<a regular API key, not the admin key>
```

## How requests flow

- The browser calls only `/api/*`. `src/app/api/[...path]/route.ts` forwards an allow-list of routes to the API with the regular key.
- `/api/admin/*` is forwarded only with the admin's key from the `sentinel_admin` HttpOnly cookie, which `src/app/api/admin-session/route.ts` sets after checking the key against the API.
- The Dashboard link appears only for a signed-in admin; `/dashboard` shows the sign-in form to everyone else.

## Checks

```bash
npm run lint && npx tsc --noEmit && npm run build
```
