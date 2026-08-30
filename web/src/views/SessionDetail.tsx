import { useEffect, useState } from "react";
import { Alert, Button, Card, Descriptions, Segmented, Table, Tag, Timeline, Tooltip, Typography } from "antd";
import { ExportOutlined } from "@ant-design/icons";
import { api, relTime, type SessionDetail as Detail, type TranscriptMessage } from "../api";
import { Bullets, CliBadge, CopyButton, InterruptionBanner } from "../components";
import { formatNum, useT } from "../i18n";

function TranscriptRow({ m }: { m: TranscriptMessage }) {
  const [open, setOpen] = useState(false);
  const long = m.text.length > 500;
  return (
    <div
      className={`cursor-pointer rounded-lg px-2.5 py-1.5 text-[12.5px] ${m.role === "user" ? "bg-sky-500/10 text-sky-100" : "bg-zinc-800/50 text-zinc-300"}`}
      onClick={() => long && setOpen(!open)}
      title={long ? (open ? "点击收起" : "点击展开全文") : undefined}
    >
      <span className="mr-1.5 select-none font-mono text-[9px] uppercase text-zinc-500">
        {m.role === "user" ? "👤 用户" : "🤖 助手"}
      </span>
      <span className="whitespace-pre-wrap break-words">
        {open || !long ? m.text : `${m.text.slice(0, 500)}…`}
      </span>
      {long && (
        <span className="ml-1.5 select-none text-[10px] text-cyan-400/80">
          {open ? "▲ 收起" : `▼ 展开全文（${m.text.length} 字）`}
        </span>
      )}
    </div>
  );
}

