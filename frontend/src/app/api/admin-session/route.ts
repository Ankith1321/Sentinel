import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const API_URL = process.env.SENTINEL_API_URL ?? "http://127.0.0.1:8000";
const ADMIN_COOKIE = "sentinel_admin";
const SESSION_SECONDS = 8 * 60 * 60;
const MAX_KEY_LENGTH = 512;

export async function POST(request: NextRequest) {
  let key = "";
  try {
    const body = await request.json();
    key = typeof body.key === "string" ? body.key.trim() : "";
  } catch {
    return Response.json({ detail: "Send the admin key as JSON: {\"key\": \"...\"}" }, { status: 400 });
  }
  if (!key || key.length > MAX_KEY_LENGTH) {
    return Response.json({ detail: "Enter the admin key." }, { status: 400 });
  }

  let check: Response;
  try {
    check = await fetch(`${API_URL}/admin/session`, { headers: { "x-api-key": key }, cache: "no-store" });
  } catch {
    return Response.json({ detail: "The Sentinel API is unreachable." }, { status: 502 });
  }
  if (!check.ok) {
    return Response.json({ detail: "That is not an admin key." }, { status: 401 });
  }

  (await cookies()).set(ADMIN_COOKIE, key, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_SECONDS,
  });
  return Response.json({ admin: true });
}

export async function DELETE() {
  (await cookies()).delete(ADMIN_COOKIE);
  return Response.json({ admin: false });
}
