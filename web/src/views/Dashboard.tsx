import { useEffect, useMemo, useState } from "react";
import { api, relTime, type SessionMeta, type StoreInfo } from "../api";
import { CliBadge, Spinner, StatusDot } from "../components";
import { useT } from "../i18n";

export default function Dashboard({ onOpen }: { onOpen: (cli: string, sid: string) => void }) {
  const t = useT();
  const [sessions, setSessions] = useState<SessionMeta[] | null>(null);
  const [stores, setStores] = useState<StoreInfo[]>([]);
  const [cliFilter, setCliFilter] = useState("");
  const [domainFilter, setDomainFilter] = useState("");
  const [q, setQ] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [, tick] = useState(0); // re-render the freshness counter every second

  const load = async (manual = false) => {
    if (manual) setRefreshing(true);
    const [s, st] = await Promise.all([
      api.sessions({ cli: cliFilter || undefined, q: q || undefined }),
      api.stores(),
    ]);
    // Only re-render when data actually changed — a steady DOM keeps scroll
    // position and hover state stable between polls.
    setSessions((prev) => (JSON.stringify(prev) === JSON.stringify(s) ? prev : s));
    setStores((prev) => (JSON.stringify(prev) === JSON.stringify(st) ? prev : st));
    setUpdatedAt(Date.now());
    setRefreshing(false);
  };

  useEffect(() => {
    load();
    const poll = setInterval(() => load(), 30_000); // stores change slowly; see ADR-006
    const clock = setInterval(() => tick((n) => n + 1), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(clock);
    };
  }, [cliFilter, q]);

  const freshSecs = updatedAt === null ? null : Math.round((Date.now() - updatedAt) / 1000);

  const cliOptions = useMemo(() => [...new Set(stores.map((s) => s.cli))], [stores]);
  const domains = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of sessions ?? []) counts.set(s.domain, (counts.get(s.domain) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [sessions]);

  const visible = (sessions ?? []).filter(
    (s) => !domainFilter || s.domain === domainFilter,
  );

  // Group rows by domain so the cockpit reads as "projects", not a dump.
  const grouped = useMemo(() => {
    const m = new Map<string, SessionMeta[]>();
    for (const s of visible) {
      const list = m.get(s.domain) ?? [];
      list.push(s);
      m.set(s.domain, list);
    }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [visible]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800/70 px-5 py-2.5">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("searchTitles")}
          className="w-56 rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-[13px] outline-none placeholder:text-zinc-600 focus:border-zinc-600"
        />
        <select
          value={cliFilter}
          onChange={(e) => setCliFilter(e.target.value)}
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-[13px] outline-none focus:border-zinc-600"
        >
          <option value="">{t("allClis")}</option>
          {cliOptions.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={domainFilter}
          onChange={(e) => setDomainFilter(e.target.value)}
          className="max-w-56 rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-[13px] outline-none focus:border-zinc-600"
          title="domains come from cwd + optional ~/.agenthandoff/domains.toml (ADR-009)"
        >
          <option value="">{t("allClis") === "全部 CLI" ? "全部项目域" : "all domains"}</option>
          {domains.map(([d, n]) => (
            <option key={d} value={d}>{d} ({n})</option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-3">
          {stores.filter((s) => !s.readable).length > 0 && (
            <span className="text-[11px] text-yellow-500/80">
              {stores.filter((s) => !s.readable).length} {t("unreadable")}
            </span>
          )}
          <span className="text-[11px] text-zinc-600">{visible.length} {t("sessionsN")}</span>
          <span className="flex items-center gap-1.5 text-[11px] text-zinc-600" title={t("autoRefresh")}>
            <span className={`h-1.5 w-1.5 rounded-full bg-emerald-400 ${refreshing ? "freshness-pulse" : ""}`} />
            {refreshing
              ? t("updating")
              : freshSecs !== null && freshSecs < 60
                ? t("updatedAgo").replace("{n}", String(freshSecs))
                : t("autoRefresh")}
          </span>
          <button onClick={() => load(true)} className="flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700">
            {refreshing && <Spinner />} {t("refresh")}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {sessions === null && <p className="text-[13px] text-zinc-600">{t("loading")}</p>}
        {sessions?.length === 0 && <p className="text-[13px] text-zinc-600">{t("noSessions")}</p>}
        {grouped.map(([domain, rows]) => {
          const isCollapsed = collapsed.has(domain);
          return (
          <div key={domain} className="mb-5">
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
              title={isCollapsed ? "点击展开" : "点击折叠"}
            >
              <span className="w-3 text-[10px] text-zinc-600">{isCollapsed ? "▸" : "▾"}</span>
              <h2 className="font-mono text-[12px] font-medium text-zinc-300 hover:text-zinc-100">
                {domain.split(/[\\/]/).filter(Boolean).slice(-1)[0] || domain}
              </h2>
              <span className="font-mono text-[10px] text-zinc-600" title={domain}>{rows.length} {t("sessionsN")}</span>
            </button>
            {!isCollapsed && (
            <ul className="space-y-1.5">
              {rows.map((s) => (
                <li key={`${s.cli}:${s.session_id}`} className="row-enter">
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
                    <span className="w-16 shrink-0 text-right font-mono text-[11px] text-zinc-500">{relTime(s.updated_at)}</span>
                    {s.status ? <StatusDot kind={s.status} /> : <span className="w-2 shrink-0" title={t("unknownEnd")} />}
                  </button>
                </li>
              ))}
            </ul>
            )}
          </div>
          );
        })}
      </div>
    </div>
  );
}
