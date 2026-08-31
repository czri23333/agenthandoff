import { useEffect, useState } from "react";
import { Alert, Button, Card, Descriptions, Segmented, Table, Tooltip, Typography } from "antd";
import { ExportOutlined } from "@ant-design/icons";
import {
  api,
  relTime,
  type Launcher,
  type SessionDetail as Detail,
  type TranscriptMessage,
} from "../api";
import { Bullets, CliBadge, CopyButton, InterruptionBanner, SectionCard, StatusTag } from "../components";
import { BudgetGauge, TokenBars, TurnTimeline, type ChartLabels } from "../charts";
import { formatNum, useT } from "../i18n";

/**
 * One session: the bundle, its transcript, the continuation brief, and the
 * verified command that resumes it in the original CLI.
 *
 * Meta rows (agent, provider, model, origin) are the most-scanned-and-least
 * -important-to-ink lines, so they use the AA-verified tiers rather than the
 * old opacity-faded text that made them unreadable in dark mode.
 */
function TranscriptRow({ m, labels }: { m: TranscriptMessage; labels: { user: string; assistant: string; expand: string; collapse: string } }) {
  const [open, setOpen] = useState(false);
  const long = m.text.length > 500;
  const who = m.role === "user" ? labels.user : labels.assistant;
  return (
    <div
      className="ah-inset cursor-pointer rounded-md px-2.5 py-1.5 text-[13px] leading-[1.65]"
      onClick={() => long && setOpen(!open)}
      title={long ? (open ? labels.collapse : labels.expand) : undefined}
    >
      <span className="ah-label mr-1.5 select-none" style={{ textTransform: "none" }}>
        {m.role === "user" ? "👤" : "🤖"} {who}
      </span>
      <span className="whitespace-pre-wrap break-words text-[var(--ah-text-1)]">
        {open || !long ? m.text : `${m.text.slice(0, 500)}…`}
      </span>
      {long && (
        <span className="ah-accent ml-1.5 select-none text-[12px]">
          {open ? `▲ ${labels.collapse}` : `▼ ${labels.expand} (${m.text.length})`}
        </span>
      )}
    </div>
  );
}

