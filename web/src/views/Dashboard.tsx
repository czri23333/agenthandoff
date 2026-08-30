import { useEffect, useMemo, useState } from "react";
import { api, relTime, type SessionMeta, type StoreInfo } from "../api";
import { CliBadge, StatusDot } from "../components";

export default function Dashboard({ onOpen }: { onOpen: (cli: string, sid: string) => void }) {
  const [sessions, setSessions] = useState<SessionMeta[] | null>(null);
  const [stores, setStores] = useState<StoreInfo[]>([]);
  const [cliFilter, setCliFilter] = useState("");
  const [cwdFilter, setCwdFilter] = useState("");
  const [q, setQ] = useState("");

  const load = async () => {
    const [s, st] = await Promise.all([
      api.sessions({ cli: cliFilter || undefined, cwd: cwdFilter || undefined, q: q || undefined }),
      api.stores(),
    ]);
    // Only re-render when data actually changed — a steady DOM keeps scroll
    // position and hover state stable between polls.
    setSessions((prev) => (JSON.stringify(prev) === JSON.stringify(s) ? prev : s));
    setStores((prev) => (JSON.stringify(prev) === JSON.stringify(st) ? prev : st));
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000); // stores change slowly; see ADR-006
    return () => clearInterval(t);
  }, [cliFilter, cwdFilter, q]);

  const cliOptions = useMemo(() => [...new Set(stores.map((s) => s.cli))], [stores]);
  const unreadable = stores.filter((s) => !s.readable).length;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800/70 px-5 py-2.5">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="search titles…"
          className="w-64 rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-[13px] outline-none placeholder:text-zinc-600 focus:border-zinc-600"
        />
        <input
          value={cwdFilter}
          onChange={(e) => setCwdFilter(e.target.value)}
          placeholder="filter by cwd…"
          className="w-56 rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-[13px] outline-none placeholder:text-zinc-600 focus:border-zinc-600"
        />
        <select
          value={cliFilter}
          onChange={(e) => setCliFilter(e.target.value)}
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-[13px] outline-none focus:border-zinc-600"
        >
          <option value="">all CLIs</option>
          {cliOptions.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-3">
          {unreadable > 0 && <span className="text-[11px] text-yellow-500/80">{unreadable} store(s) unreadable</span>}
          <span className="text-[11px] text-zinc-600">{sessions?.length ?? "…"} sessions</span>
          <button onClick={load} className="rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700">
            refresh
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {sessions === null && <p className="text-[13px] text-zinc-600">loading…</p>}
        {sessions?.length === 0 && (
          <p className="text-[13px] text-zinc-600">no sessions match. Run some AI CLIs, then refresh.</p>
        )}
        <ul className="space-y-1.5">
          {sessions?.map((s) => (
            <li key={`${s.cli}:${s.session_id}`}>
              <button
                onClick={() => onOpen(s.cli, s.session_id)}
                className="group flex w-full items-center gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3 py-2 text-left hover:border-zinc-600 hover:bg-zinc-900"
              >
                <CliBadge cli={s.cli} origin={s.origin} />
                <span className="min-w-0 flex-1 truncate text-[13px] text-zinc-200 group-hover:text-white">{s.title}</span>
                {s.parent_session_id && (
                  <span className="hidden shrink-0 font-mono text-[10px] text-zinc-600 xl:inline" title={`child of ${s.parent_session_id}`}>
                    ⤷ child
                  </span>
                )}
                <span className="shrink-0 font-mono text-[11px] text-zinc-600" title={s.cwd}>
                  {s.cwd.split(/[\\/]/).filter(Boolean).slice(-1)[0] || s.cwd}
                </span>
                <span className="w-16 shrink-0 text-right font-mono text-[11px] text-zinc-500">{relTime(s.updated_at)}</span>
                {s.status ? <StatusDot kind={s.status} /> : <span className="w-2 shrink-0" title="unknown end-state" />}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
