import { useEffect, useState } from "react";
import { Alert, Button, Card, Descriptions, Segmented, Table, Tag, Tooltip, Typography } from "antd";
import { ExportOutlined } from "@ant-design/icons";
import {
  api,
  relTime,
  type Launcher,
  type SessionDetail as Detail,
  type TranscriptMessage,
} from "../api";
import { Bullets, CliBadge, CopyButton, InterruptionBanner, SectionCard, StatusTag } from "../components";
import { Markdown } from "../Markdown";
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
/** UAX #29 (L4 rule): never cut inside a grapheme cluster — emoji ZWJ
 * sequences and combining marks stay whole at the truncation boundary. */
function graphemeSlice(text: string, maxGraphemes: number): string {
  if (typeof Intl !== "undefined" && "Segmenter" in Intl) {
    const seg = new Intl.Segmenter(undefined, { granularity: "grapheme" });
    let out = "";
    let n = 0;
    for (const { segment } of seg.segment(text)) {
      if (n >= maxGraphemes) break;
      out += segment;
      n += 1;
    }
    return out;
  }
  return [...text].slice(0, maxGraphemes).join("");
}

/** Desktop Task chats link to the CLI session of the same work. */
function guessLinkedCli(_id: string, fromCli: string): string {
  if (fromCli === "qoderwork-cn-app") return "qoderwork-cn";
  if (fromCli === "qoderwork-app") return "qoderwork";
  if (fromCli === "qwenwork-app") return "qwenwork";
  return fromCli;
}

/**
 * Official-grade transcript row (WorkBuddy asar ground truth):
 * - user: right-aligned bubble (M3E large radius, sender corner cut)
 * - assistant: full-width column, transparent — avatar row above the text
 * - thinking ([思考] prefix): folded by default, tertiary 13px header
 * - tool call ([工具 name] line): card with header + args
 * - sub-agent call ([子代理 mark] line): nested block linked to the child
 * - timestamp: hover-only time tip, never standing text
 */
