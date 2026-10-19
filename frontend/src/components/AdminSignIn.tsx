"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { adminSignIn } from "@/lib/api";

export function AdminSignIn() {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await adminSignIn(key);
      setKey("");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-md space-y-4 rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
      <div>
        <h2 className="text-xl font-semibold">Admin dashboard</h2>
        <p className="mt-1 text-sm text-zinc-400">
          The dashboard is for administrators. Sign in with the admin key (<code>SENTINEL_API_KEY</code> in the
          server&apos;s <code>.env</code>). It is kept in a secure cookie for 8 hours and never shown to the page.
        </p>
      </div>
      <label htmlFor="admin-key" className="block text-sm text-zinc-300">
        Admin key
        <input
          id="admin-key"
          type="password"
          autoComplete="current-password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          className="mt-1 w-full rounded-xl border border-zinc-700 bg-zinc-950 p-3 text-sm text-zinc-100 outline-none focus:border-zinc-500"
        />
      </label>
      {error && (
        <p role="alert" className="rounded-xl border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || key.trim().length === 0}
        className="cursor-pointer rounded-xl bg-white px-5 py-2 text-sm font-medium text-zinc-950 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? "Checking…" : "Sign in"}
      </button>
    </form>
  );
}
