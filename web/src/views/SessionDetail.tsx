import { useEffect, useState } from "react";
import { api, relTime, type Launcher, type SessionDetail as Detail, type TranscriptMessage } from "../api";
import { Bullets, CliBadge, CopyButton, InterruptionBanner, SectionCard } from "../components";
import { formatNum, useT } from "../i18n";

// One transcript turn. Long turns collapse to a preview; click to expand —
// a truncated history the user can't open is just a prettier lie.
function TranscriptRow({ m }: { m: TranscriptMessage }) {
  const [open, setOpen] = useState(false);
  const long = m.text.length > 500;
  return (
    <div
      className={`cursor-pointer rounded-lg px-2.5 py-1.5 text-[12px] ${m.role === "user" ? "bg-sky-500/10 text-sky-100" : "bg-zinc-800/50 text-zinc-300"}`}
      onClick={() => long && setOpen(!open)}
      title={long ? (open ? "点击收起" : "点击展开全文") : undefined}
    >
      <span className="mr-1.5 select-none font-mono text-[9px] uppercase text-zinc-500">
        {m.role === "user" ? "👤" : "🤖"}
      </span>
      <span className="whitespace-pre-wrap break-words">
        {open || !long ? m.text : `${m.text.slice(0, 500)}…`}
      </span>
      {long && (
        <span className="ml-1.5 select-none text-[10px] text-cyan-400/80">
          {open ? "收起" : `展开全文（${m.text.length} 字）`}
        </span>
      )}
    </div>
  );
}

