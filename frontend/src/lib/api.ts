export type Source = {
  id: string;
  path: string | null;
  language: string | null;
  title: string | null;
  distance: number | null;
  score: number | null;
  preview: string | null;
};

export type ChatMessage = {
  key: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[] | null;
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
export const listDocuments = (limit: number, offset: number) =>
  request<DocumentList>(`/documents?limit=${limit}&offset=${offset}`);
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
