import { useState } from "react";
import type { Interruption } from "./api";

const CLI_COLORS: Record<string, string> = {
  zcode: "text-sky-300 border-sky-300/30 bg-sky-300/10",
  claude: "text-red-300 border-red-300/30 bg-red-300/10",
  codebuddy: "text-green-300 border-green-300/30 bg-green-300/10",
  "codebuddy-cn": "text-green-400 border-green-400/30 bg-green-400/10",
  qoderwork: "text-orange-300 border-orange-300/30 bg-orange-300/10",
  "qoderwork-cn": "text-orange-400 border-orange-400/30 bg-orange-400/10",
  "qodercn-ide": "text-amber-400 border-amber-400/30 bg-amber-400/10",
  qwenwork: "text-violet-300 border-violet-300/30 bg-violet-300/10",
  dsh: "text-cyan-300 border-cyan-300/30 bg-cyan-300/10",
  kimi: "text-purple-300 border-purple-300/30 bg-purple-300/10",
  codex: "text-indigo-300 border-indigo-300/30 bg-indigo-300/10",
};

export function CliBadge({ cli, origin }: { cli: string; origin?: string | null }) {
  const color = CLI_COLORS[cli] ?? "text-zinc-300 border-zinc-600/40 bg-zinc-800";
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-px font-mono text-[10px] ${color}`}>
      {cli}
      {origin && origin !== `.${cli}` && <span className="opacity-50">·{origin}</span>}
    </span>
  );
}

export const INTERRUPTION_STYLE: Record<string, { dot: string; label: string; note: string }> = {
  clean: { dot: "bg-emerald-400", label: "clean", note: "ended normally" },
  user_pending: { dot: "bg-orange-400 animate-pulse", label: "pending", note: "un-answered user instruction" },
  cancelled: { dot: "bg-yellow-400", label: "cancelled", note: "cancelled by user" },
  context_exceeded: { dot: "bg-red-400", label: "context", note: "context window exceeded" },
  length_truncated: { dot: "bg-red-400", label: "truncated", note: "reply cut by token limit" },
  error: { dot: "bg-red-500", label: "error", note: "model error" },
  unknown: { dot: "bg-zinc-400", label: "abrupt", note: "abrupt end" },
};

export function StatusDot({ kind }: { kind: string }) {
  const s = INTERRUPTION_STYLE[kind] ?? INTERRUPTION_STYLE.unknown;
  return <span title={s.label} className={`inline-block h-2 w-2 rounded-full ${s.dot}`} />;
}

export function InterruptionBanner({ it }: { it: Interruption }) {
  if (it.kind === "clean") return null;
  const s = INTERRUPTION_STYLE[it.kind] ?? INTERRUPTION_STYLE.unknown;
  return (
    <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-[13px] text-yellow-200">
      <span className="font-medium">Interrupted session</span> — {s.note}
      {it.detail && <span className="text-yellow-300/60"> · {it.detail}</span>}
      {it.kind === "user_pending" && it.pending_user_text && (
        <div className="mt-1 rounded bg-yellow-500/10 px-2 py-1 font-mono text-[12px]">
          pending instruction: {it.pending_user_text}
        </div>
      )}
    </div>
  );
}

export function CopyButton({ text, label = "copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {
          /* clipboard denied */
        }
      }}
      className="rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100"
    >
      {done ? "copied ✓" : label}
    </button>
  );
}

export function SectionCard({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900/50">
      <header className="flex items-center justify-between border-b border-zinc-800/70 px-3 py-2">
        <h3 className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">{title}</h3>
        {right}
      </header>
      <div className="px-3 py-2.5 text-[13px] leading-relaxed">{children}</div>
    </section>
  );
}

export function Bullets({ items, empty = "none recorded", numbered = false }: { items: string[]; empty?: string; numbered?: boolean }) {
  if (!items.length) return <p className="text-[12px] italic text-zinc-600">{empty}</p>;
  return (
    <ol className="space-y-1">
      {items.map((s, i) => (
        <li key={i} className="flex gap-2">
          {numbered ? (
            <span className="mt-px min-w-[16px] rounded bg-zinc-800 px-1 text-center font-mono text-[10px] leading-5 text-zinc-400">{i + 1}</span>
          ) : (
            <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-zinc-600" />
          )}
          <span className="break-words text-zinc-300">{s}</span>
        </li>
      ))}
    </ol>
  );
}
