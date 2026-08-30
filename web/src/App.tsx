import { useEffect, useState } from "react";
import Dashboard from "./views/Dashboard";
import SessionDetail from "./views/SessionDetail";
import Threads from "./views/Threads";
import Inbox from "./views/Inbox";
import Doctor from "./views/Doctor";

type View = { name: "dashboard" } | { name: "detail"; cli: string; sid: string } | { name: "threads" } | { name: "inbox" } | { name: "doctor" };

const TABS: { id: View["name"]; label: string; key: string }[] = [
  { id: "dashboard", label: "Sessions", key: "1" },
  { id: "threads", label: "Threads", key: "2" },
  { id: "inbox", label: "Inbox", key: "3" },
  { id: "doctor", label: "Doctor", key: "4" },
];

export default function App() {
  const [view, setView] = useState<View>({ name: "dashboard" });

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
    <div className="mx-auto flex h-screen max-w-[1400px] flex-col">
      <header className="flex items-center gap-6 border-b border-zinc-800 px-5 py-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[15px] font-semibold tracking-tight text-zinc-100">agenthandoff</span>
          <span className="text-[11px] text-zinc-500">cockpit</span>
        </div>
        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setView({ name: t.id } as View)}
              className={`rounded-md px-3 py-1.5 text-[13px] transition-colors ${
                view.name === t.id || (view.name === "detail" && t.id === "dashboard")
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
              }`}
            >
              {t.label} <span className="ml-0.5 text-[9px] text-zinc-600">{t.key}</span>
            </button>
          ))}
        </nav>
        <div className="ml-auto text-[11px] text-zinc-600">127.0.0.1 · local only</div>
      </header>

      <main className="min-h-0 flex-1 overflow-hidden">
        {view.name === "dashboard" && <Dashboard onOpen={(cli, sid) => setView({ name: "detail", cli, sid })} />}
        {view.name === "detail" && <SessionDetail cli={view.cli} sid={view.sid} onBack={() => setView({ name: "dashboard" })} />}
        {view.name === "threads" && <Threads />}
        {view.name === "inbox" && <Inbox />}
        {view.name === "doctor" && <Doctor />}
      </main>
    </div>
  );
}
