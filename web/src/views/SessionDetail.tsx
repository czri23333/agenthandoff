import { useEffect, useState } from "react";
import { api, relTime, type Launcher, type SessionDetail as Detail } from "../api";
import { Bullets, CliBadge, CopyButton, InterruptionBanner, SectionCard } from "../components";

export default function SessionDetail({ cli, sid, onBack }: { cli: string; sid: string; onBack: () => void }) {
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
  if (!data) return <div className="p-5 text-[13px] text-zinc-600">loading…</div>;
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
        <button onClick={onBack} className="text-[12px] text-zinc-500 hover:text-zinc-200">← back</button>
        <CliBadge cli={meta.cli} origin={meta.origin} />
        <span className="truncate text-[13px] text-zinc-200">{meta.title}</span>
        <span className="font-mono text-[11px] text-zinc-600">{relTime(meta.updated_at)}</span>
        {meta.provider && <span className="font-mono text-[10px] text-zinc-500" title="model route">⛽ {meta.provider}</span>}
        <div className="ml-auto flex items-center gap-2">
          <select value={lang} onChange={(e) => setLang(e.target.value as "en" | "zh")} className="rounded border border-zinc-800 bg-zinc-900 px-1.5 py-1 text-[11px]">
            <option value="en">brief: en</option>
            <option value="zh">brief: zh</option>
          </select>
          <CopyButton text={data.markdown} label="copy bundle" />
          <button onClick={() => doPublish(false)} className="rounded-md border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-700">
            publish
          </button>
        </div>
      </div>
      {pub && <div className="truncate border-b border-zinc-800/70 bg-zinc-900/60 px-5 py-1 font-mono text-[11px] text-emerald-400/80">→ {pub}</div>}

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_380px] gap-4 overflow-hidden p-4">
        <div className="space-y-3 overflow-y-auto pr-1">
          <InterruptionBanner it={data.interruption} />

          <SectionCard title="objective">
            <p className="text-zinc-200">{b.objective || "(not captured)"}</p>
            {b.topics.length >= 2 && (
              <div className="mt-2 space-y-1 border-t border-zinc-800 pt-2">
                <p className="text-[11px] uppercase tracking-wider text-zinc-500">topic segments (mixed session)</p>
                {b.topics.map((t, i) => (
                  <p key={i} className="text-[12px] text-zinc-400">
                    <span className="mr-1.5 rounded bg-zinc-800 px-1 font-mono text-[10px]">{i + 1}</span>
                    {t.opener} <span className="text-zinc-600">({t.messages} msg)</span>
                  </p>
                ))}
              </div>
            )}
          </SectionCard>

          <div className="grid grid-cols-3 gap-3">
            <SectionCard title="done"><Bullets items={b.state.done} /></SectionCard>
            <SectionCard title="in progress"><Bullets items={b.state.in_progress} /></SectionCard>
            <SectionCard title="blocked / open"><Bullets items={b.state.blocked} /></SectionCard>
          </div>

          <SectionCard title="key user directives" right={<span className="text-[10px] text-zinc-600">must obey</span>}>
            <Bullets items={b.directives} />
          </SectionCard>

          <SectionCard title="next steps">
            <Bullets items={b.next_steps} numbered />
          </SectionCard>

          <div className="grid grid-cols-2 gap-3">
            <SectionCard title="files touched">
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
            <SectionCard title="context notes">
              <Bullets items={b.context_notes} />
            </SectionCard>
          </div>
        </div>

        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          <SectionCard
            title="continuation brief"
            right={<CopyButton text={data.brief} label="copy brief" />}
          >
            <pre className="max-h-[46vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-zinc-950/80 p-2.5 font-mono text-[11px] leading-relaxed text-zinc-300">
              {data.brief}
            </pre>
          </SectionCard>

          <SectionCard title="resume in cli" right={<span className={`text-[10px] ${launcher?.kind === "verified" ? "text-emerald-500" : "text-yellow-600"}`}>{launcher ? launcher.kind : "no launcher"}</span>}>
            {launcher ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded bg-zinc-950/80 px-2 py-1.5 font-mono text-[11.5px] text-cyan-300">{launcher.command}</code>
                  <CopyButton text={launcher.command} />
                </div>
                {launcher.headless && (
                  <p className="text-[11px] text-zinc-500">headless: <code className="text-zinc-400">{launcher.headless}</code></p>
                )}
                {launcher.kind === "unverified" && (
                  <p className="text-[11px] text-yellow-600/80">unverified on this machine — check the syntax before running.</p>
                )}
              </div>
            ) : (
              <p className="text-[12px] italic text-zinc-600">no verified launcher for this cli.</p>
            )}
          </SectionCard>

          <SectionCard title="session">
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
