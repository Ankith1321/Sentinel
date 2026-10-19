"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteDocument,
  getJob,
  listDocuments,
  uploadDocument,
  type DocumentList,
  type DocumentSource,
  type JobStatus,
} from "@/lib/api";

const ACCEPTED = ".py,.md,.mdx,.js,.jsx,.ts,.tsx,.txt,.pdf,.docx";
const PAGE_SIZE = 25;
const POLL_MS = 1500;

type Upload = {
  key: string;
  filename: string;
  status: JobStatus["status"] | "uploading" | "rejected";
  detail?: string;
};

const STATUS_LABEL: Record<Upload["status"], string> = {
  uploading: "Uploading",
  queued: "Queued",
  processing: "Processing",
  done: "Indexed",
  unchanged: "Already indexed, no change",
  failed: "Failed",
  rejected: "Rejected",
};

const isFinished = (status: Upload["status"]) =>
  status === "done" || status === "unchanged" || status === "failed" || status === "rejected";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function Documents() {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [documents, setDocuments] = useState<DocumentList>({ total: 0, items: [] });
  const [offset, setOffset] = useState(0);
  const [source, setSource] = useState<DocumentSource>("upload");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(() => {
    let cancelled = false;

    listDocuments(PAGE_SIZE, offset, source)
      .then((list) => {
        if (cancelled) return;
        setDocuments(list);
        setError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load documents");
      });

    return () => {
      cancelled = true;
    };
  }, [offset, reloadToken, source]);

  async function ingest(file: File) {
    const key = crypto.randomUUID();
    const update = (changes: Partial<Upload>) =>
      setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, ...changes } : u)));

    setUploads((prev) => [{ key, filename: file.name, status: "uploading" }, ...prev]);

    try {
      const { job_id } = await uploadDocument(file);
      let job = await getJob(job_id);
      update({ status: job.status });

      while (!isFinished(job.status)) {
        await wait(POLL_MS);
        job = await getJob(job_id);
        update({ status: job.status, detail: job.error ?? undefined });
      }
      update({ status: job.status, detail: job.error ?? undefined });
      refresh();
    } catch (err) {
      update({ status: "rejected", detail: err instanceof Error ? err.message : "Upload failed" });
    }
  }

  function addFiles(files: FileList | null) {
    if (!files) return;
    Array.from(files).forEach((file) => void ingest(file));
  }

  async function remove(id: string) {
    try {
      await deleteDocument(id);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete document");
    }
  }

  return (
    <div className="space-y-6">
      <section
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
        className={`rounded-2xl border border-dashed p-8 text-center ${
          dragging ? "border-zinc-300 bg-zinc-800" : "border-zinc-700 bg-zinc-900"
        }`}
      >
        <h2 className="text-xl font-semibold">Add documents to the index</h2>
        <p className="mt-2 text-sm text-zinc-400">
          Drop files here or choose them. Accepted: .py .md .mdx .js .ts .tsx .txt .pdf .docx, up to 10 MB each.
          Processing runs in the background and can take a while for large files.
        </p>
        <input
          ref={inputRef}
          id="file-input"
          type="file"
          multiple
          accept={ACCEPTED}
          className="sr-only"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="mt-4 cursor-pointer rounded-xl bg-white px-5 py-2 text-sm font-medium text-zinc-950"
        >
          Choose files
        </button>
      </section>

      {uploads.length > 0 && (
        <section aria-label="Uploads" className="space-y-2">
          {uploads.map((u) => (
            <div
              key={u.key}
              className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border p-3 text-sm ${
                u.status === "failed" || u.status === "rejected"
                  ? "border-red-900 bg-red-950/40 text-red-300"
                  : "border-zinc-800 bg-zinc-900 text-zinc-300"
              }`}
            >
              <span className="min-w-0 truncate">{u.filename}</span>
              <span className="text-xs">
                {STATUS_LABEL[u.status]}
                {u.detail ? `: ${u.detail}` : ""}
              </span>
            </div>
          ))}
        </section>
      )}

      {error && (
        <div role="alert" className="rounded-2xl border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-semibold">Indexed documents</h2>
          <div className="flex items-center gap-3">
            <div role="group" aria-label="Which documents" className="flex gap-1 rounded-xl bg-zinc-950 p-1 text-xs">
              {([
                ["upload", "Uploaded"],
                ["corpus", "Codebase"],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={source === value}
                  onClick={() => {
                    setSource(value);
                    setOffset(0);
                  }}
                  className="cursor-pointer rounded-lg px-3 py-1 text-zinc-400 aria-pressed:bg-zinc-800 aria-pressed:text-zinc-100"
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="text-xs text-zinc-500">{documents.total.toLocaleString()} total</span>
          </div>
        </div>
        {documents.items.length === 0 ? (
          <p className="mt-4 text-sm text-zinc-400">
            {source === "upload"
              ? "No uploads yet. Files you upload appear here with their chunk counts."
              : "The codebase manifest is empty. Run a full build or a sync to fill it."}
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-zinc-800">
            {documents.items.map((doc) => (
              <li key={doc.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
                <div className="min-w-0">
                  <div className="break-all font-mono text-xs text-zinc-200">{doc.path}</div>
                  <div className="mt-1 text-xs text-zinc-500">
                    {doc.language ?? doc.source_type} · {doc.chunk_count} chunks
                  </div>
                </div>
                {doc.source_type === "upload" && (
                  <button
                    type="button"
                    onClick={() => remove(doc.id)}
                    className="cursor-pointer rounded-lg border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:border-red-800 hover:text-red-300"
                  >
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {documents.total > PAGE_SIZE && (
          <div className="mt-4 flex justify-between text-xs">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="cursor-pointer rounded-lg border border-zinc-700 px-3 py-1 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= documents.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="cursor-pointer rounded-lg border border-zinc-700 px-3 py-1 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
