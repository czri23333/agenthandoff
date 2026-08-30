import { useEffect, useState } from "react";
import { api, type InboxItem } from "../api";
import { useT } from "../i18n";
import { CliBadge, CopyButton } from "../components";

export default function Inbox() {
  const t = useT();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [globalScope, setGlobalScope] = useState(false);
  const [msg, setMsg] = useState("");

  const load = async () => setItems(await api.inbox(globalScope));
  useEffect(() => {
    load();
  }, [globalScope]);

  const doClaim = async (path: string) => {
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
        <p className="text-[12px] text-zinc-500">{t("inboxDesc")}</p>
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-zinc-500">
          <input type="checkbox" checked={globalScope} onChange={(e) => setGlobalScope(e.target.checked)} />
          {t("global")}
        </label>
        <button onClick={load} className="rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700">{t("refresh")}</button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {msg && <p className="mb-2 text-[12px] text-red-400">{msg}</p>}
        {items === null && <p className="text-[13px] text-zinc-600">{t("loading")}</p>}
        {items?.length === 0 && (
          <p className="text-[13px] text-zinc-600">
            {t("inboxEmpty")} <code className="text-zinc-500">handoff publish &lt;bundle&gt;</code>.
          </p>
        )}
        <ul className="space-y-1.5">
          {items?.map((it) => (
            <li key={it.path} className="flex items-center gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3 py-2">
              <CliBadge cli={it.cli} />
              <span className="min-w-0 flex-1 truncate text-[13px] text-zinc-200">{it.title}</span>
              <span className="font-mono text-[11px] text-zinc-600">{it.published_at}</span>
              {it.claimed ? (
                <span className="rounded border border-zinc-700 bg-zinc-800 px-1.5 py-px font-mono text-[10px] text-zinc-400">{t("claimed")} · {it.claimed_by}</span>
              ) : (
                <button onClick={() => doClaim(it.path)} className="rounded-md border border-emerald-700/50 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/20">
                  {t("claim")}
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