export default function SessionDetail({
  cli,
  sid,
  onBack,
}: {
  cli: string;
  sid: string;
  onBack: () => void;
}) {
  const t = useT();
  const charts: ChartLabels = {
    tokensIn: t("tokensIn"),
    tokensOut: t("tokensOut"),
    model: t("model"),
    calls: t("calls"),
    turns: t("turns"),
    user: t("user"),
    assistant: t("assistant"),
    compaction: t("compactionNote"),
    budget: t("budget"),
    fired: t("snapFired"),
    pending: t("snapPending"),
    peak: t("chartPeak"),
    perBucket: t("chartPerBucket"),
    noData: t("noChart"),
  };
  const [data, setData] = useState<Detail | null>(null);
  const [launcher, setLauncher] = useState<Launcher | null>(null);
  const [lang, setLang] = useState<"en" | "zh">("zh");
  const [err, setErr] = useState("");
  const [pub, setPub] = useState("");

  useEffect(() => {
    setData(null);
    setErr("");
    api
      .detail(cli, sid, lang)
      .then(setData)
      .catch((e) => setErr(String(e)));
    api.launcher(cli, sid).then(setLauncher).catch(() => setLauncher(null));
  }, [cli, sid, lang]);

  if (err)
    return (
      <div className="p-5">
        <Alert type="error" showIcon message={t("loading")} description={err} />
      </div>
    );
  if (!data)
    return (
      <div className="p-5">
        <Typography.Text className="ah-meta">{t("loading")}</Typography.Text>
      </div>
    );

  const b = data.bundle;
  const meta = b.meta;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* agent identity bar — the thing that used to be 1.1:1 contrast */}
      <div className="ah-bar flex flex-wrap items-center gap-3 px-5 py-2.5">
        <Button type="text" size="small" onClick={onBack}>
          ← {t("back")}
        </Button>
        <CliBadge cli={meta.cli} origin={meta.origin} title={meta.cli} />
        <span className="ah-title min-w-0 flex-1 truncate font-medium">{meta.title}</span>
        <StatusTag kind={b.interruption?.kind ?? null} />
        <span className="ah-faint font-mono">{relTime(meta.updated_at)}</span>
        {meta.provider && (
          <Tooltip title={t("provider")}>
            <span className="ah-inset px-2 py-0.5 font-mono text-[12px]">⛽ {meta.provider}</span>
          </Tooltip>
        )}
        {meta.model && (
          <Tooltip title={t("model")}>
            <span className="ah-inset px-2 py-0.5 font-mono text-[12px]">🧠 {meta.model}</span>
          </Tooltip>
        )}
        <div className="flex items-center gap-2">
          <Segmented
            size="small"
            value={lang}
            onChange={(v) => setLang(v as "en" | "zh")}
            options={[
              { label: "EN", value: "en" },
              { label: "中文", value: "zh" },
            ]}
          />
          <CopyButton text={data.markdown} label={t("copyBundle")} />
          <Button
            size="small"
            icon={<ExportOutlined />}
            onClick={async () => {
              const r = await api.publish(cli, sid).catch(() => null);
              setPub(r ? `${t("published")} → ${r.published}` : t("publishFailed"));
            }}
          >
            {t("publish")}
          </Button>
        </div>
      </div>
      {pub && (
        <div className="ah-code truncate border-0 border-b px-5 py-1.5 font-mono text-[12px]" style={{ borderColor: "var(--ah-line)" }}>
          {pub}
        </div>
      )}

      {/* Two columns on a wide window, stacked below 1200px: a fixed 420px rail
          squeezed the bundle into an unreadable column on a 1280 laptop. */}
      <div className="ah-shell">
        {/* left: the bundle */}
        <div className="ah-main space-y-3 pr-1">
          <InterruptionBanner it={data.interruption} />

          <SectionCard
            title={t("budget")}
            extra={
              <span className="ah-faint font-mono text-[12px]">
                {data.budget?.turns ?? 0} {t("turns")}
              </span>
            }
          >
            <BudgetGauge
              fill={data.budget?.fill ?? null}
              basis={data.budget?.basis}
              fired={data.budget?.fired}
              pending={data.budget?.pending}
              t={charts}
            />
          </SectionCard>

          <SectionCard title={t("objective")}>
            <Typography.Paragraph className="mb-0! text-[14px] leading-[1.7]">
              {b.objective || "—"}
            </Typography.Paragraph>
            {b.topics.length >= 2 && (
              <div className="mt-2 space-y-1.5 border-t border-[var(--ah-line)] pt-2">
                <span className="ah-label">{t("topicSegments")}</span>
                {b.topics.map((tp, i) => (
                  <div key={i} className="flex items-start gap-2 text-[12.5px]">
                    <span className="ah-inset min-w-[20px] px-1 text-center font-mono text-[11px]">{i + 1}</span>
                    <span className="min-w-0 flex-1 text-[var(--ah-text-1)]">{tp.opener}</span>
                    <span className="ah-faint shrink-0 font-mono">
                      {tp.messages} {t("msg")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          <div className="grid grid-cols-3 gap-3">
            <SectionCard title={`✓ ${t("done")}`} tone="ok">
              <Bullets items={b.state.done} />
            </SectionCard>
            <SectionCard title={`◐ ${t("inProgress")}`} tone="accent">
              <Bullets items={b.state.in_progress} />
            </SectionCard>
            <SectionCard title={`⚑ ${t("blockedOpen")}`} tone="err">
              <Bullets items={b.state.blocked} />
            </SectionCard>
          </div>

          <SectionCard title={t("keyDirectives")} extra={<span className="ah-warn ah-label">{t("mustObey")}</span>}>
            <Bullets items={b.directives} />
          </SectionCard>

          <SectionCard title={t("nextSteps")}>
            <Bullets items={b.next_steps} numbered />
          </SectionCard>

          {data.usage && (
            <SectionCard
              title={t("usage")}
              extra={
                <span className="ah-faint font-mono">
                  Σ {formatNum(data.usage.totals.tokens_in)}↓ {formatNum(data.usage.totals.tokens_out)}↑ ·{" "}
                  {data.usage.totals.calls} {t("calls")}
                </span>
              }
            >
              <div className="pb-3">
                <TokenBars models={data.usage.models} t={charts} />
              </div>
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
                  {
                    title: "cache",
                    key: "cache",
                    align: "right",
                    width: 110,
                    render: (_, r: { cache_write: number | null; cache_read: number | null }) =>
                      `${formatNum(r.cache_write)}/${formatNum(r.cache_read)}`,
                  },
                  {
                    title: t("ttft"),
                    dataIndex: "avg_ttft_ms",
                    align: "right",
                    width: 70,
                    render: (v: number | null) => (v != null ? `${(v / 1000).toFixed(1)}s` : "—"),
                  },
                  {
                    title: t("tokSpeed"),
                    dataIndex: "tok_per_s",
                    align: "right",
                    width: 80,
                    render: (v: number | null) => (v != null ? v.toFixed(0) : "—"),
                  },
                ]}
              />
            </SectionCard>
          )}

          <SectionCard
            title={`${t("transcript")}${data.compactions > 0 ? ` · ${data.compactions} × ${t("compactionNote")}` : ""}`}
            extra={
              data.compactions > 0 ? (
                <Tooltip title={t("compactionHint")}>
                  <span className="ah-warn ah-label">⚠ {t("compactionNote")}</span>
                </Tooltip>
              ) : undefined
            }
          >
            <div className="pb-2">
              <TurnTimeline
                messages={data.messages.filter((m) => m.role !== "compaction")}
                compactions={data.compactions}
                t={charts}
              />
            </div>
            {data.messages.length === 0 ? (
              <Typography.Text className="ah-meta italic">{t("noMessages")}</Typography.Text>
            ) : (
              <div className="max-h-[420px] overflow-y-auto pr-1">
                <ul className="m-0 list-none space-y-1.5 p-0">
                  {data.messages.map((m, i) =>
                    m.role === "compaction" ? (
                      <li key={i} className="ah-inset px-2.5 py-1.5 text-[12.5px]">
                        <span className="ah-warn">⚠ {t("compactionNote")}</span>{" "}
                        <span className="ah-meta">{m.text}</span>
                      </li>
                    ) : (
                      <li key={i}>
                        <TranscriptRow
                          m={m}
                          labels={{
                            user: t("user"),
                            assistant: t("assistant"),
                            expand: t("expand"),
                            collapse: t("collapse"),
                          }}
                        />
                      </li>
                    ),
                  )}
                </ul>
              </div>
            )}
          </SectionCard>

          <div className="grid grid-cols-2 gap-3">
            <SectionCard title={t("filesTouched")}>
              {b.files_touched.length === 0 ? (
                <Typography.Text className="ah-meta italic">{t("noRecord")}</Typography.Text>
              ) : (
                <ul className="m-0 list-none space-y-1 p-0 font-mono text-[12px]">
                  {b.files_touched.map((f) => (
                    <li key={f.path} className="flex items-baseline gap-2">
                      <span className="ah-meta min-w-0 flex-1 truncate" title={f.path}>
                        {f.path}
                      </span>
                      <span className="ah-faint shrink-0">×{f.hits}</span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
            <SectionCard title={t("contextNotes")}>
              <Bullets items={b.context_notes} />
            </SectionCard>
          </div>

          {b.tool_summary.length > 0 && (
            <SectionCard title={t("calls")}>
              <div className="flex flex-wrap gap-1.5">
                {b.tool_summary.map((tl) => (
                  <span key={tl.tool} className="ah-inset px-2 py-0.5 font-mono text-[12px]">
                    {tl.tool} <span className="ah-faint">{tl.calls}</span>
                  </span>
                ))}
              </div>
            </SectionCard>
          )}
        </div>

        {/* right: what you paste into the next session */}
        <div className="ah-side ah-scroll-x flex min-h-0 flex-col gap-3">
          <Card
            size="small"
            title={<span className="ah-label">{t("continuationBrief")}</span>}
            extra={<CopyButton text={data.brief} label={t("copyBrief")} />}
          >
            <pre className="ah-code ah-search-panel overflow-auto whitespace-pre-wrap break-words p-2.5 text-[12px] leading-relaxed">
              {data.brief}
            </pre>
          </Card>

          <Card
            size="small"
            title={<span className="ah-label">{t("resumeInCli")}</span>}
            extra={
              <span className={`ah-label ${launcher?.kind === "verified" ? "ah-ok" : "ah-warn"}`}>
                {launcher ? t(launcher.kind === "verified" ? "verified" : "unverified") : t("noLauncher")}
              </span>
            }
          >
            {launcher ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <code className="ah-code min-w-0 flex-1 truncate px-2 py-1.5 text-[12px]">
                    {launcher.command}
                  </code>
                  <CopyButton text={launcher.command} />
                </div>
                {launcher.headless && (
                  <p className="ah-meta mb-0">
                    {t("headless")}: <code>{launcher.headless}</code>
                  </p>
                )}
                {launcher.kind === "unverified" && (
                  <p className="ah-warn mb-0 text-[12.5px]">{t("unverifiedHint")}</p>
                )}
              </div>
            ) : (
              <Typography.Text className="ah-meta italic">{t("noVerifiedLauncher")}</Typography.Text>
            )}
          </Card>

          <Card size="small" title={<span className="ah-label">{t("sessionInfo")}</span>}>
            <Descriptions size="small" column={1} labelStyle={{ width: 96 }}>
              <Descriptions.Item label={t("sessions")}>
                <span className="font-mono text-[12px]">{meta.session_id}</span>
              </Descriptions.Item>
              <Descriptions.Item label="cwd">
                <span className="font-mono text-[12px] break-all">{meta.cwd}</span>
              </Descriptions.Item>
              <Descriptions.Item label={t("model")}>
                <span className="font-mono text-[12px]">{meta.model ?? "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label={t("provider")}>
                <span className="font-mono text-[12px]">{meta.provider ?? "—"}</span>
              </Descriptions.Item>
              {meta.origin && (
                <Descriptions.Item label="origin">
                  <span className="font-mono text-[12px]">{meta.origin}</span>
                </Descriptions.Item>
              )}
              {meta.parent_session_id && (
                <Descriptions.Item label={t("subSession")}>
                  <span className="font-mono text-[12px] break-all">{meta.parent_session_id}</span>
                </Descriptions.Item>
              )}
              {meta.tokens_in != null && (
                <Descriptions.Item label={t("tokensIn")}>
                  <span className="ah-num">{formatNum(meta.tokens_in)}</span>
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>
        </div>
      </div>
    </div>
  );
}