export default function SessionDetail({ cli, sid, onBack }: { cli: string; sid: string; onBack: () => void }) {
  const t = useT();
  const [data, setData] = useState<Detail | null>(null);
  const [launcher, setLauncher] = useState<Launcher | null>(null);
  const [lang, setLang] = useState<"en" | "zh">("en");
  const [err, setErr] = useState("");
  const [pub, setPub] = useState("");

  useEffect(() => {
    setData(null);
    api.detail(cli, sid, lang).then(setData).catch((e) => setErr(String(e)));
    api.launcher(cli, sid).then(setLauncher).catch(() => setLauncher(null));
  }, [cli, sid, lang]);

  if (err) return <div className="p-5 text-[13px] text-red-400">{err}</div>;
  if (!data) return <div className="p-5 text-[13px] text-zinc-600">{t("loading")}</div>;
  const b = data.bundle;
  const meta = b.meta;

  const doPublish = async (scope: boolean) => {
    try {
      const r = await api.publish(cli, sid, undefined, scope);
      setPub(r.published);
    } catch (e) {
      setPub(String(e));
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-zinc-800/70 px-5 py-2.5">
        <button onClick={onBack} className="text-[12px] text-zinc-500 hover:text-zinc-200">← {t("back")}</button>
        <CliBadge cli={meta.cli} origin={meta.origin} />
        <span className="truncate text-[13px] text-zinc-200">{meta.title}</span>
        <span className="font-mono text-[11px] text-zinc-600">{relTime(meta.updated_at)}</span>
        {meta.provider && <span className="font-mono text-[10px] text-zinc-500" title="model route">⛽ {meta.provider}</span>}
        <div className="ml-auto flex items-center gap-2">
          <select value={lang} onChange={(e) => setLang(e.target.value as "en" | "zh")} className="rounded border border-zinc-800 bg-zinc-900 px-1.5 py-1 text-[11px]">
            <option value="en">{t("briefEn")}</option>
            <option value="zh">{t("briefZh")}</option>
          </select>
          <CopyButton text={data.markdown} label={t("copyBundle")} />
          <button onClick={() => doPublish(false)} className="rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700">
            {t("publish")}
          </button>
        </div>
      </div>
      {pub && <div className="truncate border-b border-zinc-800/70 bg-zinc-900/60 px-5 py-1 font-mono text-[11px] text-emerald-400/80">→ {pub}</div>}

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_380px] gap-4 overflow-hidden p-4">
        <div className="space-y-3 overflow-y-auto pr-1">
          <InterruptionBanner it={data.interruption} />

          <SectionCard title={t("objective")}>
            <p className="text-zinc-200">{b.objective || "(not captured)"}</p>
            {b.topics.length >= 2 && (
              <div className="mt-2 space-y-1 border-t border-zinc-800 pt-2">
                <p className="text-[11px] uppercase tracking-wider text-zinc-500">{t("topicSegments")}</p>
                {b.topics.map((tp, i) => (
                  <p key={i} className="text-[12px] text-zinc-400">
                    <span className="mr-1.5 rounded bg-zinc-800 px-1 font-mono text-[10px]">{i + 1}</span>
                    {tp.opener} <span className="text-zinc-600">({tp.messages} {t("msg")})</span>
                  </p>
                ))}
              </div>
            )}
          </SectionCard>

          <div className="grid grid-cols-3 gap-3">
            <SectionCard title={t("done")}><Bullets items={b.state.done} /></SectionCard>
            <SectionCard title={t("inProgress")}><Bullets items={b.state.in_progress} /></SectionCard>
            <SectionCard title={t("blockedOpen")}><Bullets items={b.state.blocked} /></SectionCard>
          </div>

          <SectionCard title={t("keyDirectives")} right={<span className="text-[10px] text-zinc-600">{t("mustObey")}</span>}>
            <Bullets items={b.directives} />
          </SectionCard>

          <SectionCard title={t("nextSteps")}>
            <Bullets items={b.next_steps} numbered />
          </SectionCard>

          {data.usage && (
            <SectionCard title={t("usage")} right={<span className="font-mono text-[10px] text-zinc-500">Σ {formatNum(data.usage.totals.tokens_in)}↓ {formatNum(data.usage.totals.tokens_out)}↑</span>}>
              <table className="w-full font-mono text-[11px]">
                <thead>
                  <tr className="text-left text-zinc-600">
                    <th className="pb-1 font-normal">{t("model")}</th>
                    <th className="pb-1 text-right font-normal">{t("calls")}</th>
                    <th className="pb-1 text-right font-normal">{t("tokensIn")}</th>
                    <th className="pb-1 text-right font-normal">{t("tokensOut")}</th>
                    <th className="pb-1 text-right font-normal">{t("reasoning")}</th>
                    <th className="pb-1 text-right font-normal" title="cache write / read">cache</th>
                    <th className="pb-1 text-right font-normal">{t("ttft")}</th>
                    <th className="pb-1 text-right font-normal">{t("tokSpeed")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.usage.models.map((m) => (
                    <tr key={m.model} className="border-t border-zinc-800/60 text-zinc-300">
                      <td className="max-w-40 truncate py-1" title={m.model}>{m.model}</td>
                      <td className="text-right">{m.calls}</td>
                      <td className="text-right">{formatNum(m.tokens_in)}</td>
                      <td className="text-right">{formatNum(m.tokens_out)}</td>
                      <td className="text-right text-zinc-500">{formatNum(m.reasoning)}</td>
                      <td className="text-right text-zinc-500" title={`${t("cacheWrite")} ${formatNum(m.cache_write)} / ${t("cacheRead")} ${formatNum(m.cache_read)}`}>
                        {formatNum(m.cache_write)}/{formatNum(m.cache_read)}
                      </td>
                      <td className="text-right">{m.avg_ttft_ms !== null ? `${(m.avg_ttft_ms / 1000).toFixed(1)}s` : "—"}</td>
                      <td className="text-right">{m.tok_per_s !== null ? m.tok_per_s.toFixed(0) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </SectionCard>
          )}

          <div className="grid grid-cols-2 gap-3">
            <SectionCard title={t("filesTouched")}>
              {b.files_touched.length === 0 ? (
                <p className="text-[12px] italic text-zinc-600">none recorded</p>
              ) : (
                <ul className="space-y-0.5 font-mono text-[11.5px] text-zinc-400">
                  {b.files_touched.map((f) => (
                    <li key={f.path} className="truncate" title={f.path}>`{f.path}` <span className="text-zinc-600">×{f.hits}</span></li>
                  ))}
                </ul>
              )}
            </SectionCard>
            <SectionCard title={t("contextNotes")}>
              <Bullets items={b.context_notes} />
            </SectionCard>
          </div>

          <SectionCard
            title={`${t("transcript")}${data.compactions > 0 ? ` · ${data.compactions} × 压缩` : ""}`}
            right={
              data.compactions > 0 ? (
                <span className="text-[10px] text-amber-400/90">⚠ 早期消息仅存摘要</span>
              ) : undefined
            }
          >
            {data.messages.length === 0 ? (
              <p className="text-[12px] italic text-zinc-600">{t("noMessages")}</p>
            ) : (
              <div className="max-h-96 space-y-2 overflow-y-auto">
                {data.messages.map((m, i) =>
                  m.role === "compaction" ? (
                    <div
                      key={i}
                      className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-center font-mono text-[10.5px] text-amber-300"
                      title="context compaction boundary"
                    >
                      ⚠ 上下文压缩 {m.text} —— 此边界之前的消息仅存模型摘要
                    </div>
                  ) : (
                    <TranscriptRow key={i} m={m} />
                  ),
                )}
              </div>
            )}
          </SectionCard>
        </div>

        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          <SectionCard
            title={t("continuationBrief")}
            right={<CopyButton text={data.brief} label={t("copyBrief")} />}
          >
            <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-zinc-950/80 p-2.5 font-mono text-[11px] leading-relaxed text-zinc-300">
              {data.brief}
            </pre>
          </SectionCard>

          <SectionCard title={t("resumeInCli")} right={<span className={`text-[10px] ${launcher?.kind === "verified" ? "text-emerald-500" : "text-yellow-600"}`}>{launcher ? t(launcher.kind === "verified" ? "verified" : "unverified") : t("noLauncher")}</span>}>
            {launcher ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded bg-zinc-950/80 px-2 py-1.5 font-mono text-[11.5px] text-cyan-300">{launcher.command}</code>
                  <CopyButton text={launcher.command} />
                </div>
                {launcher.headless && (
                  <p className="text-[11px] text-zinc-500">{t("headless")}: <code className="text-zinc-400">{launcher.headless}</code></p>
                )}
                {launcher.kind === "unverified" && (
                  <p className="text-[11px] text-yellow-600/80">{t("unverifiedHint")}</p>
                )}
              </div>
            ) : (
              <p className="text-[12px] italic text-zinc-600">{t("noVerifiedLauncher")}</p>
            )}
          </SectionCard>

          <SectionCard title={t("session")}>
            <dl className="space-y-1 font-mono text-[11px] text-zinc-500">
              <div className="truncate"><span className="text-zinc-600">id </span>{meta.session_id}</div>
              <div className="truncate"><span className="text-zinc-600">cwd </span>{meta.cwd}</div>
              <div><span className="text-zinc-600">model </span>{meta.model ?? "—"}</div>
              {meta.parent_session_id && <div className="truncate"><span className="text-zinc-600">parent </span>{meta.parent_session_id}</div>}
            </dl>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
