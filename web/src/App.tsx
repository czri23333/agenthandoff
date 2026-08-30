import { useEffect, useState } from "react";
import { LangContext, useT, type Lang, type TKey } from "./i18n";
import Dashboard from "./views/Dashboard";
import SessionDetail from "./views/SessionDetail";
import Threads from "./views/Threads";
import Inbox from "./views/Inbox";
import Doctor from "./views/Doctor";

type View = { name: "dashboard" } | { name: "detail"; cli: string; sid: string } | { name: "threads" } | { name: "inbox" } | { name: "doctor" };

const TABS: { id: View["name"]; key: string; labelKey: TKey }[] = [
  { id: "dashboard", key: "1", labelKey: "sessions" },
  { id: "threads", key: "2", labelKey: "threads" },
  { id: "inbox", key: "3", labelKey: "inbox" },
  { id: "doctor", key: "4", labelKey: "doctor" },
];

export default function App() {
  const t = useT();
  const [view, setView] = useState<View>({ name: "dashboard" });
  const [lang, setLang] = useState<Lang>(
    () => (localStorage.getItem("ah-lang") as Lang) || "zh",
  );
  useEffect(() => {
    localStorage.setItem("ah-lang", lang);
  }, [lang]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return;
      const tab = TABS.find((t) => t.key === e.key);
      if (tab) setView({ name: tab.id } as View);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <LangContext.Provider value={lang}>
    <div className="mx-auto flex h-screen max-w-[1400px] flex-col">
      <header className="flex items-center gap-6 border-b border-zinc-800 px-5 py-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[15px] font-semibold tracking-tight text-zinc-100">agenthandoff</span>
          <span className="text-[11px] text-zinc-500">cockpit</span>
        </div>
        <nav className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setView({ name: tab.id } as View)}
              className={`rounded-md px-3 py-1.5 text-[13px] transition-colors ${
                view.name === tab.id || (view.name === "detail" && tab.id === "dashboard")
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
              }`}
            >
              {t(tab.labelKey)} <span className="ml-0.5 text-[9px] text-zinc-600">{tab.key}</span>
            </button>
          ))}
        </nav>
        {/* Language segmented control: one block, two cells, the active one
            gets a brighter inset chip. */}
        <div className="ml-auto flex rounded-lg border border-zinc-700 bg-zinc-900 p-0.5">
          {(["zh", "en"] as Lang[]).map((l) => (
            <button
              key={l}
              onClick={() => setLang(l)}
              className={`rounded-md px-2.5 py-1 text-[11px] transition-all ${
                lang === l
                  ? "bg-zinc-600 text-zinc-50 shadow-inner ring-1 ring-zinc-500/40"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {l === "zh" ? "中" : "EN"}
            </button>
          ))}
        </div>
        <div className="text-[11px] text-zinc-600">127.0.0.1 · {t("localOnly").split("·").pop()?.trim()}</div>
      </header>

      <main className="min-h-0 flex-1 overflow-hidden" key={view.name + (view.name === "detail" ? view.sid : "")}>
        <div className="view-enter h-full">
          {view.name === "dashboard" && <Dashboard onOpen={(cli, sid) => setView({ name: "detail", cli, sid })} />}
          {view.name === "detail" && <SessionDetail cli={view.cli} sid={view.sid} onBack={() => setView({ name: "dashboard" })} />}
          {view.name === "threads" && <Threads />}
          {view.name === "inbox" && <Inbox />}
          {view.name === "doctor" && <Doctor />}
        </div>
      </main>
    </div>
    </LangContext.Provider>
  );
}
