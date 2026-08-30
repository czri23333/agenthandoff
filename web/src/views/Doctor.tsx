import { useEffect, useState } from "react";
import { api, type StoreInfo } from "../api";

export default function Doctor() {
  const [stores, setStores] = useState<StoreInfo[] | null>(null);

  useEffect(() => {
    api.stores().then(setStores);
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-zinc-800/70 px-5 py-2.5">
        <p className="text-[12px] text-zinc-500">which CLI session stores exist on this machine, and are they readable</p>
        <button onClick={() => api.stores().then(setStores)} className="ml-auto rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700">
          re-probe
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {stores === null && <p className="text-[13px] text-zinc-600">probing…</p>}
        <ul className="space-y-1.5">
          {stores?.map((s) => (
            <li key={`${s.cli}:${s.path}`} className="flex items-center gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3 py-2">
              <span className={`inline-block h-2 w-2 rounded-full ${s.readable ? "bg-emerald-400" : "bg-zinc-600"}`} />
              <span className="w-28 font-mono text-[12px] text-zinc-300">{s.cli}</span>
              {s.via_wsl && <span className="rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-px font-mono text-[10px] text-violet-300">wsl</span>}
              <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-zinc-600" title={s.path}>{s.path}</span>
              <span className="text-[11px] text-zinc-500">{s.detail}</span>
            </li>
          ))}
        </ul>
        {stores?.length === 0 && <p className="text-[13px] text-zinc-600">no known CLI stores found on this machine.</p>}
      </div>
    </div>
  );
}