export default function SessionDetail({ cli, sid, onBack }: { cli: string; sid: string; onBack: () => void }) {
  const t = useT();
  const [data, setData] = useState<Detail | null>(null);
  const [launcher, setLauncher] = useState<Parameters<typeof Object>[0] extends never ? never : import("../api").Launcher | null>(null);
  const [lang, setLang] = useState<"en" | "zh">("en");
  const [err, setErr] = useState("");
  const [pub, setPub] = useState("");

  useEffect(() => {
    setData(null);
    api.detail(cli, sid, lang).then(setData).catch((e) => setErr(String(e)));
    api.launcher(cli, sid).then(setLauncher).catch(() => setLauncher(null));
  }, [cli, sid, lang]);

  if (err) return <div className="p-5"><Alert type="error" showIcon message="加载失败" description={err} /></div>;
  if (!data) return <div className="p-5 text-[13px] text-zinc-600">{t("loading")}</div>;
  const b = data.bundle;
  const meta = b.meta;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-zinc-800/70 px-5 py-2.5">
        <Button type="text" size="small" onClick={onBack}>← {t("back")}</Button>
        <CliBadge cli={meta.cli} origin={meta.origin} />
        <span className="min-w-0 flex-1 truncate text-[13px] text-zinc-200">{meta.title}</span>
        <span className="font-mono text-[11px] text-zinc-600">{relTime(meta.updated_at)}</span>
        {meta.provider && <Tooltip title="模型路由（额度归属）"><Tag className="font-mono!">⛽ {meta.provider}</Tag></Tooltip>}
        <div className="flex items-center gap-2">
          <Segmented size="small" value={lang} onChange={(v) => setLang(v as "en" | "zh")} options={[{ label: "EN", value: "en" }, { label: "中文", value: "zh" }]} />
          <CopyButton text={data.markdown} label={t("copyBundle")} />
          <Button size="small" icon={<ExportOutlined />} onClick={async () => {
            const r = await api.publish(cli, sid).catch(() => null);
            setPub(r ? `已发布 → ${r.published}` : "发布失败");
          }}>{t("publish")}</Button>
        </div>
      </div>
      {pub && <div className="truncate border-b border-zinc-800/70 bg-zinc-900/60 px-5 py-1 font-mono text-[11px] text-emerald-400/80">{pub}</div>}

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_400px] gap-4 overflow-hidden p-4">
        <div className="space-y-3 overflow-y-auto pr-1">
          <InterruptionBanner it={data.interruption} />

          <Card size="small" title={t("objective").toUpperCase()}>
            <Typography.Paragraph className="mb-0! text-[13.5px] text-zinc-100">{b.objective || "（未捕获）"}</Typography.Paragraph>
            {b.topics.length >= 2 && (
              <div className="mt-2 space-y-1 border-t border-zinc-800 pt-2">
                <Typography.Text type="secondary" className="text-[11px]">{t("topicSegments")}</Typography.Text>
                {b.topics.map((tp, i) => (
                  <div key={i} className="flex items-start gap-2 text-[12px] text-zinc-400">
                    <Tag className="mr-0 px-1! font-mono!" color="default">{i + 1}</Tag>
                    <span className="min-w-0 flex-1">{tp.opener}</span>
                    <span className="shrink-0 text-zinc-600">{tp.messages} {t("msg")}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <div className="grid grid-cols-3 gap-3">
            <Card size="small" title={<span className="text-[11px] text-emerald-400/80">✓ {t("done")}</span>}>
              <Bullets items={b.state.done} />
            </Card>
            <Card size="small" title={<span className="text-[11px] text-sky-400/80">◐ {t("inProgress")}</span>}>
              <Bullets items={b.state.in_progress} />
            </Card>
            <Card size="small" title={<span className="text-[11px] text-red-400/80">⚑ {t("blockedOpen")}</span>}>
              <Bullets items={b.state.blocked} />
            </Card>
          </div>

          <Card size="small" title={<span className="text-[11px]">{t("keyDirectives")}</span>} extra={<Tag color="gold" className="mr-0!">{t("mustObey")}</Tag>}>
            <Bullets items={b.directives} />
          </Card>

          <Card size="small" title={<span className="text-[11px]">{t("nextSteps")}</span>}>
            <Bullets items={b.next_steps} numbered />
          </Card>

          {data.usage && (
            <Card size="small" title={<span className="text-[11px]">{t("usage")}</span>}
              extra={<span className="font-mono text-[10px] text-zinc-500">Σ {formatNum(data.usage.totals.tokens_in)}↓ {formatNum(data.usage.totals.tokens_out)}↑ · {data.usage.totals.calls} {t("calls")}</span>}>
              <Table
                size="small"
                pagination={false}
                rowKey="model"
                dataSource={data.usage.models}
                columns={[
                  { title: t("model"), dataIndex: "model", ellipsis: true },
                  { title: t("calls"), dataIndex: "calls", align: "right", width: 60 },
                  { title: t("tokensIn"), dataIndex: "tokens_in", align: "right", width: 80, render: formatNum },
                  { title: t("tokensOut"), dataIndex: "tokens_out", align: "right", width: 80, render: formatNum },
                  { title: t("reasoning"), dataIndex: "reasoning", align: "right", width: 80, render: formatNum },
                  { title: "cache", key: "cache", align: "right", width: 110, render: (_: unknown, r: { cache_write: number | null; cache_read: number | null }) => `${formatNum(r.cache_write)}/${formatNum(r.cache_read)}` },
                  { title: t("ttft"), dataIndex: "avg_ttft_ms", align: "right", width: 70, render: (v: number | null) => (v != null ? `${(v / 1000).toFixed(1)}s` : "—") },
                  { title: t("tokSpeed"), dataIndex: "tok_per_s", align: "right", width: 80, render: (v: number | null) => (v != null ? v.toFixed(0) : "—") },
                ]}
              />
            </Card>
          )}

          <Card size="small"
            title={<span className="text-[11px]">{t("transcript")}{data.compactions > 0 ? ` · ${data.compactions} × 压缩` : ""}</span>}
            extra={data.compactions > 0 ? <Tooltip title="长会话的上下文被多次压缩，边界之前的消息仅存模型摘要"><Tag color="gold" className="mr-0!">⚠ 历史含压缩</Tag></Tooltip> : undefined}>
            {data.messages.length === 0 ? (
              <Typography.Text type="secondary" className="text-[12px] italic">{t("noMessages")}</Typography.Text>
            ) : (
              <div className="max-h-96 overflow-y-auto">
                <Timeline
                  className="mt-1!"
                  items={data.messages.map((m) =>
                    m.role === "compaction"
                      ? {
                          color: "gold",
                          children: (
                            <span className="font-mono text-[10.5px] text-amber-300">
                              ⚠ 上下文压缩 {m.text} —— 此边界之前的消息仅存模型摘要
                            </span>
                          ),
                        }
                      : {
                          color: m.role === "user" ? "blue" : "gray",
                          children: <TranscriptRow m={m} />,
                        },
                  )}
                />
              </div>
            )}
          </Card>

          <div className="grid grid-cols-2 gap-3">
            <Card size="small" title={<span className="text-[11px]">{t("filesTouched")}</span>}>
              {b.files_touched.length === 0 ? (
                <Typography.Text type="secondary" className="text-[12px] italic">（无记录）</Typography.Text>
              ) : (
                <ul className="m-0 list-none space-y-0.5 p-0 font-mono text-[11.5px] text-zinc-400">
                  {b.files_touched.map((f) => (
                    <li key={f.path} className="truncate" title={f.path}>{f.path} <span className="text-zinc-600">×{f.hits}</span></li>
                  ))}
                </ul>
              )}
            </Card>
            <Card size="small" title={<span className="text-[11px]">{t("contextNotes")}</span>}>
              <Bullets items={b.context_notes} />
            </Card>
          </div>
        </div>

        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          <Card size="small" title={t("continuationBrief")} extra={<CopyButton text={data.brief} label={t("copyBrief")} />}>
            <pre className="max-h-[38vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/40 p-2.5 font-mono text-[11px] leading-relaxed text-zinc-300">
              {data.brief}
            </pre>
          </Card>

          <Card size="small" title={t("resumeInCli")}
            extra={<Tag color={launcher?.kind === "verified" ? "green" : "gold"} className="mr-0!">{launcher ? t(launcher.kind === "verified" ? "verified" : "unverified") : t("noLauncher")}</Tag>}>
            {launcher ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded bg-black/40 px-2 py-1.5 font-mono text-[11.5px] text-cyan-300">{launcher.command}</code>
                  <CopyButton text={launcher.command} />
                </div>
                {launcher.headless && <p className="mb-0 text-[11px] text-zinc-500">{t("headless")}: <code>{launcher.headless}</code></p>}
                {launcher.kind === "unverified" && <p className="mb-0 text-[11px] text-yellow-600/80">{t("unverifiedHint")}</p>}
              </div>
            ) : (
              <Typography.Text type="secondary" className="text-[12px] italic">{t("noVerifiedLauncher")}</Typography.Text>
            )}
          </Card>

          <Card size="small" title={t("session")}>
            <Descriptions size="small" column={1} className="font-mono! text-[11px]">
              <Descriptions.Item label="id">{meta.session_id}</Descriptions.Item>
              <Descriptions.Item label="cwd"><span className="break-all">{meta.cwd}</span></Descriptions.Item>
              <Descriptions.Item label="model">{meta.model ?? "—"}</Descriptions.Item>
              {meta.parent_session_id && <Descriptions.Item label="parent">{meta.parent_session_id}</Descriptions.Item>}
            </Descriptions>
          </Card>
        </div>
      </div>
    </div>
  );
}
