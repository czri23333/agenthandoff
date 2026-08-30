import { useEffect, useState } from "react";
import { Button, Card, Empty, Skeleton, Slider, Typography } from "antd";
import { api, type ThreadGroup } from "../api";
import { useT } from "../i18n";

export default function Threads() {
  const t = useT();
  const [threads, setThreads] = useState<ThreadGroup[] | null>(null);
  const [minOverlap, setMinOverlap] = useState(0.15);

  const load = async () => setThreads(await api.threads());
  useEffect(() => {
    load();
  }, []);

  const recluster = async () => {
    setThreads(null);
    const all = await fetch(`/api/threads?min_overlap=${minOverlap}`).then((r) => r.json());
    setThreads(all);
  };

  const multi = threads?.filter((th) => th.session_ids.length > 1) ?? null;
  const singleCount = (threads?.length ?? 0) - (multi?.length ?? 0);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-zinc-800/70 px-5 py-2.5">
        <Typography.Text type="secondary" className="text-[12px]">{t("threadsDesc")}</Typography.Text>
        <div className="ml-auto flex items-center gap-3">
          <Typography.Text type="secondary" className="text-[11px]">{t("minOverlap")} {minOverlap.toFixed(2)}</Typography.Text>
          <Slider min={0.05} max={0.6} step={0.05} value={minOverlap} onChange={setMinOverlap} className="w-32! mb-0!" />
          <Button onClick={recluster} loading={threads === null}>{t("recluster")}</Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {threads === null && <Skeleton active paragraph={{ rows: 8 }} />}
        {multi?.length === 0 && <Empty description={t("noThreads")} />}
        {singleCount > 0 && (
          <Typography.Text type="secondary" className="mb-3 block text-[11px]">
            {singleCount} {t("standaloneHidden")}
          </Typography.Text>
        )}
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {multi?.map((th, i) => (
            <Card
              key={i}
              size="small"
              title={
                <span className="flex items-center gap-2">
                  <span className="rounded bg-zinc-800 px-1.5 font-mono text-[10px] text-zinc-400">
                    {th.session_ids.length} {t("sessionsN")}
                  </span>
                  <span className="font-mono text-[10px] text-zinc-500">{th.clis.join(" + ")}</span>
                  <span className="ml-auto font-mono text-[10px] text-zinc-600">{th.last_active?.slice(0, 10)}</span>
                </span>
              }
            >
              <pre className="m-0! whitespace-pre-wrap font-mono text-[11px] leading-[1.7] text-zinc-400">
                {th.lines.slice(1).join("\n")}
              </pre>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
