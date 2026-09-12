import { Suspense, lazy, useEffect, useLayoutEffect, useRef, useState } from "react";
import { App as AntApp, Dropdown, Layout, Tooltip, Typography } from "antd";
import { getLang, setAppLang, useT, type Lang } from "./i18n";
import { getSeed, seeds, setSeed, setThemeMode, useTheme, type ThemeMode } from "./theme";
import Dashboard from "./views/Dashboard";
// Route-split (§4-2): the 1.4MB bundle was every view up front. Dashboard
// stays in the entry chunk; the rest load on first visit with a fallback
// that matches the list skeleton.
const SessionDetail = lazy(() => import("./views/SessionDetail"));
const Threads = lazy(() => import("./views/Threads"));
const Inbox = lazy(() => import("./views/Inbox"));
const Doctor = lazy(() => import("./views/Doctor"));
const MemoryExport = lazy(() => import("./views/MemoryExport"));

// Hash routing: every view and session is a shareable, bookmarkable URL — also
// the reason keyboard/automation can reach any screen without clicking.
type View =
  | { name: "dashboard" }
  | { name: "detail"; cli: string; sid: string }
  | { name: "threads" }
  | { name: "inbox" }
  | { name: "doctor" }
  | { name: "memory" };

const TABS: { id: View["name"]; key: string; labelKey: Parameters<ReturnType<typeof useT>>[0]; hash: string }[] = [
  { id: "dashboard", key: "1", labelKey: "sessions", hash: "" },
  { id: "threads", key: "2", labelKey: "threads", hash: "threads" },
  { id: "inbox", key: "3", labelKey: "inbox", hash: "inbox" },
  { id: "doctor", key: "4", labelKey: "doctor", hash: "doctor" },
  { id: "memory", key: "5", labelKey: "memory", hash: "memory" },
];

const THEME_ORDER: ThemeMode[] = ["auto", "dark", "light"];

