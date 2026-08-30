import { useEffect, useState } from "react";
import { api, type ThreadGroup } from "../api";

export default function Threads() {
  const [threads, setThreads] = useState<ThreadGroup[] | null>(null);
  const [minOverlap, setMinOverlap] = useState(0.15);

  const load = async () => {
    setThreads(await api.threads());
  };
  useEffect(() => {
    load();
  }, []);

  const recluster = async () => {
    setThreads(null);
    // threshold passed through a query re-run
    const all = await fetch(`/api/threads?min_overlap=${minOverlap}`).then((r) => r.json());
    setThreads(all);
  };

  // Standalone sessions (no links) are noise in this view — collapse them.
  const multi = threads?.filter((t) => t.session_ids.length > 1) ?? null;
  const singleCount = (threads?.length ?? 0) - (multi?.length ?? 0);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-zinc-800/70 px-5 py-2.5">
        <p className="text-[12px] text-zinc-500">sessions that are actually one job — lineage + file overlap + title tokens, within a time window</p>
        <div className="ml-auto flex items-center gap-2">
          <label className="text-[11px] text-zinc-500">min overlap {minOverlap.toFixed(2)}</label>
          <input type="range" min={0.05} max={0.6} step={0.05} value={minOverlap} onChange={(e) => setMinOverlap(Number(e.target.value))} className="w-32" />
          <button onClick={recluster} className="rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700">recluster</button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {threads === null && <p className="text-[13px] text-zinc-600">clustering… (first run ~15s on a big machine, cached after)</p>}
        {multi?.length === 0 && <p className="text-[13px] text-zinc-600">no multi-session threads detected — every session looks standalone.</p>}
        {singleCount > 0 && (
          <p className="mb-3 text-[11px] text-zinc-600">{singleCount} standalone session(s) hidden — lower min overlap to link them.</p>
        )}
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {multi?.map((t, i) => (
            <section key={i} className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-3">
              <header className="mb-2 flex items-center gap-2">
                <span className="rounded bg-zinc-800 px-1.5 py-px font-mono text-[10px] text-zinc-400">{t.session_ids.length} sessions</span>
                <span className="font-mono text-[10px] text-zinc-600">{t.clis.join(" + ")}</span>
                <span className="ml-auto font-mono text-[10px] text-zinc-600">{t.last_active?.slice(0, 10)}</span>
              </header>
              <pre className="whitespace-pre-wrap font-mono text-[11px] leading-[1.7] text-zinc-400">{t.lines.slice(1).join("\n")}</pre>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
