"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const AGENT_ID = "echo";

type Quota = { calls_used: number; calls_limit: number };
type Status = "idle" | "running" | "done";

export default function Home() {
  const [question, setQuestion] = useState("");
  const [output, setOutput] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [notice, setNotice] = useState<string | null>(null);
  const [quota, setQuota] = useState<Quota | null>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const source = useRef<EventSource | null>(null);

  const refreshQuota = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND}/rate-limit/status?agent_id=${AGENT_ID}`);
      setQuota(await res.json());
      setReachable(true);
    } catch {
      setReachable(false);
    }
  }, []);

  useEffect(() => {
    refreshQuota();
    return () => source.current?.close();
  }, [refreshQuota]);

  async function run() {
    setStatus("running");
    setOutput("");
    setNotice(null);

    let runId: string;
    try {
      const res = await fetch(`${BACKEND}/agents/${AGENT_ID}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: { question } }),
      });
      const body = await res.json();
      if (!res.ok) {
        // The backend already phrased this for a human, including the 429 case.
        setNotice(body.message ?? "The agent could not start.");
        setStatus("idle");
        refreshQuota();
        return;
      }
      runId = body.run_id;
      setReachable(true);
    } catch {
      setReachable(false);
      setStatus("idle");
      return;
    }

    const stream = new EventSource(`${BACKEND}/agents/${AGENT_ID}/stream/${runId}`);
    source.current = stream;

    stream.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "partial_output") setOutput((prior) => prior + data.text);
      if (data.type === "error") setNotice(data.message);
      if (data.type === "run_complete" || data.type === "error") {
        stream.close();
        setStatus("done");
        refreshQuota();
      }
    };
    stream.onerror = () => {
      stream.close();
      setStatus("done");
      setNotice((prior) => prior ?? "The connection to the agent dropped.");
    };
  }

  const remaining = quota ? Math.max(0, quota.calls_limit - quota.calls_used) : null;
  const busy = status === "running";

  return (
    <main className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Agentic Patterns Lab</h1>
        <p className="text-neutral-400">
          Phase 1: one echo agent, proving the path from browser to rate limiter to
          model gateway and back as a live stream.
        </p>
      </header>

      {reachable === false && (
        <p className="rounded border border-amber-800 bg-amber-950/40 px-4 py-3 text-amber-200">
          The backend is waking up or unavailable. Give it a moment and try again.
        </p>
      )}

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <label htmlFor="question" className="font-medium">
            Ask the echo agent
          </label>
          {remaining !== null && (
            <span className="text-sm text-neutral-400">{remaining} calls remaining today</span>
          )}
        </div>

        <textarea
          id="question"
          rows={3}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={2000}
          placeholder="What is a directed graph, in one paragraph?"
          className="w-full rounded border border-neutral-800 bg-neutral-900 px-4 py-3 outline-none focus:border-neutral-600"
        />

        <button
          onClick={run}
          disabled={busy || !question.trim()}
          className="rounded bg-neutral-100 px-4 py-2 font-medium text-neutral-900 disabled:opacity-40"
        >
          {busy ? "Running..." : "Run agent"}
        </button>

        {notice && (
          <p className="rounded border border-red-900 bg-red-950/40 px-4 py-3 text-red-200">{notice}</p>
        )}
      </section>

      {(output || busy) && (
        <section className="space-y-2">
          <h2 className="font-medium">Output</h2>
          <pre className="whitespace-pre-wrap rounded border border-neutral-800 bg-neutral-900 px-4 py-3 font-sans">
            {output || "Starting..."}
          </pre>
        </section>
      )}
    </main>
  );
}
