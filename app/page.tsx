"use client";

import { useEffect, useState } from "react";

type TaskResult = {
  task_id: string;
  title: string;
  activity: string;
  change_type: string;
  original_window: { start_time: string; end_time: string };
  proposed_window: { start_time: string; end_time: string } | null;
  reasons: string[];
};

type ScheduleResult = {
  plan_id: string;
  overall_status: string;
  summary: {
    total_tasks: number;
    unchanged_count: number;
    rescheduled_count: number;
    unfeasible_count: number;
  };
  tasks: TaskResult[];
};

function formatTime(value: string) {
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function Home() {
  const [result, setResult] = useState<ScheduleResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/schedule")
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Unable to calculate schedule");
        return data as ScheduleResult;
      })
      .then(setResult)
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "Unable to calculate schedule"),
      );
  }, []);

  return (
    <main className="min-h-screen bg-[#f7f9f5] px-6 py-12 text-[#183126] md:px-12">
      <div className="mx-auto max-w-5xl">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-[#d47c30]">
          PlanSafe India
        </p>
        <h1 className="mt-3 text-4xl font-bold tracking-tight">Weather-aware schedule proposal</h1>
        <p className="mt-3 text-[#62766b]">
          This page calls the Python scheduling engine through <code>/api/schedule</code>.
        </p>

        {error && (
          <div className="mt-8 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800">
            {error}
          </div>
        )}
        {!result && !error && <p className="mt-8 text-[#62766b]">Calculating proposal...</p>}

        {result && (
          <>
            <section className="mt-8 grid gap-4 md:grid-cols-4">
              <div className="rounded-xl bg-[#176b45] p-5 text-white">
                <p className="text-sm text-white/70">Status</p>
                <p className="mt-2 text-2xl font-bold">{result.overall_status}</p>
              </div>
              <div className="rounded-xl bg-white p-5 shadow-sm">
                <p className="text-sm text-[#62766b]">Total tasks</p>
                <p className="mt-2 text-2xl font-bold">{result.summary.total_tasks}</p>
              </div>
              <div className="rounded-xl bg-white p-5 shadow-sm">
                <p className="text-sm text-[#62766b]">Rescheduled</p>
                <p className="mt-2 text-2xl font-bold">{result.summary.rescheduled_count}</p>
              </div>
              <div className="rounded-xl bg-white p-5 shadow-sm">
                <p className="text-sm text-[#62766b]">Unchanged</p>
                <p className="mt-2 text-2xl font-bold">{result.summary.unchanged_count}</p>
              </div>
            </section>

            <section className="mt-8 rounded-xl bg-white p-6 shadow-sm">
              <p className="text-sm text-[#62766b]">Plan ID</p>
              <p className="mt-1 font-mono text-sm">{result.plan_id}</p>
              <div className="mt-6 space-y-4">
                {result.tasks.map((task) => (
                  <article key={task.task_id} className="rounded-lg border border-[#dfe8df] p-5">
                    <div className="flex flex-col justify-between gap-3 md:flex-row">
                      <div>
                        <h2 className="font-bold">{task.title}</h2>
                        <p className="mt-1 text-sm text-[#718278]">{task.activity} · {task.task_id}</p>
                      </div>
                      <span className="h-fit rounded-full bg-[#e6f4eb] px-3 py-1 text-xs font-bold text-[#176b45]">
                        {task.change_type}
                      </span>
                    </div>
                    <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
                      <div>
                        <p className="text-[#718278]">Original window</p>
                        <p className="font-medium">{formatTime(task.original_window.start_time)} – {formatTime(task.original_window.end_time)}</p>
                      </div>
                      <div>
                        <p className="text-[#718278]">Proposed window</p>
                        <p className="font-medium">
                          {task.proposed_window
                            ? `${formatTime(task.proposed_window.start_time)} – ${formatTime(task.proposed_window.end_time)}`
                            : "No change required"}
                        </p>
                      </div>
                    </div>
                    <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-[#62766b]">
                      {task.reasons.map((reason) => <li key={reason}>{reason}</li>)}
                    </ul>
                  </article>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}
