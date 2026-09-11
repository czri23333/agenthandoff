import { Alert, App, Button, Empty, Tooltip, Typography } from "antd";
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
    kind === "clean" || kind === "completed"
      ? "ah-ok"
      : kind === "user_pending" || kind === "cancelled" || kind === "working"
        ? "ah-warn"
        : kind === "idle" || kind === "archived"
          ? "ah-faint"
          : "ah-err";
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
          {/* The engine's own words, labelled as such rather than dropped into a
              localized sentence. `detail` is diagnostic prose built by the
              parsers — `error_type=…`, `turn_end:…`, "newest message is an
              un-answered user instruction" — so it is shown verbatim and
              attributed; translating it would be inventing text the engine did
              not produce, and leaving it unattributed read as a missing
              translation in the Chinese UI. */}
          {it.detail && (
            <div className="ah-meta flex flex-wrap items-baseline gap-1.5">
              <span className="ah-label">{t("engineDetail")}</span>
              <span dir="auto">{it.detail}</span>
            </div>
          )}
          {it.kind === "user_pending" && it.pending_user_text && (
            <div className="ah-code mt-1.5 px-2 py-1.5 text-[12px]">
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
  // M3E: tonal header strip + large radius card. The tone tints only the
  // header (status at a glance); the body stays on the surface.
  // A status tone is carried by the *header's* ink and a 4px leading rule, not
  // by a saturated band across it. Measured before: a full-width
  // `--ah-ok-container` strip 30px tall reads as a solid green bar, which is the
  // loudest thing on the transcript screen and has no Material counterpart —
  // M3 tints a *container*, not a heading.
  const rule =
    tone === "ok"
      ? "ah-card__rule ah-card__rule--ok"
      : tone === "accent"
        ? "ah-card__rule ah-card__rule--accent"
        : tone === "err"
          ? "ah-card__rule ah-card__rule--err"
          : "";
  return (
    <div className="ah-card overflow-hidden">
      <div className={`ah-card__head ${rule}`}>
        <span className={`ah-label ${tone ? `ah-${tone}` : ""}`}>{title}</span>
        {extra}
      </div>
      <div className="ah-card__body">{children}</div>
    </div>
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
        <li key={i} className="flex items-start gap-2 text-[14px] leading-[1.6] text-[var(--ah-text-1)]">
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
/**
 * A status word in a tokenised tonal chip.
 *
 * Replaces antd's `Tag color="green"`, whose pair the theme algorithm derives
 * and nothing gates: measured at **3.37:1** in the light theme (`read`,
 * `rgb(56,158,13)` on `rgb(246,255,237)`), under the 4.5:1 this project
 * requires. Every tone below is a container the contrast test already gates
 * against `text1`, so the failure cannot come back unnoticed.
 */
export function StatusChip({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "ok" | "accent" | "warn" | "err";
  children: React.ReactNode;
}) {
  return <span className={`ah-tag ah-tag--${tone}`}>{children}</span>;
}
/**
 * An empty state: our mark in a container, not the component library's artwork.
 *
 * `Empty` on its own renders a 184×152 SVG supplied by antd, at a fixed 140px
 * height that is on no scale, carrying a `<title>` in antd's words — a second
 * announcement for a screen reader that already gets the description, and an
 * asset from a different design system inside a Material app. M3 publishes no
 * empty-state component, so this one is ours and is labelled as ours.
 */
export function EmptyState({
  text,
  icon,
  children,
}: {
  text: React.ReactNode;
  icon?: React.ReactNode;
  /** Rendered below the description — antd's `Empty` uses it as a footer slot. */
  children?: React.ReactNode;
}) {
  return (
    <Empty
      className="ah-empty"
      image={<span className="ah-empty__mark" aria-hidden="true">{icon ?? "◇"}</span>}
      description={<span className="ah-meta">{text}</span>}
    >
      {children}
    </Empty>
  );
}
