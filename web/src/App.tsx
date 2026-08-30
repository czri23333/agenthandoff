import { useEffect, useRef, useState } from "react";
import { Layout, Menu, Segmented, Typography } from "antd";
import { setAppLang, useT, type Lang } from "./i18n";
import Dashboard from "./views/Dashboard";
import SessionDetail from "./views/SessionDetail";
import Threads from "./views/Threads";
import Inbox from "./views/Inbox";
import Doctor from "./views/Doctor";

// Hash routing: every view and session is a shareable, bookmarkable URL.
type View =
  | { name: "dashboard" }
  | { name: "detail"; cli: string; sid: string }
  | { name: "threads" }
  | { name: "inbox" }
  | { name: "doctor" };

const TABS: { id: View["name"]; key: string; labelKey: Parameters<ReturnType<typeof useT>>[0]; hash: string }[] = [
  { id: "dashboard", key: "1", labelKey: "sessions", hash: "" },
  { id: "threads", key: "2", labelKey: "threads", hash: "threads" },
  { id: "inbox", key: "3", labelKey: "inbox", hash: "inbox" },
  { id: "doctor", key: "4", labelKey: "doctor", hash: "doctor" },
];

function parseHash(): View {
  const parts = location.hash.replace(/^#/, "").split("/").filter(Boolean);
  if (parts[0] === "session" && parts[1] && parts[2])
    return { name: "detail", cli: decodeURIComponent(parts[1]), sid: decodeURIComponent(parts[2]) };
  if (parts[0] === "threads") return { name: "threads" };
  if (parts[0] === "inbox") return { name: "inbox" };
  if (parts[0] === "doctor") return { name: "doctor" };
  return { name: "dashboard" };
}

function toHash(v: View): string {
  if (v.name === "detail")
    return `#/session/${encodeURIComponent(v.cli)}/${encodeURIComponent(v.sid)}`;
  return v.name === "dashboard" ? "#/" : `#${v.name}`;
}

export default function App() {
  const t = useT();
  const [view, setView] = useState<View>(parseHash);
  const [lang, setLangState] = useState<Lang>(
    () => (localStorage.getItem("ah-lang") as Lang) || "zh",
  );
  const navDepth = useRef(0);

  const setLang = (l: Lang) => {
    setLangState(l);
    setAppLang(l);
  };

  const navigate = (v: View) => {
    navDepth.current += 1;
    setView(v);
    history.pushState(null, "", toHash(v));
  };

  const goBack = () => {
    if (navDepth.current > 0) {
      navDepth.current -= 1;
      history.back();
    } else {
      navigate({ name: "dashboard" });
    }
  };

  useEffect(() => {
    const sync = () => {
      navDepth.current = Math.max(0, navDepth.current - 1);
      setView(parseHash());
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("hashchange", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("hashchange", sync);
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return;
      const tab = TABS.find((tb) => tb.key === e.key);
      if (tab) navigate({ name: tab.id } as View);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <Layout className="mx-auto h-screen max-w-[1400px] bg-zinc-950">
      <Layout.Header className="flex items-center gap-5 border-b border-zinc-800 px-5!">
        <Typography.Title level={5} style={{ margin: 0 }}>
          agenthandoff <span className="text-[11px] font-normal text-zinc-500">cockpit</span>
        </Typography.Title>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[view.name === "detail" ? "dashboard" : view.name]}
          onClick={(e) => navigate({ name: e.key } as View)}
          items={TABS.map((tb) => ({
            key: tb.id,
            label: `${t(tb.labelKey)} ${tb.key}`,
          }))}
          style={{ flex: 1, minWidth: 300, borderBottom: "none" }}
        />
        <Segmented
          value={lang}
          onChange={(v) => setLang(v as Lang)}
          options={[
            { label: "中", value: "zh" },
            { label: "EN", value: "en" },
          ]}
        />
        <Typography.Text type="secondary" className="text-[11px]">127.0.0.1</Typography.Text>
      </Layout.Header>

      <Layout.Content className="min-h-0 flex-1 overflow-hidden" key={view.name + (view.name === "detail" ? view.sid : "")}>
        <div className="view-enter h-full">
          {view.name === "dashboard" && <Dashboard onOpen={(cli, sid) => navigate({ name: "detail", cli, sid })} />}
          {view.name === "detail" && <SessionDetail cli={view.cli} sid={view.sid} onBack={goBack} />}
          {view.name === "threads" && <Threads />}
          {view.name === "inbox" && <Inbox />}
          {view.name === "doctor" && <Doctor />}
        </div>
      </Layout.Content>
    </Layout>
  );
}
