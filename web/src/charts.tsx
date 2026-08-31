// Charts, drawn here rather than pulled in: three small SVG components, no new
// dependency, and every colour from the AA-verified token set (`--ah-*`), so a
// chart obeys the theme and the contrast gate the same way a table does.
//
// Two rules these follow, learned from the dark-mode audit:
//   * a shape is never the only information - the number is written next to it;
//   * no text below 12px, no fill that is only distinguishable by hue.

import { formatNum } from "./i18n";
import type { UsageModel, SessionMeta } from "./api";

const AXIS = "var(--ah-text-2)";
const GRID = "var(--ah-line)";
const INK = "var(--ah-text-1)";

export interface ChartLabels {
  tokensIn: string;
  tokensOut: string;
  model: string;
  calls: string;
  turns: string;
  user: string;
  assistant: string;
  compaction: string;
  budget: string;
  fired: string;
  pending: string;
  peak: string;
  perBucket: string;
  noData: string;
}

/** Horizontal bars with the value written beside them. */
export function TokenBars({ models, t }: { models: UsageModel[]; t: ChartLabels }) {
  const rows = models.filter((m) => (m.tokens_in || m.tokens_out || m.calls));
  if (!rows.length) return <Empty text={t.noData} />;
  const max = Math.max(...rows.map((m) => Math.max(m.tokens_in || 0, m.tokens_out || 0)), 1);
  const bar = (value: number, color: string) => (
    <div className="flex items-center gap-2">
      <div
        style={{
          height: 10,
          width: `${Math.max(2, (value / max) * 100)}%`,
          background: color,
          borderRadius: "var(--ah-radius, 3px)",
          minWidth: 2,
        }}
      />
      <span className="font-mono text-[12px]" style={{ color: AXIS }}>
        {formatNum(value)}
      </span>
    </div>
  );
  return (
    <div
      className="flex flex-col gap-2.5"
      role="img"
      aria-label={rows
        .map((m) => `${m.model} ${t.tokensIn} ${m.tokens_in} ${t.tokensOut} ${m.tokens_out}`)
        .join("; ")}
    >
      {rows.map((m) => (
        <div key={m.model} className="grid grid-cols-[minmax(80px,26%)_1fr] items-center gap-2">
          <span className="truncate text-[12px]" style={{ color: INK }} title={m.model}>
            {m.model}
            <span className="ml-1" style={{ color: AXIS }}>
              ×{formatNum(m.calls)}
            </span>
          </span>
          <div className="flex flex-col gap-1">
            {bar(m.tokens_in || 0, "var(--ah-accent)")}
            {bar(m.tokens_out || 0, "var(--ah-ok)")}
          </div>
        </div>
      ))}
      <div className="flex gap-4 pt-0.5 text-[12px]" style={{ color: AXIS }}>
        <LegendDot color="var(--ah-accent)" text={t.tokensIn} />
        <LegendDot color="var(--ah-ok)" text={t.tokensOut} />
      </div>
    </div>
  );
}

function LegendDot({ color, text }: { color: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span style={{ width: 9, height: 9, background: color, display: "inline-block" }} />
      {text}
    </span>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="py-2 text-[12px]" style={{ color: AXIS }}>
      {text}
    </div>
  );
}

const HOUR = 3600_000;

/**
 * When a session actually happened: user turns on the upper row, assistant turns
 * below, compactions as vertical marks. The shape that matters here is the gap -
 * a session that ends in a long silence, or one that was compacted twice in an
 * hour, reads differently from a transcript.
 */