export function parseHash(): View {
  const parts = location.hash.replace(/^#/, "").split("/").filter(Boolean);
  if (parts[0] === "session" && parts[1] && parts[2])
    return { name: "detail", cli: decodeURIComponent(parts[1]), sid: decodeURIComponent(parts[2]) };
  if (parts[0] === "threads") return { name: "threads" };
  if (parts[0] === "inbox") return { name: "inbox" };
  if (parts[0] === "doctor") return { name: "doctor" };
  if (parts[0] === "memory") return { name: "memory" };
  return { name: "dashboard" };
}

function toHash(v: View): string {
  if (v.name === "detail") return `#/session/${encodeURIComponent(v.cli)}/${encodeURIComponent(v.sid)}`;
  return v.name === "dashboard" ? "#/" : `#${v.name}`;
}

export default function App() {
  const t = useT();
  const { mode } = useTheme();
  const { message } = AntApp.useApp();
  const [view, setView] = useState<View>(parseHash);
  const [lang, setLangState] = useState<Lang>(getLang);
  const navDepth = useRef(0);
  /* The tab indicator is one element that *travels*, which is what Material's
     own implementation does and what a per-tab pseudo-element cannot: a rule
     can fade its own indicator in, but only a shared element can move between
     two tabs. `theme.ts` cannot measure anything, so this is the one piece of
     geometry the app owns — and it reads its size and colour from tokens. */
  const navRef = useRef<HTMLElement | null>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);
  const activeTabId = view.name === "detail" ? "dashboard" : view.name;

  useLayoutEffect(() => {
    const measure = () => {
      const tab = tabRefs.current[activeTabId];
      const nav = navRef.current;
      if (!tab || !nav) return;
      // `offsetLeft` is relative to the nav's padding box and does not change
      // when the strip is scrolled, so the indicator scrolls with its tab.
      setIndicator({ left: tab.offsetLeft, width: tab.offsetWidth });
    };
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (observer && navRef.current) observer.observe(navRef.current);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [activeTabId]);

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

  // Keyboard: 1-5 views, T theme, / search. Skipped while a field has focus so
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
      <Layout.Header
        className="ah-appbar !flex !items-center gap-x-4 !px-4"
        style={{ borderBottom: "1px solid var(--ah-line)" }}
      >
        {/* An <h1> rather than antd's `Typography.Title level={5}`: the app bar's
            title role is M3's title-large (22px), and antd's own heading rule is
            `h5.ant-typography` plus its runtime hash class, so a single-class
            override loses and the bar kept a 16px heading. */}
        <h1 className="ah-appbar__title m-0 whitespace-nowrap">
          agenthandoff{" "}
          <span className="ah-label ah-label-plain">
            cockpit
          </span>
        </h1>
        {/* PrimaryNavigationTabTokens: the official control for "which of these
            destinations am I on" — a 48dp tab whose 3dp primary indicator sits
            under the active one. This replaces an antd Segmented, which is a
            *segmented button*: the right control for a filter, the wrong one for
            navigation, and at full width it read as a search box.
            Below md the row drops to its own line: it needs ~300px and was being
            overlapped by the theme switcher, which made the wrong control win the
            hit test on a phone. */}
        <nav
          ref={navRef}
          className="ah-tabs min-w-0 flex-1 overflow-x-auto max-md:order-last max-md:basis-full"
          aria-label={t("sessions")}
        >
          {indicator && (
            <span
              className="ah-tabs__indicator"
              aria-hidden="true"
              style={{ translate: `${indicator.left}px`, width: indicator.width }}
            />
          )}
          {TABS.map((tb) => {
            const active = activeTabId === tb.id;
            return (
              <button
                key={tb.id}
                type="button"
                ref={(el) => {
                  tabRefs.current[tb.id] = el;
                }}
                className={`ah-tab ${active ? "ah-tab--active" : "ah-tab--inactive"}`}
                aria-current={active ? "page" : undefined}
                onClick={() => goTo(tb.id)}
              >
                {t(tb.labelKey)}
                <span className="ah-tab__key">{tb.key}</span>
              </button>
            );
          })}
        </nav>
        {/* Display settings are an icon button and a menu, not two more
            segmented buttons. The toolbar above already has one segmented
            control (the search mode) and one below it (the grouping), which is
            what a segmented button is *for* — a filter. Theme and language are
            settings: M3 puts them on an IconButtonTokens trigger that opens a
            MenuTokens menu, and four identical pills in one bar is the thing
            that read as "not a Material app". The `T` shortcut still cycles the
            theme without opening the menu. */}
        <Dropdown
          trigger={["click"]}
          placement="bottomRight"
          menu={{
            selectedKeys: [`theme:${mode}`, `seed:${getSeed() ?? "baseline"}`, `lang:${lang}`],
            onClick: ({ key }) => {
              if (key.startsWith("seed:")) {
                // The menu carries the seed's *id*; the hex comes from the token
                // file, so a preset cannot drift between the two places.
                const id = key.slice("seed:".length);
                const chosen = seeds.find((seed) => seed.id === id);
                const value = chosen?.hex || null;
                // `null` restores the hand-authored baseline; anything else is a
                // seed Google's dynamic-colour maths derives the roles from. The
                // verdict is shown when a seed fails the AA gate the baseline is
                // held to, rather than applied and quietly made unreadable.
                void setSeed(value).then((verdict) => {
                  if (!verdict.ok) {
                    message.warning(`${t("seedRejected")} ${verdict.detail}`);
                  }
                });
                return;
              }
              const [group, value] = key.split(":");
              if (group === "theme") setThemeMode(value as ThemeMode);
              else setLang(value as Lang);
            },
            items: [
              { key: "theme:auto", label: t("themeAuto") },
              { key: "theme:dark", label: t("themeDark") },
              { key: "theme:light", label: t("themeLight") },
              { type: "divider" },
              // From `tokens.json`: a seed is an input to Google's derivation, and
              // the repo's rule is that a colour with no owner does not appear in
              // a component — not even as a starting point.
              ...seeds.map((seed) => ({
                key: `seed:${seed.id}`,
                label: seed.id === "baseline" ? t("seedBaseline") : seed.label,
              })),
              { type: "divider" },
              { key: "lang:zh", label: "中文" },
              { key: "lang:en", label: "EN" },
            ],
          }}
        >
          <Tooltip title={t("themeToggleHint")}>
            <button
              type="button"
              className="ah-iconbtn shrink-0"
              aria-label={t("displaySettings")}
            >
              <span aria-hidden="true">◐</span>
            </button>
          </Tooltip>
        </Dropdown>
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
          {view.name !== "dashboard" && (
            <Suspense
              fallback={
                <div className="space-y-2 px-5 py-3">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="ah-skeleton" />
                  ))}
                </div>
              }
            >
              {view.name === "detail" && (
                <SessionDetail
                  cli={view.cli}
                  sid={view.sid}
                  onBack={goBack}
                  onOpen={(cli, sid) => navigate({ name: "detail", cli, sid })}
                />
              )}
              {view.name === "threads" && <Threads />}
              {view.name === "inbox" && <Inbox />}
              {view.name === "doctor" && <Doctor />}
              {view.name === "memory" && <MemoryExport />}
            </Suspense>
          )}
        </div>
      </Layout.Content>
    </Layout>
  );
}
