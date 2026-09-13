import { useEffect, useState } from "react";
import { Button, Slider, Typography } from "antd";
import { api, type ThreadGroup, type ThreadsCoverage } from "../api";
import { EmptyState } from "../components";
import { useT } from "../i18n";

/**
 * Sessions that are actually one job — clustered from lineage, file overlap and
 * title tokens within a time window (threads.py owns the algorithm).
 */
export default function Threads() {
  const t = useT();
  const [threads, setThreads] = useState<ThreadGroup[] | null>(null);
  const [coverage, setCoverage] = useState<ThreadsCoverage | null>(null);
  const [minOverlap, setMinOverlap] = useState(0.15);

  const recluster = async () => {
    setThreads(null);
    const payload = await api
      .threads()
      .catch(() => ({ threads: [] as ThreadGroup[], coverage: null }));
    setThreads(payload.threads);
    setCoverage(payload.coverage);
  };

  /** The next budget's worth. The server caches what it already read, so this
   *  does not re-pay for the previous batch. */
  const loadMore = async () => {
    const payload = await api.threadsMore().catch(() => null);
    if (!payload) return;
    setThreads(payload.threads);
    setCoverage(payload.coverage);
  };

  useEffect(() => {
    void recluster();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const multi = threads?.filter((th) => th.session_ids.length > 1) ?? null;
  const singleCount = (threads?.length ?? 0) - (multi?.length ?? 0);

  return (
    <div className="flex h-full flex-col">
      <div className="ah-bar flex flex-wrap items-center gap-3 px-5 py-2.5">
        <Typography.Text className="ah-meta">{t("threadsDesc")}</Typography.Text>
        <div className="ml-auto flex items-center gap-3">
          <span className="ah-meta">
            {t("minOverlap")} {minOverlap.toFixed(2)}
          </span>
          <Slider
            min={0.05}
            max={0.6}
            step={0.05}
            value={minOverlap}
            onChange={setMinOverlap}
            className="w-32! mb-0!"
          />
          <Button onClick={() => void recluster()} loading={threads === null}>
            {t("recluster")}
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {threads === null && (
          <div className="flex items-center gap-2 p-6">
            {/* LoadingIndicatorTokens, not antd's four-dot `Spin`: the dots draw
                `colorPrimary` through antd's derivative chain, which resolves to
                `rgb(180,163,220)` — a colour in no token table — where M3E's
                indicator is a 38dp shape in `primary`. */}
            <span className="ah-loading ah-loading--uncontained" aria-hidden="true" />
            <span className="ah-meta">{t("clustering")}</span>
          </div>
        )}
        {multi?.length === 0 && <EmptyState text={t("noThreads")} />}
        {/* Honesty about what was actually read. The file-overlap signal needs
            every session's record; on an 802-session store that is ~150s, so the
            pass stops at a budget and the view reports the count it reached
            rather than presenting partial clusters as the whole picture. */}
        {coverage?.budget_hit && (
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Typography.Text className="ah-warn ah-meta">
              {t("threadsCoverage")
                .replace("{with_files}", String(coverage.with_files))
                .replace("{sessions}", String(coverage.sessions))
                .replace("{seconds}", String(coverage.seconds))}
            </Typography.Text>
            <Button size="small" onClick={() => void loadMore()}>
              {t("threadsLoadMore")}
            </Button>
          </div>
        )}
        {singleCount > 0 && (
          <Typography.Text className="ah-faint mb-3 block">
            {singleCount} {t("standaloneHidden")}
          </Typography.Text>
        )}
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {multi?.map((th, i) => (
            <div key={i} className="ah-card p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="ah-inset px-1.5 py-0.5 font-mono text-[12px]">
                  {th.session_ids.length} {t("sessionsN")}
                </span>
                <span className="ah-meta font-mono">{th.clis.join(" + ")}</span>
                <span className="ah-faint ml-auto font-mono">{th.last_active?.slice(0, 10)}</span>
              </div>
              <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[12px] leading-[1.8] text-[var(--ah-text-1)]">
                {th.lines.slice(1).join("\n")}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
