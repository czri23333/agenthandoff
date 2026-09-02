import { App } from "antd";
import { memo, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import { useT } from "./i18n";

/**
 * Rich markdown rendering for agent transcripts, in the spirit of the top
 * coding agents: GFM tables / task-lists / strikethrough, syntax-highlighted
 * code blocks with a copy button, all coloured from the cockpit theme tokens
 * so it reads well in both dark and light.
 *
 * The caller decides when to mount this (expanded / short messages) so a
 * transcript with hundreds of long turns stays fast.
 */

function CodeBlock({ children }: { children?: React.ReactNode }) {
  const { message } = App.useApp();
  const t = useT();
  const ref = useRef<HTMLPreElement>(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(ref.current?.textContent ?? "");
      message.success(t("copied"));
    } catch {
      message.error(t("copyFailed"));
    }
  };
  return (
    <div className="ah-codeblock group/code relative my-2">
      <button
        onClick={copy}
        className="ah-copybtn absolute right-1.5 top-1.5 rounded px-1.5 py-0.5 font-mono text-[11px] opacity-0 transition-opacity group-hover/code:opacity-100"
      >
        {t("copy")}
      </button>
      <pre ref={ref} className="overflow-x-auto rounded-md p-3 text-[12.5px] leading-relaxed">
        {children}
      </pre>
    </div>
  );
}

/** Memoized: parsing/highlighting a turn once and caching it is the L0-style
 * "render once, reuse" rule — expanding another row must not re-parse all. */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="ah-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          pre: CodeBlock,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer" className="ah-link">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
