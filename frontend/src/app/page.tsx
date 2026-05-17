"use client";

import { useState } from "react";

type Source = {
  id: string;
  path: string | null;
  language: string | null;
  title: string | null;
  distance: number | null;
  preview: string | null;
};

type QueryResponse = {
  question: string;
  answer: string;
  sources: Source[];
  top_k: number;
  model: string;
};

export default function Home() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function askSentinel() {
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const res = await fetch("http://127.0.0.1:8000/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question,
          top_k: 3,
        }),
      });

      if (!res.ok) {
        throw new Error(`API error: ${res.status}`);
      }

      const data: QueryResponse = await res.json();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-4xl font-bold">Sentinel</h1>
        <p className="mt-2 text-zinc-400">
          AI assistant for the Apache Superset codebase.
        </p>

        <div className="mt-8 rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
          <textarea
            className="min-h-32 w-full rounded-xl border border-zinc-700 bg-zinc-950 p-4 text-zinc-100 outline-none"
            placeholder="Ask about Apache Superset..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />

          <button
           type="button"
           onClick={() => {
             console.log("Ask button clicked");
             askSentinel();
           }}
           disabled={loading || question.trim().length < 3}
           className="mt-4 cursor-pointer rounded-xl bg-white px-5 py-2 font-medium text-zinc-950 disabled:cursor-not-allowed disabled:opacity-50"
         >
           {loading ? "Thinking..." : "Ask Sentinel"}
         </button>
        </div>

        {result && (
          <div className="mt-8 space-y-6">
            <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
              <h2 className="text-xl font-semibold">Answer</h2>
              <pre className="mt-4 whitespace-pre-wrap text-sm leading-7 text-zinc-200">
                {result.answer}
              </pre>
            </section>

            <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
              <h2 className="text-xl font-semibold">Sources</h2>

              <div className="mt-4 space-y-4">
                {result.sources.map((source) => (
                  <div
                    key={source.id}
                    className="rounded-xl border border-zinc-800 bg-zinc-950 p-4"
                  >
                    <div className="font-medium">
                      {source.id}: {source.title}
                    </div>
                    <div className="mt-1 text-xs text-zinc-500">
                      {source.language} · distance:{" "}
                      {source.distance?.toFixed(4)}
                    </div>
                    <div className="mt-2 break-all text-xs text-zinc-400">
                      {source.path}
                    </div>
                    <p className="mt-3 text-sm text-zinc-300">
                      {source.preview}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          </div>
        )}
      </div>
    </main>
  );
}