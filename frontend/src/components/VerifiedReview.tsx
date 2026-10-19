"use client";

import { useEffect, useState } from "react";
import {
  approveVerified,
  deleteVerified,
  getSeedQuestions,
  listVerified,
  queueDrafts,
  rejectVerified,
  type VerifiedAnswer,
  type VerifiedStatus,
} from "@/lib/api";

const TABS: { status: VerifiedStatus; label: string; hint: string }[] = [
  { status: "pending", label: "Pending", hint: "Drafts waiting for review. Nothing here is served to users yet." },
  { status: "approved", label: "Approved", hint: "Served instantly when a new question matches closely enough." },
  { status: "stale", label: "Stale", hint: "A cited source file changed after approval, so the answer is no longer served." },
  { status: "rejected", label: "Rejected", hint: "Kept for reference and never served." },
];

const MAX_DRAFTS = 100;

function ReviewItem({ item, onChange, onError }: { item: VerifiedAnswer; onChange: () => void; onError: (m: string) => void }) {
  const [text, setText] = useState(item.answer);
  const [busy, setBusy] = useState(false);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      onChange();
    } catch (err) {
      onError(err instanceof Error ? err.message : "That action failed");
    } finally {
      setBusy(false);
    }
  }

  const edited = text.trim() !== item.answer.trim();

  return (
    <li className="space-y-3 border-t border-zinc-800 pt-4 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-zinc-100">{item.question}</h3>
        <span className="text-xs text-zinc-500">
          #{item.id} · {item.origin === "chat" ? "from a chat answer" : "drafted by the model"}
          {item.status === "approved" ? ` · served ${item.times_served}×` : ""}
        </span>
      </div>
      {item.stale_reason && <p className="text-xs text-amber-200">{item.stale_reason}</p>}
      {item.status === "pending" || item.status === "stale" ? (
        <textarea
          aria-label={`Answer for: ${item.question}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="min-h-28 w-full resize-y rounded-xl border border-zinc-700 bg-zinc-950 p-3 text-sm leading-6 text-zinc-200 outline-none focus:border-zinc-500"
        />
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-6 text-zinc-300">{item.answer}</p>
      )}
      <div className="flex flex-wrap gap-1.5 text-xs">
        {item.sources.map((s) => (
          <span key={s.id} className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-0.5 font-mono text-zinc-400" title={s.path ?? ""}>
            {s.id} {s.path}
          </span>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {(item.status === "pending" || item.status === "stale") && (
          <button
            type="button"
            disabled={busy}
            onClick={() => act(() => approveVerified(item.id, edited ? text : undefined))}
            className="cursor-pointer rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-zinc-950 disabled:opacity-50"
          >
            {edited ? "Save edits and approve" : item.status === "stale" ? "Checked, approve again" : "Approve"}
          </button>
        )}
        {item.status === "stale" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => act(async () => { await deleteVerified(item.id); await queueDrafts([item.question]); })}
            className="cursor-pointer rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:border-zinc-500 disabled:opacity-50"
          >
            Re-draft from current code
          </button>
        )}
        {item.status !== "rejected" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => act(() => rejectVerified(item.id))}
            className="cursor-pointer rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:border-zinc-500 disabled:opacity-50"
          >
            Reject
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => act(() => deleteVerified(item.id))}
          className="cursor-pointer rounded-lg border border-zinc-800 px-3 py-1.5 text-xs text-zinc-400 hover:border-red-800 hover:text-red-300 disabled:opacity-50"
        >
          Delete
        </button>
      </div>
    </li>
  );
}

export function VerifiedReview({ refreshToken, onChanged }: { refreshToken: number; onChanged: () => void }) {
  const [tab, setTab] = useState<VerifiedStatus>("pending");
  const [data, setData] = useState<{ counts: Record<VerifiedStatus, number>; items: VerifiedAnswer[] } | null>(null);
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [drafts, setDrafts] = useState("");

  useEffect(() => {
    let cancelled = false;
    listVerified(tab)
      .then((list) => {
        if (!cancelled) setData({ counts: list.counts, items: list.items });
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load verified answers");
      });
    return () => {
      cancelled = true;
    };
  }, [tab, reload, refreshToken]);

  const changed = () => {
    setError("");
    setReload((r) => r + 1);
    onChanged();
  };

  async function loadSeeds() {
    try {
      const seeds = await getSeedQuestions();
      setDrafts(seeds.join("\n"));
      setNotice(seeds.length ? `${seeds.length} starter questions loaded. Edit the list, then draft.` : "Every starter question is already in the queue.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load starter questions");
    }
  }

  async function draft() {
    const questions = [...new Set(drafts.split("\n").map((q) => q.trim()).filter((q) => q.length >= 3))].slice(0, MAX_DRAFTS);
    if (questions.length === 0) return;
    try {
      const { queued } = await queueDrafts(questions);
      setDrafts("");
      setNotice(`Drafting ${queued} answers in the background (about 8 s each). They appear under Pending as they finish.`);
      setTab("pending");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not queue drafts");
    }
  }

  const current = TABS.find((t) => t.status === tab)!;
  const draftCount = drafts.split("\n").filter((q) => q.trim().length >= 3).length;

  return (
    <div className="space-y-5">
      <div role="tablist" aria-label="Verified answers by status" className="flex flex-wrap gap-1 rounded-xl bg-zinc-950 p-1 text-sm">
        {TABS.map((t) => (
          <button
            key={t.status}
            type="button"
            role="tab"
            aria-selected={tab === t.status}
            onClick={() => setTab(t.status)}
            className="cursor-pointer rounded-lg px-3 py-1.5 text-zinc-400 aria-selected:bg-zinc-800 aria-selected:text-zinc-100"
          >
            {t.label} <span className="tabular-nums text-zinc-500">{data?.counts[t.status] ?? "–"}</span>
          </button>
        ))}
      </div>
      <p className="text-xs text-zinc-500">{current.hint}</p>

      {notice && <p className="rounded-xl border border-zinc-800 bg-zinc-950 p-3 text-sm text-zinc-300">{notice}</p>}
      {error && (
        <p role="alert" className="rounded-xl border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
          {error}
        </p>
      )}

      {data && data.items.length === 0 ? (
        <p className="text-sm text-zinc-400">Nothing {current.label.toLowerCase()}.</p>
      ) : (
        <ul className="space-y-4">
          {data?.items.map((item) => (
            <ReviewItem key={`${item.id}-${item.status}-${item.answer.length}`} item={item} onChange={changed} onError={setError} />
          ))}
        </ul>
      )}

      <div className="space-y-2 border-t border-zinc-800 pt-4">
        <label htmlFor="draft-questions" className="text-sm font-medium text-zinc-200">
          Draft answers for new questions
        </label>
        <p className="text-xs text-zinc-500">One question per line. The model answers each from the codebase; nothing is served until you approve it.</p>
        <textarea
          id="draft-questions"
          value={drafts}
          onChange={(e) => setDrafts(e.target.value)}
          placeholder="How does Superset handle query timeouts?"
          className="min-h-24 w-full resize-y rounded-xl border border-zinc-700 bg-zinc-950 p-3 text-sm text-zinc-200 outline-none focus:border-zinc-500"
        />
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={draft} disabled={draftCount === 0} className="cursor-pointer rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-zinc-950 disabled:opacity-50">
            Draft {draftCount || ""} answers
          </button>
          <button type="button" onClick={loadSeeds} className="cursor-pointer rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:border-zinc-500">
            Load starter questions
          </button>
        </div>
      </div>
    </div>
  );
}
