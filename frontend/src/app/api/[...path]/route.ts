import type { NextRequest } from "next/server";

const API_URL = process.env.SENTINEL_API_URL ?? "http://127.0.0.1:8000";
const API_KEY = process.env.SENTINEL_API_KEY ?? "";

const ALLOWED_ROOTS = new Set(["query", "search", "sessions", "messages", "documents", "jobs"]);
const FORWARDED_RESPONSE_HEADERS = ["content-type", "cache-control"];

async function proxy(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;

  if (!ALLOWED_ROOTS.has(path[0])) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  if (API_KEY) headers.set("x-api-key", API_KEY);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    duplex: hasBody ? "half" : undefined,
    cache: "no-store",
  };

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/${path.join("/")}${request.nextUrl.search}`, init);
  } catch {
    return Response.json({ detail: "The Sentinel API is unreachable." }, { status: 502 });
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export { proxy as GET, proxy as POST, proxy as DELETE };
