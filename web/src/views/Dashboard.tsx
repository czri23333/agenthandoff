import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Input, Segmented, Select, Tooltip, Typography, type GetRef } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import {
  api,
  relTime,
  type IndexStatus,
  type SearchHit,
  type SearchStats,
  type SessionMeta,
  type StoreInfo,
} from "../api";
import { CliBadge, CopyButton, Highlight, StatusTag } from "../components";
import { ActivityGrid } from "../charts";
import { useFmt, useT, type TKey } from "../i18n";

/**
 * Session dashboard: grouping by project domain, plus two search modes.
 *
 * "titles" filters the already-loaded list on the client (zero round-trips,
 * instant); "full text" asks /api/search, which answers out of the warm index
 * and reports coverage in `stats` — so while the index is still building the UI
 * shows a progress bar and a growing list instead of a silently partial answer.
 */
type Mode = "titles" | "full";

const DEBOUNCE_MS = 350;
const POLL_MS = 30_000;

export default function Dashboard({ onOpen }: { onOpen: (cli: string, sid: string) => void }) {
  const t = useT();
  const fmt = useFmt();
  const [sessions, setSessions] = useState<SessionMeta[] | null>(null);
  const [stores, setStores] = useState<StoreInfo[]>([]);
  const [cliFilter, setCliFilter] = useState("");
  const [domainFilter, setDomainFilter] = useState("");
  const [mode, setMode] = useState<Mode>("titles");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [stats, setStats] = useState<SearchStats | null>(null);
  const [index, setIndex] = useState<IndexStatus | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [needsReplyOnly, setNeedsReplyOnly] = useState(false);
  const [, tick] = useState(0);
  const inputRef = useRef<GetRef<typeof Input.Search>>(null);

  const load = useCallback(
    async (manual = false) => {
      if (manual) setRefreshing(true);
      const [s, st] = await Promise.all([
        api.sessions({ cli: cliFilter || undefined }),
        api.stores(),
      ]);
      setSessions((prev) => (JSON.stringify(prev) === JSON.stringify(s) ? prev : s));
      setStores((prev) => (JSON.stringify(prev) === JSON.stringify(st) ? prev : st));
      setUpdatedAt(Date.now());
      setRefreshing(false);
    },
    [cliFilter],
  );

  useEffect(() => {
    load();
    const poll = setInterval(() => load(), POLL_MS);
    const clock = setInterval(() => tick((n) => n + 1), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(clock);
    };
  }, [load]);

  /* keyboard "/" from App.tsx */
  useEffect(() => {
    const focus = () => inputRef.current?.focus();
    window.addEventListener("ah-focus-search", focus);
    return () => window.removeEventListener("ah-focus-search", focus);
  }, []);

  /* full-text: debounce, warm the index on demand, poll while it builds */
  useEffect(() => {
    if (mode !== "full" || q.trim().length < 2) {
      setHits(null);
      setStats(null);
      setSearchError("");
      return;
    }
    let cancelled = false;
    let timer: number | undefined;

    const run = async () => {
      setSearching(true);
      try {
        const res = await api.search(q.trim(), { cli: cliFilter || undefined, mode: "full" });
        if (cancelled) return;
        setHits(res.hits);
        setStats(res.stats);
        setIndex((prev) => ({
          state: res.stats.index_state,
          done: prev?.done ?? 0,
          total: res.stats.total,
          indexed: res.stats.indexed,
          error: prev?.error ?? "",
        }));
        setSearchError("");
      } catch (e) {
        if (!cancelled) setSearchError(String(e));
      } finally {
        if (!cancelled) setSearching(false);
      }
    };

    timer = window.setTimeout(run, DEBOUNCE_MS);
    return () => {
      if (timer) clearTimeout(timer);
      cancelled = true;
    };
  }, [mode, q, cliFilter]);

  const building = stats?.index_state === "building" || index?.state === "building";
  useEffect(() => {
    if (mode !== "full" || q.trim().length < 2) return;
    if (!building) return;
    const poll = setInterval(async () => {
      try {
        setIndex(await api.searchStatus());
        const res = await api.search(q.trim(), { cli: cliFilter || undefined, mode: "full" });
        setHits(res.hits);
        setStats(res.stats);
      } catch {
        /* transient: the next tick retries */
      }
    }, 1200);
    return () => clearInterval(poll);
  }, [mode, q, cliFilter, building]);

  const [showActivity, setShowActivity] = useState(false);
  const cliOptions = useMemo(() => [...new Set(stores.map((s) => s.cli))], [stores]);

  const titleFiltered = useMemo(() => {
    const list = sessions ?? [];
    const needle = mode === "titles" ? q.trim().toLowerCase() : "";
    if (!needle) return list;
    return list.filter(
      (s) =>
        s.title.toLowerCase().includes(needle) ||
        s.cwd.toLowerCase().includes(needle) ||
        s.cli.toLowerCase().includes(needle) ||
        (s.model ?? "").toLowerCase().includes(needle),
    );
  }, [sessions, q, mode]);

  const domains = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of titleFiltered) counts.set(s.domain, (counts.get(s.domain) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [titleFiltered]);

  const needsReplyCount = useMemo(
    () => (sessions ?? []).filter((s) => s.needs_reply === true).length,
    [sessions],
  );
  const visible = titleFiltered.filter(
    (s) =>
      (!domainFilter || s.domain === domainFilter) &&
      (!needsReplyOnly || s.needs_reply === true),
  );
  const grouped = useMemo(() => {
    const m = new Map<string, SessionMeta[]>();
    for (const s of visible) {
      const list = m.get(s.domain) ?? [];
      list.push(s);
      m.set(s.domain, list);
    }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [visible]);

  const freshSecs = updatedAt === null ? null : Math.round((Date.now() - updatedAt) / 1000);
  const unreadable = stores.filter((s) => !s.readable).length;

  const indexLine = () => {
    if (mode !== "full") return null;
    if (searchError) return <span className="ah-err ah-meta">{searchError}</span>;
    if (stats?.index_state === "failed") return <span className="ah-err ah-meta">{index?.error ?? stats.index_state}</span>;
    if (building)
      return (
        <span className="ah-meta ah-accent">
          {fmt("indexing", { done: index?.done ?? stats?.indexed ?? 0, total: stats?.total ?? index?.total ?? 0 })}
        </span>
      );
    if (stats?.index_state === "idle") return <span className="ah-faint">{t("indexIdle")}</span>;
    return (
      <span className="ah-faint">
        {fmt("indexReady", { n: stats?.indexed ?? 0 })}
        {stats ? ` · ${fmt("searchedIn", { ms: stats.took_ms, scanned: stats.scanned, total: stats.total })}` : ""}
      </span>
    );
  };

  const showHits = mode === "full" && q.trim().length >= 2;

  return (
    <div className="flex h-full flex-col">
      <div className="ah-bar ah-toolbar px-4 py-2.5">
        <Segmented
          size="small"
          value={mode}
          onChange={(v) => setMode(v as Mode)}
          options={[
            { label: t("searchModeTitle"), value: "titles" },
            { label: t("searchModeFull"), value: "full" },
          ]}
        />
        <Input.Search
          ref={inputRef}
          allowClear
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onSearch={(v) => setQ(v)}
          placeholder={mode === "titles" ? t("searchTitles") : t("searchFull")}
          className="ah-search-input"
          loading={searching}
        />
        <Select
          value={cliFilter || undefined}
          onChange={setCliFilter}
          placeholder={t("allClis")}
          allowClear
          className="w-44"
          options={cliOptions.map((c) => ({ value: c, label: c }))}
        />
        <Tooltip title={t("domainsHint")}>
          <Select
            value={domainFilter || undefined}
            onChange={setDomainFilter}
            placeholder={t("allDomains")}
            allowClear
            className="ah-narrow-hide min-w-56 max-w-80"
            options={domains.map(([d, n]) => ({
              value: d,
              label: `${d.split(/[\\/]/).filter(Boolean).pop() ?? d} (${n})`,
            }))}
          />
        </Tooltip>
        <Tooltip title={t("needsReplyHint")}>
          <Button
            size="small"
            type={needsReplyOnly ? "primary" : "default"}
            onClick={() => setNeedsReplyOnly((v) => !v)}
          >
            ⚠ {t("needsReply")}
            {needsReplyCount > 0 && (
              <span className="ml-1 font-mono">{needsReplyCount}</span>
            )}
          </Button>
        </Tooltip>
        <div className="ml-auto flex items-center gap-3">
          {indexLine()}
          {showHits && !building && (
            <Button size="small" onClick={() => void api.searchWarm().then(setIndex)}>
              {t("rebuildIndex")}
            </Button>
          )}
          {unreadable > 0 && (
            <Tooltip title={t("doctor")}>
              <span className="ah-inset ah-warn px-2 py-0.5 font-mono text-[12px]">
                ⚠ {unreadable} {t("unreadable")}
              </span>
            </Tooltip>
          )}
          <span className="ah-md-hide ah-faint flex items-center gap-1.5">
            <span
              className="freshness-dot h-1.5 w-1.5 rounded-full"
              style={{ opacity: refreshing ? 0.5 : 1 }}
            />
            {refreshing
              ? t("updating")
              : freshSecs !== null && freshSecs < 60
                ? fmt("updatedAgo", { n: freshSecs })
                : t("autoRefresh")}
          </span>
          <Button size="small" type="text" onClick={() => setShowActivity((v) => !v)}>
            {t("activity")}
          </Button>
          <Button icon={<ReloadOutlined spin={refreshing} />} onClick={() => void load(true)} size="small">
            {t("refresh")}
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {showActivity && !showHits && sessions && sessions.length > 0 && (
          <div className="ah-card mb-3 p-3">
            <div className="ah-label mb-2">{t("activity")}</div>
            <ActivityGrid sessions={sessions} label={t("activity")} />
          </div>
        )}
        {showHits ? (
          <HitList hits={hits} stats={stats} query={q} onOpen={onOpen} building={!!building} />
        ) : sessions === null ? (
          <SkeletonRows n={10} />
        ) : visible.length === 0 ? (
          <Empty description={t("noSessions")}>
            <FirstRun />
          </Empty>
        ) : (
          grouped.map(([domain, rows]) => {
            const isCollapsed = collapsed.has(domain);
            const short =
              domain.split(/[\\/]/).filter(Boolean).pop() || domain || t("noProjectPath");
            return (
              <div key={domain} className="mb-4">
                <button
                  onClick={() =>
                    setCollapsed((prev) => {
                      const next = new Set(prev);
                      if (next.has(domain)) next.delete(domain);
                      else next.add(domain);
                      return next;
                    })
                  }
                  className="mb-1.5 flex w-full items-baseline gap-2 text-left"
                >
                  <span className="w-3 ah-faint">{isCollapsed ? "▸" : "▾"}</span>
                  <span className="ah-title font-mono font-medium">{short}</span>
                  <Tooltip title={domain}>
                    <span className="ah-faint font-mono">
                      {rows.length} {t("sessionsN")}
                    </span>
                  </Tooltip>
                </button>
                {!isCollapsed && (
                  <ul className="m-0 list-none space-y-1.5 p-0">
                    {rows.map((s) => (
                      <li key={`${s.cli}:${s.session_id}`} className="row-enter">
                        <button
                          onClick={() => onOpen(s.cli, s.session_id)}
                          className="ah-row group flex w-full items-center gap-3 px-3 py-2 text-left"
                        >
                          <CliBadge cli={s.cli} origin={s.origin} />
                          <span className="min-w-0 flex-1">
                            <span className="ah-title block truncate">{s.title}</span>
                            <span className="ah-faint block truncate font-mono text-[11px] leading-tight">
                              {s.session_id.slice(0, 8)}
                              {s.git?.branch && (
                                <span className="ml-1.5 ah-accent">⎇ {s.git.branch}</span>
                              )}
                              {s.cwd && (
                                <span className="ml-1.5" dir="auto">· {s.cwd.split(/[\\/]/).filter(Boolean).pop() ?? s.cwd}</span>
                              )}
                            </span>
                          </span>
                          {s.parent_session_id && (
                            <Tooltip title={`${t("subSession")} · ${s.parent_session_id}`}>
                              <span className="ah-faint hidden shrink-0 font-mono xl:inline">⤷ {t("subSession")}</span>
                            </Tooltip>
                          )}
                          {s.provider && (
                            <Tooltip title={t("provider")}>
                              <span className="ah-faint hidden shrink-0 font-mono lg:inline">
                                {(s.provider as string).slice(0, 18)}
                              </span>
                            </Tooltip>
                          )}
                          {/* Below sm these two fixed columns starved the title to
                          zero width; the title is the only thing that identifies a
                          row, so the columns give way first. */}
                          <span className="ah-faint w-16 shrink-0 text-right font-mono max-sm:hidden">
                            {relTime(s.updated_at)}
                          </span>
                          {s.needs_reply === true && (
                            <Tooltip title={t("needsReplyHint")}>
                              <span className="ah-warn shrink-0 text-[13px]">⚠</span>
                            </Tooltip>
                          )}
                          <span className="w-24 shrink-0 text-right max-sm:hidden">
                            <StatusTag kind={s.status} />
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function HitList({
  hits,
  stats,
  query,
  onOpen,
  building,
}: {
  hits: SearchHit[] | null;
  stats: SearchStats | null;
  query: string;
  onOpen: (cli: string, sid: string) => void;
  building: boolean;
}) {
  const t = useT();
  const fmt = useFmt();
  if (hits === null)
    return (
      <div className="mb-3">
        <SkeletonRows n={4} />
      </div>
    );
  const progress = stats && stats.total > 0 ? Math.min(100, (stats.indexed / stats.total) * 100) : 0;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <Typography.Text className="ah-meta">{fmt("hits", { n: hits.length })}</Typography.Text>
        {stats && stats.truncated && <span className="ah-faint">· 50+</span>}
        {building && (
          <div className="ah-progress ml-auto w-56">
            <i style={{ width: `${progress}%` }} />
          </div>
        )}
      </div>
      {hits.length === 0 && !building && (
        <Empty description={<span className="ah-meta">{t("noFullHits")}</span>} />
      )}
      <ul className="m-0 list-none space-y-1.5 p-0">
        {hits.map((h) => (
          <li key={`${h.cli}:${h.session_id}`} className="row-enter">
            <button onClick={() => onOpen(h.cli, h.session_id)} className="ah-row flex w-full flex-col gap-1 px-3 py-2 text-left">
              <span className="flex w-full items-center gap-3">
                <CliBadge cli={h.cli} />
                <span className="ah-title min-w-0 flex-1 truncate">
                  <Highlight text={h.title} query={query} />
                </span>
                <span className="ah-faint shrink-0 font-mono">{h.score}</span>
                <span className="ah-faint w-16 shrink-0 text-right font-mono">{relTime(h.updated_at)}</span>
              </span>
              <span className="flex w-full items-center gap-2">
                {h.matched && (
                  <span className="ah-inset px-1.5 py-0.5 font-mono text-[12px]">
                    {h.matched
                      .split("+")
                      .map((m) => t(MATCH_TK[m] ?? "matchBody"))
                      .join(" + ")}
                  </span>
                )}
                <span className="ah-faint min-w-0 flex-1 truncate font-mono">{h.cwd}</span>
              </span>
              {h.excerpt && (
                <span className="ah-meta min-w-0 break-words">
                  <Highlight text={h.excerpt} query={query} />
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Which surface produced a hit, in the user's language. */
const MATCH_TK: Record<string, TKey> = {
  title: "matchTitle",
  body: "matchBody",
  file: "matchFile",
  cwd: "matchCwd",
  model: "matchModel",
  provider: "matchProvider",
  origin: "matchOrigin",
};

/**
 * First-run guidance. The cockpit is usually opened by someone who has never
 * run the CLI, so the empty state teaches the whole loop in three steps and
 * keeps the keyboard map visible.
 */
function FirstRun() {
  const t = useT();
  const steps: [string, string][] = [
    [t("guideStep1"), "handoff doctor"],
    [t("guideStepFind"), "handoff list --cli codex -n 10"],
    [t("guideStep2"), "handoff capture -o handoff.md"],
    [t("guideStep3"), "handoff resume handoff.md --lang zh"],
    [t("guideStep4"), "handoff watch --cli codex --every 60"],
    [t("guideStep5"), "handoff publish handoff.md --lease-minutes 45"],
  ];
  return (
    <div className="ah-card mx-auto mt-4 max-w-[620px] p-4 text-left">
      <div className="ah-title mb-2 font-medium">{t("guideTitle")}</div>
      <ol className="m-0 list-none space-y-2 p-0">
        {steps.map(([label, cmd], i) => (
          <li key={cmd} className="flex flex-wrap items-center gap-2">
            <span className="ah-inset min-w-[22px] px-1.5 text-center font-mono text-[12px]">{i + 1}</span>
            <span className="ah-meta min-w-0 flex-1">{label}</span>
            <code className="ah-code px-2 py-1 text-[12px]">{cmd}</code>
            <CopyButton text={cmd} label="copy" />
          </li>
        ))}
      </ol>
      <div className="ah-faint mt-3 border-t border-[var(--ah-line)] pt-2">{t("searchHint")}</div>
    </div>
  );
}

function SkeletonRows({ n }: { n: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="ah-skeleton h-11" />
      ))}
    </div>
  );
}
