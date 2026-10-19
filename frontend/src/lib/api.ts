export type Source = {
  id: string;
  path: string | null;
  language: string | null;
  title: string | null;
  distance: number | null;
  score: number | null;
  preview: string | null;
};

export type VerifiedInfo = {
  id: number;
  similarity: number;
  matched_question: string;
  reviewed_at: string | null;
};

export type AnswerChecks = {
  cited_sources: number[];
  invalid_citations: number[];
  unsupported_terms: string[];
  abstained: boolean;
  needs_review: boolean;
};

export type ChatMessage = {
  key: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[] | null;
  checks?: AnswerChecks;
  verified?: VerifiedInfo;
  messageId?: number;
  rating?: -1 | 1;
  streaming?: boolean;
  failed?: boolean;
  model?: string;
  latencyMs?: number;
};

export type SessionSummary = {
  id: string;
  created_at: string;
  last_active_at: string;
  first_question: string | null;
};

type StoredMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[] | null;
  created_at: string;
};

export type SessionDetail = {
  id: string;
  messages: StoredMessage[];
};

export type JobStatus = {
  id: string;
  filename: string;
  status: "queued" | "processing" | "done" | "unchanged" | "failed";
  document_id: string | null;
  error: string | null;
};

export type IndexedDocument = {
  id: string;
  path: string;
  source_type: string;
  language: string | null;
  chunk_count: number;
  last_indexed_at: string;
};

export type DocumentList = { total: number; items: IndexedDocument[] };

export type DonePayload = {
  answer: string;
  sources: Source[];
  model: string;
  retrieval_ms: number;
  generation_ms: number;
  message_id?: number;
  session_id?: string;
  checks?: AnswerChecks;
  verified?: VerifiedInfo;
};

export type StreamEvent =
  | { event: "sources"; data: { sources: Source[]; standalone_question: string } }
  | { event: "token"; data: string }
  | { event: "done"; data: DonePayload }
  | { event: "error"; data: { detail: string } };

export type QueryBody = {
  question: string;
  top_k: number;
  session_id?: string;
};

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function readDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    return `Request failed (${res.status})`;
  }
  return `Request failed (${res.status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new ApiError(res.status, await readDetail(res));
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const createSession = () => request<{ session_id: string }>("/sessions", { method: "POST" });
export const listSessions = () => request<SessionSummary[]>("/sessions?limit=30");
export const getSession = (id: string) => request<SessionDetail>(`/sessions/${id}`);
export const sendFeedback = (messageId: number, rating: -1 | 1) =>
  request(`/messages/${messageId}/feedback`, json({ rating }));

export async function uploadDocument(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return request("/documents/upload", { method: "POST", body: form });
}

export const getJob = (id: string) => request<JobStatus>(`/jobs/${id}`);
export type DocumentSource = "upload" | "corpus";
export const listDocuments = (limit: number, offset: number, source: DocumentSource) =>
  request<DocumentList>(`/documents?limit=${limit}&offset=${offset}&source=${source}`);
export const deleteDocument = (id: string) => request(`/documents/${id}`, { method: "DELETE" });

function parseBlock(block: string): StreamEvent | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }
  if (!event || dataLines.length === 0) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) } as StreamEvent;
}

export async function* streamQuery(body: QueryBody, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API_BASE}/query/stream`, { ...json(body), signal });
  if (!res.ok || !res.body) throw new ApiError(res.status, await readDetail(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const parsed = parseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (parsed) yield parsed;
      boundary = buffer.indexOf("\n\n");
    }
  }
}

