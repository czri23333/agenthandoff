import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Empty, Input, Select, Tooltip } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { api, relTime, type SessionMeta, type StoreInfo } from "../api";
import { CliBadge, StatusDot } from "../components";
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
  const [, tick] = useState(0);

  const load = async (manual = false) => {
    if (manual) setRefreshing(true);
    const [s, st] = await Promise.all([
      api.sessions({ cli: cliFilter || undefined, q: q || undefined }),
      api.stores(),
    ]);
    setSessions((prev) => (JSON.stringify(prev) === JSON.stringify(s) ? prev : s));
    setStores((prev) => (JSON.stringify(prev) === JSON.stringify(st) ? prev : st));
    setUpdatedAt(Date.now());
    setRefreshing(false);
  };

  useEffect(() => {
    load();
    const poll = setInterval(() => load(), 30_000);
    const clock = setInterval(() => tick((n) => n + 1), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(clock);
    };
  }, [cliFilter, q]);

  const cliOptions = useMemo(() => [...new Set(stores.map((s) => s.cli))], [stores]);
  const domains = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of sessions ?? []) counts.set(s.domain, (counts.get(s.domain) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [sessions]);

  const visible = (sessions ?? []).filter((s) => !domainFilter || s.domain === domainFilter);
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

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800/70 px-5 py-2.5">
        <Input.Search
          allowClear
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("searchTitles")}
          className="w-60"
        />
        <Select
          value={cliFilter || undefined}
          onChange={setCliFilter}
          placeholder={t("allClis")}
          allowClear
          className="w-40"
          options={cliOptions.map((c) => ({ value: c, label: c }))}
        />
        <Tooltip title="项目域来自 cwd，可用 ~/.agenthandoff/domains.toml 自定义规则（ADR-009）">
          <Select
            value={domainFilter || undefined}
            onChange={setDomainFilter}
            placeholder="全部项目域"
            allowClear
            className="min-w-52 max-w-72"
            options={domains.map(([d, n]) => ({ value: d, label: `${d.split(/[\\/]/).filter(Boolean).pop()} (${n})` }))}
          />
        </Tooltip>
        <div className="ml-auto flex items-center gap-3">
          {stores.filter((s) => !s.readable).length > 0 && (
            <Badge count={stores.filter((s) => !s.readable).length} color="gold">
              <span className="text-[11px] text-zinc-500">{t("doctor")}</span>
            </Badge>
          )}
          <span className="flex items-center gap-1.5 text-[11px] text-zinc-600">
            <span className={`h-1.5 w-1.5 rounded-full bg-emerald-400 ${refreshing ? "opacity-40" : ""}`} />
            {refreshing ? t("updating") : freshSecs !== null && freshSecs < 60 ? t("updatedAgo").replace("{n}", String(freshSecs)) : t("autoRefresh")}
          </span>
          <Button icon={<ReloadOutlined spin={refreshing} />} onClick={() => load(true)} size="small">
            {t("refresh")}
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {sessions === null && <Skeleton active />}
        {sessions?.length === 0 && <Empty description={t("noSessions")} />}
        {grouped.map(([domain, rows]) => {
          const isCollapsed = collapsed.has(domain);
          const short = domain.split(/[\\/]/).filter(Boolean).pop() || domain;
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
                <span className="w-3 text-[10px] text-zinc-600">{isCollapsed ? "▸" : "▾"}</span>
                <span className="font-mono text-[12px] font-medium text-zinc-300 hover:text-zinc-100">{short}</span>
                <Tooltip title={domain}>
                  <span className="font-mono text-[10px] text-zinc-600">{rows.length} {t("sessionsN")}</span>
                </Tooltip>
              </button>
              {!isCollapsed && (
                <ul className="m-0 list-none space-y-1.5 p-0">
                  {rows.map((s) => (
                    <li key={`${s.cli}:${s.session_id}`} className="row-enter">
                      <button
                        onClick={() => onOpen(s.cli, s.session_id)}
                        className="group flex w-full items-center gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3 py-2 text-left transition-colors hover:border-zinc-600 hover:bg-zinc-900"
                      >
                        <CliBadge cli={s.cli} origin={s.origin} />
                        <span className="min-w-0 flex-1 truncate text-[13px] text-zinc-200 group-hover:text-white">{s.title}</span>
                        {s.parent_session_id && (
                          <Tooltip title={`子任务 · ${s.parent_session_id}`}>
                            <span className="hidden shrink-0 font-mono text-[10px] text-zinc-600 xl:inline">⤷ 子会话</span>
                          </Tooltip>
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

function Skeleton({ active }: { active: boolean }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="h-11 animate-pulse rounded-lg bg-zinc-900" style={{ opacity: 1 - i * 0.07 }} />
      ))}
      {active ? null : null}
    </div>
  );
}
