import { useEffect, useState } from "react";
import { api, type InboxItem } from "../api";
import { CliBadge, CopyButton } from "../components";

export default function Inbox() {
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [globalScope, setGlobalScope] = useState(false);
  const [msg, setMsg] = useState("");

  const load = async () => setItems(await api.inbox(globalScope));
  useEffect(() => {
    load();
  }, [globalScope]);

  const claim = async (path: string) => {
    try {
      await api.claim(path);
      await load();
    } catch (e) {
      setMsg(String(e));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-zinc-800/70 px-5 py-2.5">
        <p className="text-[12px] text-zinc-500">published handoffs waiting for pickup — files are the API, git is the bus</p>
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-zinc-500">
          <input type="checkbox" checked={globalScope} onChange={(e) => setGlobalScope(e.target.checked)} />
          ~/.agenthandoff (global)
        </label>
        <button onClick={load} className="rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700">refresh</button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {msg && <p className="mb-2 text-[12px] text-red-400">{msg}</p>}
        {items === null && <p className="text-[13px] text-zinc-600">loading…</p>}
        {items?.length === 0 && (
          <p className="text-[13px] text-zinc-600">
            inbox empty. Publish from a session detail page, or <code className="text-zinc-500">handoff publish &lt;bundle&gt;</code>.
          </p>
        )}
        <ul className="space-y-1.5">
          {items?.map((it) => (
            <li key={it.path} className="flex items-center gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3 py-2">
              <CliBadge cli={it.cli} />
              <span className="min-w-0 flex-1 truncate text-[13px] text-zinc-200">{it.title}</span>
              <span className="font-mono text-[11px] text-zinc-600">{it.published_at}</span>
              {it.claimed ? (
                <span className="rounded border border-zinc-700 bg-zinc-800 px-1.5 py-px font-mono text-[10px] text-zinc-400">claimed · {it.claimed_by}</span>
              ) : (
                <button onClick={() => claim(it.path)} className="rounded-md border border-emerald-700/50 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/20">
                  claim
                </button>
              )}
              <CopyButton text={it.path} label="path" />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