export type SyncRunSummary = {
  id: number;
  status: "running" | "done" | "failed";
  pulled: boolean;
  commit_before: string | null;
  commit_after: string | null;
  added: number | null;
  changed: number | null;
  removed: number | null;
  unchanged: number | null;
  error_count: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type RetrievalRun = {
  label: string;
  created_at: string;
  mode: string | null;
  collection: string | null;
  embedding_model: string | null;
  questions: number;
  hit_at_1: number;
  hit_at_5: number;
  hit_at_10: number;
  mrr: number;
};

export type AnswerRun = {
  label: string;
  created_at: string;
  model: string | null;
  quantization: string | null;
  prompt: string | null;
  cites_a_source: number;
  cites_expected_file: number;
  refuses_off_topic: number;
  flagged: number;
  avg_seconds: number;
};

export type DashboardData = {
  generated_at: string;
  service: {
    started_at: string;
    uptime_seconds: number;
    provider: string;
    model: string;
    quantization: string | null;
    prompt_variant: string;
    retrieval_mode: string;
    embedding_model: string;
    collection: string;
    chunks_in_index: number | null;
    keyword_index_chunks: number | null;
    gpu: { name: string; memory_used_mb: number; memory_total_mb: number } | null;
    python_version: string;
    torch_version: string;
  };
  corpus: {
    path: string;
    commit: string | null;
    commit_subject: string | null;
    files_tracked: number;
    chunks_tracked: number;
    uploaded_files: number;
    sync_runs: SyncRunSummary[];
  };
  usage: {
    queries: number;
    avg_retrieval_ms: number;
    avg_generation_ms: number;
    p95_total_ms: number;
    flagged: number;
    checked: number;
    sessions: number;
    feedback_up: number;
    feedback_down: number;
    feedback_positive_ratio: number | null;
    queries_per_day: { day: string; queries: number }[];
  };
  recent_queries: {
    message_id: number | null;
    verified_answer_id: number | null;
    created_at: string;
    question: string;
    model: string;
    retrieval_ms: number;
    generation_ms: number;
    needs_review: boolean | null;
  }[];
  verified: { pending: number; approved: number; stale: number; rejected: number; served: number };
  uploads: { filename: string; status: string; error: string | null; created_at: string; finished_at: string | null }[];
  retrieval_runs: RetrievalRun[];
  answer_runs: AnswerRun[];
  plan: { phase: string; title: string; status: string; state: "done" | "partial" | "todo" }[];
  commits: { hash: string; date: string; subject: string }[];
};

export const getDashboard = () => request<DashboardData>("/admin/dashboard");

export type VerifiedStatus = "pending" | "approved" | "stale" | "rejected";

export type VerifiedAnswer = {
  id: number;
  question: string;
  answer: string;
  sources: Source[];
  status: VerifiedStatus;
  origin: string;
  stale_reason: string | null;
  times_served: number;
  created_at: string;
  reviewed_at: string | null;
  last_served_at: string | null;
};

export type VerifiedList = { total: number; counts: Record<VerifiedStatus, number>; items: VerifiedAnswer[] };

export const listVerified = (status: VerifiedStatus) =>
  request<VerifiedList>(`/admin/verified?status=${status}&limit=100`);
export const approveVerified = (id: number, answer?: string) =>
  request<VerifiedAnswer>(`/admin/verified/${id}/approve`, json(answer ? { answer } : {}));
export const rejectVerified = (id: number) => request<VerifiedAnswer>(`/admin/verified/${id}/reject`, { method: "POST" });
export const deleteVerified = (id: number) => request(`/admin/verified/${id}`, { method: "DELETE" });
export const queueDrafts = (questions: string[]) => request<{ queued: number }>("/admin/verified/drafts", json({ questions }));
export const getSeedQuestions = () => request<string[]>("/admin/verified/seeds");
export const promoteMessage = (messageId: number) =>
  request<{ id: number }>(`/admin/verified/from-message/${messageId}`, { method: "POST" });

export async function adminSignIn(key: string): Promise<void> {
  const res = await fetch("/api/admin-session", json({ key }));
  if (!res.ok) throw new ApiError(res.status, await readDetail(res));
}

export async function adminSignOut(): Promise<void> {
  await fetch("/api/admin-session", { method: "DELETE" });
}
