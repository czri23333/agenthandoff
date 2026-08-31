import { Alert, App, Button, Card, Tooltip, Typography } from "antd";
import { useState } from "react";
import type { Interruption } from "./api";
import { formatNum, useT } from "./i18n";

/**
 * Shared cockpit atoms.
 *
 * Colour policy: nothing here picks a colour by name. Identity chips are driven
 * by `data-cli`, which theme.ts maps to AA-verified token triples out of
 * tokens.json — the fix for the shipped 1.1:1 white-on-#f2f2f2 agent badges.
 */

export function CliBadge({ cli, origin, title }: { cli: string; origin?: string | null; title?: string }) {
  const known = /^[$_.A-Za-z0-9-]+$/.test(cli);
  return (
    <span className="ah-chip" data-cli={known ? cli : "default"} title={title}>
      {cli}
      {origin && origin !== `.${cli}` && (
        <span className="ah-chip-dim">·{origin.replace(/^\./, "")}</span>
      )}
    </span>
  );
}

/** Proven end-state of a session, as an honest label (never a bare dot). */
export function StatusTag({ kind }: { kind: string | null }) {
  const t = useT();
  if (!kind)
    return (
      <Tooltip title={t("unknownEnd")}>
        <span className="ah-faint" aria-label={t("unknownEnd")}>
          ?
        </span>
      </Tooltip>
    );
  const tone =
    kind === "clean" ? "ah-ok" : kind === "user_pending" || kind === "cancelled" ? "ah-warn" : "ah-err";
  return (
    <Tooltip title={kind}>
      <span className={`ah-meta ${tone}`}>{t(`it_${kind}` as Parameters<typeof t>[0])}</span>
    </Tooltip>
  );
}

export function InterruptionBanner({ it }: { it: Interruption }) {
  const t = useT();
  if (!it || it.kind === "clean") return null;
  const label = t(`it_${it.kind}` as Parameters<typeof t>[0]);
  return (
    <Alert
      type={it.kind === "error" || it.kind === "context_exceeded" ? "error" : "warning"}
      showIcon
      message={`${t("interrupted")} — ${label}`}
      description={
        <>
          {it.detail && <div className="ah-meta">{it.detail}</div>}
          {it.kind === "user_pending" && it.pending_user_text && (
            <div className="ah-code mt-1.5 px-2 py-1.5 text-[12.5px]">
              <span className="ah-label">{t("pendingDirective")}</span>
              <div className="whitespace-pre-wrap break-words">{it.pending_user_text}</div>
            </div>
          )}
        </>
      }
    />
  );
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const { message } = App.useApp();
  const t = useT();
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      message.success(t("copied"));
      setTimeout(() => setDone(false), 1500);
    } catch {
      message.error(t("copyFailed"));
    }
  };
  return (
    <Button size="small" type={done ? "primary" : "default"} onClick={copy}>
      {done ? t("copiedShort") : (label ?? t("copy"))}
    </Button>
  );
}

export function SectionCard({
  title,
  extra,
  tone,
  children,
}: {
  title: React.ReactNode;
  extra?: React.ReactNode;
  tone?: "ok" | "accent" | "err";
  children: React.ReactNode;
}) {
  return (
    <Card
      size="small"
      title={<span className={`ah-label ${tone ? `ah-${tone}` : ""}`}>{title}</span>}
      extra={extra}
    >
      {children}
    </Card>
  );
}

export function Bullets({
  items,
  numbered = false,
  emptyKey = "noRecord",
}: {
  items: string[];
  numbered?: boolean;
  emptyKey?: "noRecord";
}) {
  const t = useT();
  if (!items.length)
    return (
      <Typography.Text type="secondary" className="ah-meta italic">
        {t(emptyKey)}
      </Typography.Text>
    );
  return (
    <ol className="m-0 list-none space-y-1.5 p-0">
      {items.map((s, i) => (
        <li key={i} className="flex items-start gap-2 text-[13px] leading-[1.6] text-[var(--ah-text-1)]">
          {numbered ? (
            <span className="ah-inset mt-0.5 min-w-[20px] px-1 text-center font-mono text-[12px] leading-5">
              {i + 1}
            </span>
          ) : (
            <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-[var(--ah-text-3)]" />
          )}
          <span className="min-w-0 break-words">{s}</span>
        </li>
      ))}
    </ol>
  );
}

/** Query highlight for search excerpts — marks without changing layout. */
export function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="ah-mark">{text.slice(idx, idx + q.length)}</mark>
      {text.slice(idx + q.length)}
    </>
  );
}

export function Metric({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <span className="ah-meta">
      {label} <span className="ah-num">{formatNum(value)}</span>
    </span>
  );
}
