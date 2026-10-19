"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  adminSignOut,
  ApiError,
  getDashboard,
  promoteMessage,
  type AnswerRun,
  type DashboardData,
  type RetrievalRun,
} from "@/lib/api";
import { QueriesPerDayChart, RetrievalRunsChart } from "./DashboardCharts";
import { VerifiedReview } from "./VerifiedReview";

const REFRESH_MS = 20_000;
const STATUS = { good: "#0ca30c", warning: "#fab219", critical: "#d03b3b", neutral: "#71717a" } as const;
type Tone = keyof typeof STATUS;

const pct = (v: number | null | undefined) => (v == null ? "–" : `${(v * 100).toFixed(1).replace(/\.0$/, "")}%`);
const ms = (v: number) => (v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`);
const num = (v: number | null | undefined) => (v == null ? "–" : v.toLocaleString());

function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

function duration(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} d`;
}

function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-zinc-800 bg-zinc-950 px-2.5 py-1 text-xs text-zinc-300">
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: STATUS[tone] }} />
      {children}
    </span>
  );
}

function Card({ title, subtitle, children, className = "" }: { title: string; subtitle?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 rounded-2xl border border-zinc-800 bg-zinc-900 p-5 ${className}`}>
      <div className="mb-4">
        <h2 className="text-base font-semibold text-zinc-100">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function Tile({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: Tone }) {
  return (
    <div className="min-w-0 rounded-2xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex items-center gap-2 text-xs text-zinc-400">
        {tone && <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: STATUS[tone] }} />}
        {label}
      </div>
      <div className="mt-2 text-3xl font-semibold tracking-tight text-zinc-100">{value}</div>
      <div className="mt-1 text-xs text-zinc-500">{detail}</div>
    </div>
  );
}

function Rows({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-zinc-500">{k}</dt>
          <dd className="min-w-0 break-words text-zinc-200">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Table({ head, children, empty }: { head: string[]; children: ReactNode; empty?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm tabular-nums">
        <thead>
          <tr className="text-xs text-zinc-500">
            {head.map((h) => (
              <th key={h} className="whitespace-nowrap pb-2 pr-4 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-zinc-300">{children}</tbody>
      </table>
      {empty && <p className="pt-2 text-sm text-zinc-500">{empty}</p>}
    </div>
  );
}

const sameSetup = (a: RetrievalRun, b: RetrievalRun) =>
  a.mode === b.mode && a.collection === b.collection && a.embedding_model === b.embedding_model;

function retrievalTile(runs: RetrievalRun[]) {
  const latest = runs[0];
  if (!latest) return { value: "–", detail: "no eval run yet" };
  const previous = runs.slice(1).find((r) => sameSetup(r, latest));
  const delta = previous ? (latest.hit_at_5 - previous.hit_at_5) * 100 : null;
  const deltaText = delta == null ? "" : ` · ${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pts vs previous`;
  return { value: pct(latest.hit_at_5), detail: `${latest.label}${deltaText}` };
}

function answerTile(runs: AnswerRun[]) {
  const latest = runs[0];
  if (!latest) return { value: "–", detail: "no answer eval yet" };
  return { value: pct(latest.cites_a_source), detail: `right file ${pct(latest.cites_expected_file)} · refuses off-topic ${pct(latest.refuses_off_topic)}` };
}

const STATE_TONE: Record<string, Tone> = { done: "good", partial: "warning", todo: "neutral", running: "warning", failed: "critical", unchanged: "good", queued: "neutral", processing: "warning" };
const STATE_LABEL: Record<string, string> = { done: "Done", partial: "Partly done", todo: "Not started" };

export function Dashboard() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getDashboard()
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError("");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          adminSignOut().then(() => router.refresh());
          return;
        }
        setError(err instanceof Error ? err.message : "Could not load the dashboard");
      })
      .finally(() => {
        if (!cancelled) setRefreshing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tick, router]);

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") {
        setRefreshing(true);
        setTick((t) => t + 1);
      }
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const refresh = () => {
    setRefreshing(true);
    setTick((t) => t + 1);
  };

  async function signOut() {
    await adminSignOut();
    router.refresh();
  }

  async function promote(messageId: number) {
    try {
      const { id } = await promoteMessage(messageId);
      setNotice(`Added to the review queue as #${id}. Approve it under Verified answers to start serving it.`);
      refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not add that answer");
    }
  }

  if (!data) {
    return error ? (
      <div role="alert" className="rounded-2xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
        {error}. Check that the API is running on the address in <code>frontend/.env.local</code>.
      </div>
    ) : (
      <p className="text-sm text-zinc-400">Loading the dashboard…</p>
    );
  }

  const { service, corpus, usage } = data;
  const lastSync = corpus.sync_runs[0];
  const retrieval = retrievalTile(data.retrieval_runs);
  const answers = answerTile(data.answer_runs);
  const flaggedRatio = usage.checked ? usage.flagged / usage.checked : null;
  const rated = usage.feedback_up + usage.feedback_down;
  const gpu = service.gpu;
  const doneCount = data.plan.filter((p) => p.state === "done").length;

  return (
    <div className={`grid gap-6 transition-opacity ${refreshing ? "opacity-70" : ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <Status tone="good">API online · up {duration(service.uptime_seconds)}</Status>
          <Status tone={service.provider === "anthropic" ? "good" : "warning"}>
            {service.provider === "anthropic" ? "Claude" : "Local model"}: {service.model.split("/").pop()}
            {service.quantization ? ` (${service.quantization})` : ""}
          </Status>
          <Status tone={service.chunks_in_index ? "good" : "critical"}>Index: {num(service.chunks_in_index)} chunks</Status>
          <Status tone={lastSync ? STATE_TONE[lastSync.status] ?? "neutral" : "neutral"}>
            Last sync: {lastSync ? `${lastSync.status}, ${ago(lastSync.finished_at ?? lastSync.started_at)}` : "never"}
          </Status>
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          Updated {new Date(data.generated_at).toLocaleTimeString()}
          <button type="button" onClick={refresh} className="cursor-pointer rounded-xl border border-zinc-700 px-3 py-1.5 text-zinc-200 hover:border-zinc-500">
            Refresh
          </button>
          <button type="button" onClick={signOut} className="cursor-pointer rounded-xl border border-zinc-800 px-3 py-1.5 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200">
            Sign out
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-2xl border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
          Refresh failed: {error}. Showing the last data received.
        </div>
      )}

      {notice && <p role="status" className="rounded-2xl border border-zinc-800 bg-zinc-900 p-3 text-sm text-zinc-300">{notice}</p>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Questions answered" value={num(usage.queries)} detail={`${num(usage.sessions)} conversations`} />
        <Tile label="p95 response time" value={usage.queries ? ms(usage.p95_total_ms) : "–"} detail={`avg search ${ms(usage.avg_retrieval_ms)} · avg answer ${ms(usage.avg_generation_ms)}`} />
        <Tile
          label="Answers flagged for review"
          value={pct(flaggedRatio)}
          detail={`${usage.flagged} of ${usage.checked} checked`}
          tone={flaggedRatio == null ? undefined : flaggedRatio <= 0.1 ? "good" : flaggedRatio <= 0.3 ? "warning" : "critical"}
        />
        <Tile label="Rated helpful" value={pct(usage.feedback_positive_ratio)} detail={`${usage.feedback_up} up · ${usage.feedback_down} down${rated ? "" : " · no ratings yet"}`} />
        <Tile label="Retrieval hit@5" value={retrieval.value} detail={retrieval.detail} />
        <Tile label="Answers citing a source" value={answers.value} detail={answers.detail} />
        <Tile label="Verified answers" value={num(data.verified.approved)} detail={`served ${num(data.verified.served)} times from the database`} />
        <Tile
          label="Waiting for review"
          value={num(data.verified.pending)}
          detail={`${data.verified.stale} stale · ${data.verified.rejected} rejected`}
          tone={data.verified.stale > 0 ? "warning" : undefined}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Questions per day" subtitle="Last 14 days, UTC">
          <QueriesPerDayChart days={usage.queries_per_day} />
        </Card>
        <Card title="Retrieval quality by eval run" subtitle="hit@5 on the fixed 40-question set">
          <RetrievalRunsChart runs={data.retrieval_runs} />
        </Card>
      </div>

      <Card title="Recent questions" subtitle="Newest first. Flagged means the answer checker found no valid citation or a name missing from the sources.">
        <Table head={["When", "Question", "Model", "Search", "Answer", "Check", ""]} empty={data.recent_queries.length ? undefined : "No questions yet."}>
          {data.recent_queries.map((q) => (
            <tr key={`${q.created_at}-${q.question}`} className="border-t border-zinc-800 align-top">
              <td className="whitespace-nowrap py-2 pr-4 text-zinc-500">{ago(q.created_at)}</td>
              <td className="max-w-md py-2 pr-4 text-zinc-200">{q.question}</td>
              <td className="whitespace-nowrap py-2 pr-4 text-zinc-400">{q.model.split("/").pop()}</td>
              <td className="whitespace-nowrap py-2 pr-4">{ms(q.retrieval_ms)}</td>
              <td className="whitespace-nowrap py-2 pr-4">{ms(q.generation_ms)}</td>
              <td className="whitespace-nowrap py-2 pr-4">
                {q.verified_answer_id ? (
                  <Status tone="good">Verified #{q.verified_answer_id}</Status>
                ) : q.needs_review == null ? (
                  <span className="text-zinc-500">–</span>
                ) : q.needs_review ? (
                  <Status tone="warning">Review</Status>
                ) : (
                  <Status tone="good">OK</Status>
                )}
              </td>
              <td className="whitespace-nowrap py-2">
                {q.message_id && !q.verified_answer_id && (
                  <button type="button" onClick={() => promote(q.message_id!)} className="cursor-pointer rounded-lg border border-zinc-700 px-2.5 py-1 text-xs text-zinc-300 hover:border-zinc-500">
                    Make verified
                  </button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card
        title="Verified answers"
        subtitle="Approved answers are served straight from the database when a new question matches one closely; everything else goes through search."
      >
        <VerifiedReview refreshToken={tick} onChanged={refresh} />
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Retrieval eval runs" subtitle={`${data.retrieval_runs.length} most recent`}>
          <Table head={["Run", "Mode", "hit@1", "hit@5", "MRR", "When"]}>
            {data.retrieval_runs.slice(0, 12).map((r) => (
              <tr key={`${r.label}-${r.created_at}`} className="border-t border-zinc-800">
                <td className="max-w-[220px] truncate py-2 pr-4 text-zinc-200" title={r.label}>{r.label}</td>
                <td className="py-2 pr-4 text-zinc-400">{r.mode ?? "–"}</td>
                <td className="py-2 pr-4">{pct(r.hit_at_1)}</td>
                <td className="py-2 pr-4 text-zinc-100">{pct(r.hit_at_5)}</td>
                <td className="py-2 pr-4">{r.mrr.toFixed(3)}</td>
                <td className="whitespace-nowrap py-2 text-zinc-500">{ago(r.created_at)}</td>
              </tr>
            ))}
          </Table>
        </Card>
        <Card title="Answer-quality eval runs" subtitle="40 answerable + 8 off-topic questions">
          <Table head={["Model", "Prompt", "Cites", "Right file", "Refuses", "s/answer"]}>
            {data.answer_runs.map((r) => (
              <tr key={`${r.label}-${r.created_at}`} className="border-t border-zinc-800">
                <td className="whitespace-nowrap py-2 pr-4 text-zinc-200" title={r.label}>
                  {(r.model ?? r.label).split("/").pop()}
                  {r.quantization && r.quantization !== "fp16" ? ` ${r.quantization}` : ""}
                </td>
                <td className="py-2 pr-4 text-zinc-400">{r.prompt ?? "–"}</td>
                <td className="py-2 pr-4 text-zinc-100">{pct(r.cites_a_source)}</td>
                <td className="py-2 pr-4">{pct(r.cites_expected_file)}</td>
                <td className="py-2 pr-4">{pct(r.refuses_off_topic)}</td>
                <td className="py-2">{r.avg_seconds.toFixed(1)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Codebase index" subtitle="Kept current by the incremental sync">
          <Rows
            items={[
              ["Corpus commit", corpus.commit ? `${corpus.commit}${corpus.commit_subject ? ` · ${corpus.commit_subject}` : ""}` : "unknown"],
              ["Files tracked", `${num(corpus.files_tracked)} files · ${num(corpus.chunks_tracked)} chunks`],
              ["Uploaded files", num(corpus.uploaded_files)],
              ["Keyword index", service.keyword_index_chunks == null ? "not built yet (builds on first question)" : `${num(service.keyword_index_chunks)} chunks in memory`],
            ]}
          />
          <h3 className="mb-2 mt-5 text-xs font-medium text-zinc-500">Recent syncs</h3>
          <Table head={["Started", "Status", "Added", "Changed", "Removed", "Errors"]} empty={corpus.sync_runs.length ? undefined : "No sync has run yet."}>
            {corpus.sync_runs.map((s) => (
              <tr key={s.id} className="border-t border-zinc-800">
                <td className="whitespace-nowrap py-2 pr-4 text-zinc-500">{ago(s.started_at)}</td>
                <td className="py-2 pr-4"><Status tone={STATE_TONE[s.status] ?? "neutral"}>{s.status}</Status></td>
                <td className="py-2 pr-4">{num(s.added)}</td>
                <td className="py-2 pr-4">{num(s.changed)}</td>
                <td className="py-2 pr-4">{num(s.removed)}</td>
                <td className="py-2">{s.error ? <span className="text-red-300">{s.error}</span> : s.error_count}</td>
              </tr>
            ))}
          </Table>
          <p className="mt-3 text-xs text-zinc-500">
            Run a sync: <code>curl -X POST -H &quot;X-API-Key: …&quot; http://127.0.0.1:8000/admin/sync?pull=true</code>
          </p>
        </Card>
        <Card title="Uploads" subtitle="Files added through the Documents page">
          <Table head={["File", "Status", "When"]} empty={data.uploads.length ? undefined : "No uploads yet."}>
            {data.uploads.map((u) => (
              <tr key={`${u.filename}-${u.created_at}`} className="border-t border-zinc-800">
                <td className="max-w-[240px] truncate py-2 pr-4 text-zinc-200" title={u.filename}>{u.filename}</td>
                <td className="py-2 pr-4"><Status tone={STATE_TONE[u.status] ?? "neutral"}>{u.status}</Status></td>
                <td className="whitespace-nowrap py-2 text-zinc-500">{ago(u.created_at)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="System">
          <Rows
            items={[
              ["Answer model", `${service.model}${service.quantization ? ` (${service.quantization})` : ""} via ${service.provider}`],
              ["Prompt", service.prompt_variant === "v2" ? "v2, strict citation prompt" : service.prompt_variant],
              ["Retrieval", `${service.retrieval_mode} · ${service.embedding_model}`],
              ["Collection", service.collection],
              ["GPU", gpu ? `${gpu.name} · ${num(gpu.memory_used_mb)} / ${num(gpu.memory_total_mb)} MB in use` : "none (CPU only)"],
              ["Runtime", `Python ${service.python_version} · PyTorch ${service.torch_version}`],
              ["Started", new Date(service.started_at).toLocaleString()],
            ]}
          />
        </Card>
        <Card title="Project plan" subtitle={`${doneCount} of ${data.plan.length} phases done · read from docs/06_IMPLEMENTATION_PLAN.md`}>
          <ul className="grid gap-2">
            {data.plan.map((p) => (
              <li key={p.phase} className="flex flex-wrap items-start justify-between gap-2 border-t border-zinc-800 pt-2 text-sm first:border-t-0 first:pt-0">
                <span className="min-w-0 text-zinc-200">
                  <span className="text-zinc-500">{p.phase.replace("Phase ", "")}</span> {p.title}
                  {p.state !== "done" && <span className="block text-xs text-zinc-500">{p.status}</span>}
                </span>
                <Status tone={STATE_TONE[p.state]}>{STATE_LABEL[p.state]}</Status>
              </li>
            ))}
          </ul>
          {data.commits.length > 0 && (
            <>
              <h3 className="mb-2 mt-5 text-xs font-medium text-zinc-500">Recent commits</h3>
              <ul className="grid gap-1.5 text-sm">
                {data.commits.map((c) => (
                  <li key={c.hash} className="flex gap-3">
                    <code className="text-zinc-500">{c.hash}</code>
                    <span className="min-w-0 truncate text-zinc-300" title={c.subject}>{c.subject}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
