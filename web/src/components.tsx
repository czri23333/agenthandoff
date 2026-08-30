import { App, Badge, Button, Card, Tag, Typography } from "antd";
import { useState } from "react";
import type { Interruption } from "./api";

const CLI_COLORS: Record<string, string> = {
  zcode: "sky",
  claude: "red",
  codebuddy: "green",
  "codebuddy-cn": "lime",
  qoderwork: "orange",
  "qoderwork-cn": "gold",
  "qodercn-ide": "amber",
  qwenwork: "purple",
  dsh: "cyan",
  kimi: "magenta",
  codex: "geekblue",
};

export function CliBadge({ cli, origin }: { cli: string; origin?: string | null }) {
  const color = CLI_COLORS[cli] ?? "default";
  return (
    <Tag color={color} className="mr-0 font-mono!">
      {cli}
      {origin && origin !== `.${cli}` && <span className="opacity-60">·{origin.replace(".", "")}</span>}
    </Tag>
  );
}

export const INTERRUPTION_STYLE: Record<string, { badge: "success" | "warning" | "error" | "default"; label: string }> = {
  clean: { badge: "success", label: "正常结束" },
  user_pending: { badge: "warning", label: "有未执行的指令" },
  cancelled: { badge: "warning", label: "用户取消" },
  context_exceeded: { badge: "error", label: "上下文超限" },
  length_truncated: { badge: "error", label: "回复被截断" },
  error: { badge: "error", label: "模型错误" },
  unknown: { badge: "default", label: "异常结束" },
};

export function StatusDot({ kind }: { kind: string }) {
  const s = INTERRUPTION_STYLE[kind] ?? INTERRUPTION_STYLE.unknown;
  return <Badge status={s.badge} title={`${kind}: ${s.label}`} />;
}

export function InterruptionBanner({ it }: { it: Interruption }) {
  if (it.kind === "clean") return null;
  const s = INTERRUPTION_STYLE[it.kind] ?? INTERRUPTION_STYLE.unknown;
  return (
    <Alert
      type={it.kind === "error" || it.kind === "context_exceeded" ? "error" : "warning"}
      showIcon
      message={`会话曾中断 — ${s.label}`}
      description={
        <>
          {it.detail && <div className="text-[12px] opacity-70">{it.detail}</div>}
          {it.kind === "user_pending" && it.pending_user_text && (
            <div className="mt-1 rounded bg-black/20 px-2 py-1 font-mono text-[12px]">
              未执行的指令：{it.pending_user_text}
            </div>
          )}
        </>
      }
    />
  );
}

import { Alert } from "antd";

export function CopyButton({ text, label = "复制" }: { text: string; label?: string }) {
  const { message } = App.useApp();
  const [done, setDone] = useState(false);
  return (
    <Button
      size="small"
      type={done ? "primary" : "default"}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          message.success("已复制到剪贴板");
          setTimeout(() => setDone(false), 1500);
        } catch {
          message.error("复制失败：浏览器拒绝了剪贴板访问");
        }
      }}
    >
      {done ? "✓ 已复制" : label}
    </Button>
  );
}

export function SectionCard({
  title,
  extra,
  children,
}: {
  title: React.ReactNode;
  extra?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card size="small" title={<span className="text-[11px] tracking-wider">{title}</span>} extra={extra}>
      {children}
    </Card>
  );
}

export function Bullets({ items, numbered = false }: { items: string[]; numbered?: boolean }) {
  if (!items.length)
    return <Typography.Text type="secondary" className="text-[12px] italic">（无记录）</Typography.Text>;
  return (
    <ol className="space-y-1 pl-0 list-none m-0 p-0">
      {items.map((s, i) => (
        <li key={i} className="flex items-start gap-2 text-[13px] text-zinc-300">
          {numbered ? (
            <span className="mt-0.5 min-w-[18px] rounded bg-zinc-800 px-1 text-center font-mono text-[10px] leading-5 text-zinc-400">
              {i + 1}
            </span>
          ) : (
            <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-zinc-600" />
          )}
          <span className="break-words">{s}</span>
        </li>
      ))}
    </ol>
  );
}
