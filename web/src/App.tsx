import { useEffect, useRef, useState } from "react";
import { Layout, Segmented, Tooltip, Typography } from "antd";
import { getLang, setAppLang, useT, type Lang } from "./i18n";
import { setThemeMode, useTheme, type ThemeMode } from "./theme";
import Dashboard from "./views/Dashboard";
import SessionDetail from "./views/SessionDetail";
import Threads from "./views/Threads";
import Inbox from "./views/Inbox";
import Doctor from "./views/Doctor";

// Hash routing: every view and session is a shareable, bookmarkable URL — also
// the reason keyboard/automation can reach any screen without clicking.
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

const THEME_ORDER: ThemeMode[] = ["auto", "dark", "light"];

export function parseHash(): View {
  const parts = location.hash.replace(/^#/, "").split("/").filter(Boolean);
  if (parts[0] === "session" && parts[1] && parts[2])
    return { name: "detail", cli: decodeURIComponent(parts[1]), sid: decodeURIComponent(parts[2]) };
  if (parts[0] === "threads") return { name: "threads" };
  if (parts[0] === "inbox") return { name: "inbox" };
  if (parts[0] === "doctor") return { name: "doctor" };
  return { name: "dashboard" };
}

function toHash(v: View): string {
  if (v.name === "detail") return `#/session/${encodeURIComponent(v.cli)}/${encodeURIComponent(v.sid)}`;
  return v.name === "dashboard" ? "#/" : `#${v.name}`;
}

export default function App() {
  const t = useT();
  const { mode } = useTheme();
  const [view, setView] = useState<View>(parseHash);
  const [lang, setLangState] = useState<Lang>(getLang);
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

  /** Switch by tab key ("dashboard" | "threads" | …) — used by clicks and 1-4. */
  const goTo = (id: string) => {
    const tab = TABS.find((tb) => tb.id === id);
    if (tab) navigate({ name: tab.id } as View);
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

  // Keyboard: 1-4 views, T theme, / search. Skipped while a field has focus so
  // typing a query never navigates away.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing =
        el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el?.isContentEditable;
      if (e.key === "Escape" && typing) {
        (el as HTMLInputElement).blur();
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      const tab = TABS.find((tb) => tb.key === e.key);
      if (tab) {
        goTo(tab.id);
        return;
      }
      if (e.key === "t" || e.key === "T") {
        const next = THEME_ORDER[(THEME_ORDER.indexOf(mode) + 1) % THEME_ORDER.length];
        setThemeMode(next);
        return;
      }
      if (e.key === "/") {
        if (view.name !== "dashboard") navigate({ name: "dashboard" });
        // Dashboard owns the input; ask it to focus on the next frame.
        requestAnimationFrame(() => window.dispatchEvent(new Event("ah-focus-search")));
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, view.name]);

  return (
    <Layout className="mx-auto h-screen max-w-[1500px]">
      <Layout.Header className="!flex !items-center gap-4 !px-5" style={{ borderBottom: "1px solid var(--ah-line)" }}>
        <Typography.Title level={5} style={{ margin: 0, whiteSpace: "nowrap" }}>
          agenthandoff{" "}
          <span className="ah-label" style={{ textTransform: "none", letterSpacing: 0 }}>
            cockpit
          </span>
        </Typography.Title>
        {/* A Segmented control instead of antd's horizontal Menu: the Menu's
            selected item paints its own container colour and measured 3.66:1 on
            our header surface, while Segmented inherits the token palette. */}
        <Segmented
          className="min-w-0 flex-1"
          value={view.name === "detail" ? "dashboard" : view.name}
          onChange={(v) => goTo(String(v))}
          options={TABS.map((tb) => ({ label: `${t(tb.labelKey)} ${tb.key}`, value: tb.id }))}
        />
        <Tooltip title={t("themeToggleHint")}>
          <Segmented
            size="small"
            value={mode}
            onChange={(v) => setThemeMode(v as ThemeMode)}
            options={[
              { label: t("themeAuto"), value: "auto" },
              { label: t("themeDark"), value: "dark" },
              { label: t("themeLight"), value: "light" },
            ]}
          />
        </Tooltip>
        <Segmented
          size="small"
          value={lang}
          onChange={(v) => setLang(v as Lang)}
          options={[
            { label: "中", value: "zh" },
            { label: "EN", value: "en" },
          ]}
        />
        <Typography.Text className="ah-md-hide ah-faint" style={{ whiteSpace: "nowrap" }}>
          {t("localOnly")}
        </Typography.Text>
      </Layout.Header>

      <Layout.Content
        className="min-h-0 flex-1 overflow-hidden"
        key={view.name + (view.name === "detail" ? view.sid : "")}
      >
        <div className="view-enter h-full">
          {view.name === "dashboard" && (
            <Dashboard onOpen={(cli, sid) => navigate({ name: "detail", cli, sid })} />
          )}
          {view.name === "detail" && (
            <SessionDetail cli={view.cli} sid={view.sid} onBack={goBack} />
          )}
          {view.name === "threads" && <Threads />}
          {view.name === "inbox" && <Inbox />}
          {view.name === "doctor" && <Doctor />}
        </div>
      </Layout.Content>
    </Layout>
  );
}