export function TurnTimeline({
  messages,
  compactions = 0,
  t,
}: {
  messages: { role: string; at: string | null }[];
  compactions?: number;
  t: ChartLabels;
}) {
  const stamps = messages
    .map((m) => (m.at ? new Date(m.at).getTime() : null))
    .filter((v): v is number => v != null && !Number.isNaN(v))
    .sort((a, b) => a - b);
  if (stamps.length < 2) return <Empty text={t.noData} />;
  const first = stamps[0];
  const last = stamps[stamps.length - 1];
  const span = Math.max(last - first, 1);
  // One bar per bucket, per role: individual dots merge into blobs once a session
  // has more turns than pixels (1084 turns over 780px is 1.4 per pixel).
  const BINS = 72;
  const bins: { user: number; assistant: number }[] = Array.from({ length: BINS }, () => ({
    user: 0,
    assistant: 0,
  }));
  for (const m of messages) {
    if (!m.at) continue;
    const when = new Date(m.at).getTime();
    if (Number.isNaN(when)) continue;
    const index = Math.min(BINS - 1, Math.floor(((when - first) / span) * BINS));
    const bucket = bins[index];
    if (m.role === "user") bucket.user += 1;
    else if (m.role === "assistant") bucket.assistant += 1;
  }
  const peak = Math.max(1, ...bins.map((b) => Math.max(b.user, b.assistant)));
  const bar = (value: number, color: string) =>
    value ? (
      <div
        title={`${value}`}
        style={{
          width: "100%",
          height: `${Math.max(2, (value / peak) * 22)}px`,
          background: color,
          borderRadius: 1,
        }}
      />
    ) : (
      <span style={{ width: "100%", display: "inline-block" }} />
    );
  const hours = Math.round(span / HOUR);
  const fractions = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div
      role="img"
      aria-label={`${t.turns}: ${messages.length} · ${hours}h · ${t.peak} ${peak}`}
    >
      {/* Density rows: user turns above the axis, assistant turns below. */}
      <div className="flex h-[24px] items-end gap-px">
        {bins.map((b, i) => (
          <span key={`u${i}`} className="flex-1">{bar(b.user, "var(--ah-accent)")}</span>
        ))}
      </div>
      <div className="my-[3px] h-px w-full" style={{ background: GRID }} />
      <div className="flex h-[24px] items-start gap-px">
        {bins.map((b, i) => (
          <span key={`a${i}`} className="flex-1">{bar(b.assistant, "var(--ah-ok)")}</span>
        ))}
      </div>
      {/* Labels are HTML: inside a scaled viewBox, SVG text shrinks with the
          window and breaks the 12px floor the rest of the UI holds to. */}
      <div className="relative h-[16px]">
        {fractions.map((f) => (
          <span
            key={f}
            className="absolute font-mono text-[12px]"
            style={{ left: `${f * 96 + 1.5}%`, color: AXIS, transform: "translateX(-50%)" }}
          >
            {Math.round(hours * f)}h
          </span>
        ))}
      </div>
      <div className="flex flex-wrap gap-4 text-[12px]" style={{ color: AXIS }}>
        <LegendDot color="var(--ah-accent)" text={t.user} />
        <LegendDot color="var(--ah-ok)" text={t.assistant} />
        <span>
          {messages.length} {t.turns} · {t.perBucket}
        </span>
        {compactions > 0 && (
          <span>
            {t.compaction} ×{compactions}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * Context budget, the number that decides whether the next request dies. Rungs
 * are marked where `handoff watch` snapshots, so the gauge and the ladder say the
 * same thing.
 */
export function BudgetGauge({
  fill,
  basis,
  fired,
  pending,
  t,
}: {
  fill: number | null;
  basis?: string;
  fired?: string[];
  pending?: string[];
  t: ChartLabels;
}) {
  if (fill == null) return <Empty text={t.noData} />;
  const pct = Math.min(1, Math.max(0, fill)) * 100;
  const done = fired ?? [];
  const todo = pending ?? [];
  const color = pct >= 90 ? "var(--ah-err)" : pct >= 70 ? "var(--ah-warn)" : "var(--ah-ok)";
  return (
    <div role="img" aria-label={`${t.budget} ${pct.toFixed(0)}%`}>
      <div
        className="relative h-[14px] w-full overflow-hidden rounded-[3px]"
        style={{ background: "var(--ah-surface-2)", border: "1px solid var(--ah-line)" }}
      >
        <div style={{ width: `${pct}%`, height: "100%", background: color }} />
        {[20, 45, 70, 90].map((rung) => (
          <div
            key={rung}
            className="absolute top-0 h-full"
            style={{ left: `${rung}%`, width: 1, background: "var(--ah-line-strong)" }}
            title={`${rung}%`}
          />
        ))}
      </div>
      <div className="flex flex-wrap justify-between gap-2 pt-1 text-[12px]" style={{ color: AXIS }}>
        <span className="font-mono">
          {pct.toFixed(1)}%{basis ? ` · ${basis}` : ""}
        </span>
        <span>
          {done.length ? `${t.fired}: ${done.join(" ")}` : ""}
          {todo.length ? `${done.length ? " · " : ""}${t.pending}: ${todo.join(" ")}` : ""}
          {!done.length && !todo.length && fill < 0.2 ? `${t.pending}: ${t.noData}` : ""}
        </span>
      </div>
    </div>
  );
}

/** Sessions per CLI per day, last 14 days: which harness is carrying the work. */
export function ActivityGrid({ sessions, label }: { sessions: SessionMeta[]; label: string }) {
  const days = 14;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const clis = Array.from(new Set(sessions.map((s) => s.cli))).sort();
  if (!clis.length) return <Empty text={label} />;
  const buckets = new Map<string, number>();
  for (const s of sessions) {
    const when = s.updated_at ? new Date(s.updated_at).getTime() : NaN;
    if (Number.isNaN(when)) continue;
    const ago = Math.floor((today.getTime() - when) / 86_400_000);
    if (ago < 0 || ago >= days) continue;
    const key = `${s.cli}:${days - 1 - ago}`;
    buckets.set(key, (buckets.get(key) || 0) + 1);
  }
  const max = Math.max(1, ...buckets.values());
  return (
    <div role="img" aria-label={`${label} (${days}d)`}>
      <div className="grid gap-[3px]" style={{ gridTemplateColumns: `minmax(84px,22%) repeat(${days}, 1fr)` }}>
        {clis.map((cli) => (
          <div key={cli} className="contents">
            <span className="truncate self-center text-[12px]" style={{ color: AXIS }}>
              {cli}
            </span>
            {Array.from({ length: days }, (_, day) => {
              const hits = buckets.get(`${cli}:${day}`) || 0;
              return (
                <span
                  key={day}
                  title={`${cli} ${days - day}d: ${hits}`}
                  style={{
                    height: 12,
                    borderRadius: 2,
                    background: hits
                      ? `color-mix(in srgb, var(--ah-accent) ${25 + (hits / max) * 70}%, var(--ah-surface-2))`
                      : "var(--ah-surface-2)",
                    border: "1px solid var(--ah-line)",
                  }}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div className="pt-1 text-[12px]" style={{ color: AXIS }}>
        {`← ${days}d → now`}
      </div>
    </div>
  );
}
