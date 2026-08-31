import { useEffect, useState } from "react";
import { Button, Empty, Slider, Spin, Typography } from "antd";
import { api, type ThreadGroup } from "../api";
import { useT } from "../i18n";

/**
 * Sessions that are actually one job — clustered from lineage, file overlap and
 * title tokens within a time window (threads.py owns the algorithm).
 */
export default function Threads() {
  const t = useT();
  const [threads, setThreads] = useState<ThreadGroup[] | null>(null);
  const [minOverlap, setMinOverlap] = useState(0.15);

  const recluster = async () => {
    setThreads(null);
    const all = await api.threads().catch(() => [] as ThreadGroup[]);
    setThreads(all);
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
            <Spin />
            <span className="ah-meta">{t("clustering")}</span>
          </div>
        )}
        {multi?.length === 0 && <Empty description={<span className="ah-meta">{t("noThreads")}</span>} />}
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