function TranscriptRow({
  m,
  labels,
  expert,
  cli,
  onOpenSub,
}: {
  m: TranscriptMessage;
  labels: {
    user: string;
    assistant: string;
    expand: string;
    collapse: string;
    raw: string;
    clean: string;
    thinking: string;
    toolCall: string;
    subagentCall: string;
    openSubagent: string;
  };
  expert?: { name?: string | null; avatar?: string | null };
  cli: string;
  onOpenSub?: (cli: string, sid: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [thinkOpen, setThinkOpen] = useState(false);
  const [toolOpen, setToolOpen] = useState(false);
  const text = m.text || "";
  const isThinking = text.startsWith("[思考]");
  const isTool = !isThinking && text.startsWith("[工具");
  const isSubagent = !isThinking && !isTool && text.startsWith("[子代理");
  const long = !isThinking && !isTool && !isSubagent && text.length > 500;
  const who = m.role === "user" ? labels.user : labels.assistant;
  const shown = showRaw && m.raw_text ? m.raw_text : text;
  // Elapsed-time cost proxy (store clocks): "3.2s" when the store kept no
  // token billing for this turn. Verifiable, never estimated.
  const durTip =
    typeof m.dur_ms === "number"
      ? m.dur_ms < 1000
        ? `${m.dur_ms}ms`
        : `${(m.dur_ms / 1000).toFixed(1)}s`
      : "";
  const timeTip = m.at ? new Date(m.at).toLocaleString() : "";
  const timeTipFull = durTip ? `${timeTip} · +${durTip}` : timeTip;

  // Cost chip priority: model+tokens > model > tokens > measured duration.
  // A turn with no token billing still shows its verifiable elapsed time —
  // every message carries visible cost evidence, never a blank.
  const hasTokens = typeof m.tokens_in === "number" || typeof m.tokens_out === "number";
  const modelChip = m.model || hasTokens ? (
    <span
      className="ah-inset mr-1.5 inline-flex items-center gap-1 px-1.5 py-px font-mono text-[11px]"
      title={`${m.model ?? "?"}${
        hasTokens
          ? ` · in=${m.tokens_in ?? "?"} out=${m.tokens_out ?? "?"}${
              typeof m.tokens_reasoning === "number" ? ` reason=${m.tokens_reasoning}` : ""
            }`
          : durTip
            ? ` · +${durTip} (no token billing in store)`
            : ""
      }`}
    >
      <span>{m.model ?? "?"}</span>
      {hasTokens ? (
        <span className="ah-faint">
          {typeof m.tokens_in === "number" ? `${m.tokens_in.toLocaleString()}↓` : ""}
          {typeof m.tokens_out === "number" ? ` ${m.tokens_out.toLocaleString()}↑` : ""}
        </span>
      ) : durTip ? (
        <span className="ah-faint">⏱ {durTip}</span>
      ) : null}
    </span>
  ) : durTip ? (
    <span
      className="ah-inset mr-1.5 inline-flex items-center gap-1 px-1.5 py-px font-mono text-[11px]"
      title={`no model/token billing in store · measured +${durTip}`}
    >
      <span className="ah-faint">⏱ {durTip}</span>
    </span>
  ) : null;

  const rawToggle = m.raw_text ? (
    <button
      className="ah-faint mr-1.5 font-mono text-[11px]"
      title={showRaw ? labels.clean : labels.raw}
      onClick={(e) => {
        e.stopPropagation();
        setShowRaw(!showRaw);
      }}
    >
      {showRaw ? labels.clean : labels.raw}
    </button>
  ) : null;

  // — user: right-aligned bubble —
  if (m.role === "user") {
    return (
      <div className="ah-user-row">
        <div className="flex max-w-full flex-col items-end">
          <div className="ah-user-bubble" dir="auto" title={timeTipFull}>
            <Markdown text={shown} />
          </div>
          <div className="mt-0.5 flex items-center gap-1.5">
            <span className="ah-time-tip font-mono" title={timeTipFull}>{durTip || timeTip}</span>
            {rawToggle}
          </div>
        </div>
      </div>
    );
  }

  // — thinking: folded block —
  if (isThinking) {
    const body = text.replace(/^\[思考\]\s?/, "");
    return (
      <div className="ah-assistant-row">
        <div className="ah-assistant-body">
          <div
            className="ah-reasoning"
            onClick={() => setThinkOpen(!thinkOpen)}
            title={thinkOpen ? labels.collapse : labels.expand}
          >
            <span className="mr-1 select-none">{thinkOpen ? "▾" : "▸"}</span>
            💭 {labels.thinking}
            {m.model || hasTokens || durTip ? (
              <span
                className="ah-inset ml-1.5 inline-flex items-center gap-1 px-1.5 py-px font-mono text-[11px]"
                title={
                  hasTokens
                    ? `${m.model ?? "?"} · in=${m.tokens_in ?? "?"} out=${m.tokens_out ?? "?"}`
                    : durTip
                      ? `${m.model ?? "?"} · +${durTip} (no token billing in store)`
                      : (m.model ?? "")
                }
              >
                <span>{m.model ?? "?"}</span>
                {hasTokens ? (
                  <span className="ah-faint">
                    {typeof m.tokens_in === "number" ? `${m.tokens_in.toLocaleString()}↓` : ""}
                    {typeof m.tokens_out === "number" ? ` ${m.tokens_out.toLocaleString()}↑` : ""}
                  </span>
                ) : durTip ? (
                  <span className="ah-faint">⏱ {durTip}</span>
                ) : null}
              </span>
            ) : null}
            <span className="ah-time-tip ml-1.5 font-mono" title={timeTipFull}>{durTip || timeTip}</span>
          </div>
          {thinkOpen && (
            <div className="ah-reasoning-content" dir="auto">
              <Markdown text={showRaw && m.raw_text ? m.raw_text : body} />
            </div>
          )}
          <div className="mt-0.5">{rawToggle}</div>
        </div>
      </div>
    );
  }

  // — tool call: card —
  if (isTool) {
    const nl = text.indexOf("\n");
    const head = (nl >= 0 ? text.slice(0, nl) : text).replace(/^\[工具\s?/, "").replace(/\]$/, "");
    const rest = nl >= 0 ? text.slice(nl + 1) : "";
    return (
      <div className="ah-assistant-row">
        <div className="ah-assistant-body">
          <div className="ah-toolcall">
            <button className="ah-toolcall-head" onClick={() => setToolOpen(!toolOpen)}>
              <span className="select-none">{toolOpen ? "▾" : "▸"}</span>
              <span>🔧 {head || labels.toolCall}</span>
              {m.subagent ? (
                <span className="ah-faint font-mono text-[11px]" title={m.subagent}>
                  ⌥ {m.subagent.replace(/^agent-/, "").slice(0, 8)}
                </span>
              ) : null}
              <span className="ah-time-tip ml-auto font-mono" title={timeTipFull}>{durTip || timeTip}</span>
            </button>
            {toolOpen && rest ? (
              <div className="ah-toolcall-body">
                <pre className="ah-toolcall-args" dir="auto">
                  {rest}
                </pre>
              </div>
            ) : null}
          </div>
          <div>
            {modelChip}
            {rawToggle}
          </div>
        </div>
      </div>
    );
  }

  // — sub-agent call: nested block linked to the child session —
  if (isSubagent) {
    // "[子代理 ✓] description → child-id"
    const body = text.replace(/^\[子代理\s?[✓…✗]?\]\s?/, "");
    const arrow = body.lastIndexOf(" → ");
    const desc = arrow >= 0 ? body.slice(0, arrow) : body;
    const childId = arrow >= 0 ? body.slice(arrow + 3).trim() : "";
    const looksLikeSid = /^[A-Za-z0-9_:-]{6,128}$/.test(childId);
    return (
      <div className="ah-assistant-row">
        <div className="ah-assistant-body">
          <div className="ah-subagent">
            <button className="ah-toolcall-head" onClick={() => setToolOpen(!toolOpen)}>
              <span className="select-none">{toolOpen ? "▾" : "▸"}</span>
              <span>
                👥 {labels.subagentCall} · {desc || who}
              </span>
              <span className="ah-time-tip ml-auto font-mono" title={timeTipFull}>{durTip || timeTip}</span>
            </button>
            <div className="ah-toolcall-body flex items-center gap-2">
              {modelChip}
              {looksLikeSid && onOpenSub ? (
                <button
                  className="ah-accent font-mono text-[12px]"
                  title={`${labels.openSubagent} · ${childId}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenSub(cli, childId);
                  }}
                >
                  → {childId.slice(0, 8)}…
                </button>
              ) : m.subagent ? (
                <span className="ah-faint font-mono text-[11px]" title={m.subagent}>
                  ⌥ {m.subagent.slice(0, 24)}
                </span>
              ) : null}
              {rawToggle}
            </div>
            {toolOpen && m.raw_text ? (
              <div className="ah-toolcall-body border-t border-[var(--ah-line)]">
                <pre className="ah-toolcall-args" dir="auto">
                  {m.raw_text.slice(0, 2000)}
                </pre>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  // — assistant: avatar row + transparent body —
  return (
    <div className="ah-assistant-row">
      <div className="ah-assistant-body">
        <div className="mb-1 flex items-center gap-1.5">
          <span className="ah-label flex select-none items-center" style={{ textTransform: "none" }}>
            {expert?.avatar ? (
              <img src={expert.avatar} alt="" className="mr-1 inline h-4 w-4 rounded-full align-[-2px]" loading="lazy" />
            ) : (
              <span className="mr-1">🤖</span>
            )}
            {expert?.name || who}
          </span>
          {m.subagent && (
            <span className="ah-accent px-1.5 py-px font-mono text-[11px]" title={m.subagent}>
              ⌥ {m.subagent.replace(/^agent-/, "").slice(0, 8)}
            </span>
          )}
          {modelChip}
          {rawToggle}
          <span className="ah-time-tip ml-auto font-mono" title={timeTipFull}>{durTip || timeTip}</span>
        </div>
        <div
          dir="auto"
          className="min-w-0 cursor-pointer break-words text-[var(--ah-text-1)]"
          onClick={() => long && setOpen(!open)}
          title={long ? (open ? labels.collapse : labels.expand) : undefined}
        >
          {open || !long ? (
            <Markdown text={shown} />
          ) : (
            <span className="tx-user whitespace-pre-wrap break-words">
              {`${graphemeSlice(shown, 500)}…`}
            </span>
          )}
        </div>
        {long && (
          <span className="ah-accent ml-1.5 select-none text-[12px]">
            {open ? `▲ ${labels.collapse}` : `▼ ${labels.expand} (${shown.length})`}
          </span>
        )}
      </div>
    </div>
  );
}

/** Paginated transcript: huge task sessions (4000+ turns) would freeze the
 * tab if every row mounted at once. Latest first page, older pages on demand
 * — the product loads history the same way. */
function TranscriptList({
  messages,
  page,
  moreLabel,
  row,
}: {
  messages: TranscriptMessage[];
  page: number;
  moreLabel: string;
  row: (m: TranscriptMessage, i: number) => React.ReactNode;
}) {
  // messages arrive newest-first; show the newest page, prepend older ones.
  const [pages, setPages] = useState(1);
  useEffect(() => setPages(1), [messages.length]);
  const shown = messages.slice(0, pages * page);
  const rest = messages.length - shown.length;
  return (
    <div className="max-h-[420px] overflow-y-auto pr-1">
      <ul className="m-0 list-none space-y-1.5 p-0">{shown.map((m, i) => row(m, i))}</ul>
      {rest > 0 && (
        <button
          onClick={() => setPages((n) => n + 1)}
          className="ah-faint w-full py-1.5 text-center font-mono text-[12px]"
        >
          {moreLabel} ({rest})
        </button>
      )}
    </div>
  );
}

export default function SessionDetail({
  cli,
  sid,
  onBack,
  onOpen,
}: {
  cli: string;
  sid: string;
  onBack: () => void;
  onOpen?: (cli: string, sid: string) => void;
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
  const [briefMode, setBriefMode] = useState<"summary" | "full">("summary");
  const [fullBrief, setFullBrief] = useState<{ brief: string; chars: number; turns: number } | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);

  // Lazy-fetch the lossless full brief the first time "全文" is selected.
  const selectBriefMode = (mode: "summary" | "full") => {
    setBriefMode(mode);
    if (mode === "full" && !fullBrief && !briefBusy) {
      setBriefBusy(true);
      api
        .brief(cli, sid, { lang, depth: "full" })
        .then(setFullBrief)
        .catch(() => setFullBrief(null))
        .finally(() => setBriefBusy(false));
    }
  };

  const shownBrief = briefMode === "full" && fullBrief ? fullBrief.brief : data?.brief ?? "";

  const downloadBrief = () => {
    const blob = new Blob([shownBrief], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `handoff-brief-${sid.slice(0, 8)}${briefMode === "full" ? "-full" : ""}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

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
      <div className="space-y-3 p-5">
        <Alert type="error" showIcon message={t("loading")} description={err} />
        <Button size="small" onClick={onBack}>
          ← {t("back")}
        </Button>
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
                    <span className="ah-inset min-w-[20px] px-1 text-center font-mono text-[12px]">{i + 1}</span>
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
                  {typeof data.usage.totals.cost_usd === "number" && (
                    <span className="ah-accent"> · ${data.usage.totals.cost_usd.toFixed(4)}</span>
                  )}
                </span>
              }
            >
              <div className="pb-3">
                <TokenBars models={data.usage.models} t={charts} />
              </div>
              {/* antd scrolls the table inside its own frame; leaving it out of
              the box pushed three columns past the viewport on a narrow window. */}
              <Table
                size="small"
                pagination={false}
                scroll={{ x: 620 }}
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
              <TranscriptList
                messages={data.messages}
                page={200}
                moreLabel={t("showMore")}
                row={(m, i) =>
                  m.role === "compaction" ? (
                    <li key={i} className="ah-inset px-2.5 py-1.5 text-[12.5px]">
                      <span className="ah-warn">⚠ {t("compactionNote")}</span>{" "}
                      <span className="ah-meta">{m.text}</span>
                    </li>
                  ) : (
                    <li key={i}>
                      <TranscriptRow
                        m={m}
                        expert={{ name: meta.expert_name, avatar: meta.expert_avatar }}
                        cli={cli}
                        onOpenSub={onOpen}
                        labels={{
                          user: t("user"),
                          assistant: t("assistant"),
                          expand: t("expand"),
                          collapse: t("collapse"),
                          raw: t("viewRaw"),
                          clean: t("viewClean"),
                          thinking: t("thinking"),
                          toolCall: t("toolCall"),
                          subagentCall: t("subagentCall"),
                          openSubagent: t("openSubagent"),
                        }}
                      />
                    </li>
                  )
                }
              />
            )}
          </SectionCard>

          <div className="grid grid-cols-2 gap-3">
            <SectionCard
              title={t("filesTouched")}
              extra={
                meta.attachments?.length ? (
                  <Tooltip title={t("attachmentsHint")}>
                    <span className="ah-label">📎 {meta.attachments.length}</span>
                  </Tooltip>
                ) : undefined
              }
            >
              {meta.attachments?.length ? (
                <ul className="m-0 mb-2 list-none space-y-1 border-b border-[var(--ah-line)] p-0 pb-2 font-mono text-[12px]">
                  {meta.attachments.map((a) => (
                    <li key={a} className="flex items-baseline gap-2">
                      <span title={t("attachment")}>📎</span>
                      <span className="min-w-0 flex-1 truncate text-[var(--ah-text-1)]" title={a}>
                        {a}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
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
            <SectionCard
              title={t("calls")}
              extra={
                data.tool_detail?.length ? (
                  <span className="ah-faint font-mono text-[12px]">
                    {data.tool_detail.length} {t("callRows")}
                  </span>
                ) : undefined
              }
            >
              <div className="flex flex-wrap gap-1.5">
                {b.tool_summary.map((tl) => (
                  <span key={tl.tool} className="ah-inset px-2 py-0.5 font-mono text-[12px]">
                    {tl.tool} <span className="ah-faint">{tl.calls}</span>
                  </span>
                ))}
              </div>
              {data.tool_detail?.length ? (
                <Table
                  size="small"
                  className="mt-2"
                  pagination={{ pageSize: 8, size: "small", showSizeChanger: false }}
                  rowKey={(_, i) => String(i)}
                  dataSource={data.tool_detail}
                  columns={[
                    { title: t("tool"), dataIndex: "tool", ellipsis: true },
                    {
                      title: t("status"),
                      dataIndex: "status",
                      width: 90,
                      render: (v: string | null, r) =>
                        r.error ? (
                          <Tooltip title={r.error}>
                            <Tag color="red" className="mr-0!">
                              {v ?? "error"}
                            </Tag>
                          </Tooltip>
                        ) : (
                          <Tag color={v === "completed" ? "green" : undefined} className="mr-0!">
                            {v ?? "—"}
                          </Tag>
                        ),
                    },
                    {
                      title: "ms",
                      dataIndex: "duration_ms",
                      align: "right" as const,
                      width: 70,
                      render: (v: number | null) => (v != null ? v.toLocaleString() : "—"),
                    },
                    {
                      title: "exit",
                      dataIndex: "exit_code",
                      align: "right" as const,
                      width: 60,
                      render: (v: number | null) =>
                        v == null || v === 0 ? (
                          <span className="ah-faint">{v ?? "—"}</span>
                        ) : (
                          <Tag color="red" className="mr-0!">
                            {v}
                          </Tag>
                        ),
                    },
                    {
                      title: "out",
                      dataIndex: "output_bytes",
                      align: "right" as const,
                      width: 80,
                      render: (v: number | null, r) => (
                        <span>
                          {v != null ? formatNum(v) : "—"}
                          {r.truncated ? <span className="ah-warn"> ✂</span> : null}
                        </span>
                      ),
                    },
                  ]}
                />
              ) : null}
            </SectionCard>
          )}
        </div>

        {/* right: what you paste into the next session */}
        <div className="ah-side ah-scroll-x flex min-h-0 flex-col gap-3">
          <Card
            size="small"
            title={
              <span className="flex items-center gap-2">
                <span className="ah-label">{t("continuationBrief")}</span>
                <Segmented
                  size="small"
                  value={briefMode}
                  onChange={(v) => selectBriefMode(v as "summary" | "full")}
                  options={[
                    { label: t("briefSummaryMode"), value: "summary" },
                    { label: t("briefFullMode"), value: "full" },
                  ]}
                />
              </span>
            }
            extra={
              <span className="flex items-center gap-1.5">
                <Button
                  size="small"
                  href={api.rawUrl(cli, sid)}
                  target="_blank"
                  title={t("rawArchiveTitle")}
                >
                  {t("downloadRaw")}
                </Button>
                <Button size="small" onClick={downloadBrief} disabled={!shownBrief}>
                  {t("downloadBrief")}
                </Button>
                <CopyButton text={shownBrief} label={t("copyBrief")} />
              </span>
            }
          >
            {briefMode === "full" && fullBrief && (
              <div className="ah-faint mb-1.5 font-mono text-[11px]">
                {t("fullBriefMeta")
                  .replace("{turns}", String(fullBrief.turns))
                  .replace("{chars}", fullBrief.chars.toLocaleString())}
              </div>
            )}
            <pre className="ah-code ah-search-panel overflow-auto whitespace-pre-wrap break-words p-2.5 text-[12px] leading-relaxed">
              {briefMode === "full"
                ? briefBusy
                  ? t("fullBriefLoading")
                  : fullBrief
                    ? fullBrief.brief
                    : t("fullBriefFailed")
                : data.brief}
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
                {meta.model ? (
                  <span className="font-mono text-[12px]">{meta.model}</span>
                ) : (
                  <Tooltip title={t("noModelHint")}>
                    <span className="ah-faint font-mono text-[12px]">{t("noModel")}</span>
                  </Tooltip>
                )}
              </Descriptions.Item>
              <Descriptions.Item label={t("provider")}>
                <span className="font-mono text-[12px]">{meta.provider ?? "—"}</span>
              </Descriptions.Item>
              {meta.origin && (
                <Descriptions.Item label="origin">
                  <span className="font-mono text-[12px]">{meta.origin}</span>
                </Descriptions.Item>
              )}
              {meta.task_type && (
                <Descriptions.Item label={t("taskKind")}>
                  <span className="font-mono text-[12px]">{meta.task_type}</span>
                </Descriptions.Item>
              )}
              {meta.title_source && (
                <Descriptions.Item label={t("titleSource")}>
                  <Tooltip title={t("titleSourceHint")}>
                    <span className="font-mono text-[12px]">{meta.title_source}</span>
                  </Tooltip>
                </Descriptions.Item>
              )}
              {meta.permission && (
                <Descriptions.Item label={t("permission")}>
                  <Tag color={meta.permission === "yolo" ? "red" : "blue"} className="mr-0 font-mono!">
                    {meta.permission}
                  </Tag>
                </Descriptions.Item>
              )}
              {meta.parent_session_id && (
                <Descriptions.Item label={t("subSession")}>
                  <span className="font-mono text-[12px] break-all">{meta.parent_session_id}</span>
                </Descriptions.Item>
              )}
              {meta.notes?.some((n) => n.startsWith("linked_cli_sessions:")) && (
                <Descriptions.Item label={t("linkedSessions")}>
                  <span className="flex flex-wrap gap-1">
                    {(meta.notes.find((n) => n.startsWith("linked_cli_sessions:")) ?? "")
                      .replace("linked_cli_sessions:", "")
                      .split(",")
                      .filter(Boolean)
                      .map((id) => (
                        <Button
                          key={id}
                          size="small"
                          type="link"
                          className="font-mono! text-[12px]"
                          onClick={() => onOpen?.(guessLinkedCli(id, meta.cli), id)}
                          title={t("linkedSessionsHint")}
                        >
                          {id.slice(0, 8)}
                        </Button>
                      ))}
                  </span>
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
