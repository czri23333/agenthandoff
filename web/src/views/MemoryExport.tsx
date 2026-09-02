import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Segmented, Switch, Table, Tag, Tooltip, Typography, message } from "antd";
import { CopyOutlined, DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import { api, type MemoryExportData, type MemoryReport } from "../api";
import { useT, type Lang } from "../i18n";

/**
 * Memory export as a page instead of a CLI invocation.
 *
 * Text-rendering rules applied here come from the L0–L7 font-stack doc
 * (docs/font-rendering-stack.md in the handoff brief): the browser owns
 * shaping/layout (L2–L5), but the app side still has to stay out of its way:
 *  - `.tx-user` carries `line-break: strict` (UAX #14 CJK kinsoku),
 *    `overflow-wrap: anywhere` for long paths, `unicode-bidi: isolate` so a
 *    stray RTL span cannot reorder the line, and `white-space: pre-wrap` so
 *    authored line breaks survive (L3).
 *  - Paths render in their own bidi isolate (L2/L4) — a `~/…` path next to
 *    CJK or RTL text must never participate in reordering.
 *  - Nothing in this view slices strings by code unit. The only truncation
 *    we allow is CSS `-webkit-line-clamp`, which breaks between rendered
 *    graphemes; any JS-side cut would use Intl.Segmenter (UAX #29), never
 *    `.slice()` — slicing can land inside an emoji ZWJ sequence or on a
 *    combining mark (L4).
 */

const CATEGORIES = ["instructions", "identity", "career", "projects", "preferences"] as const;

/** Status colours reuse the doctor palette: read is ok, everything the scan
 *  could not read keeps a warning tone — a missing store is news, not noise. */
const STATUS_TONE: Record<string, string> = {
  read: "green",
  "config-noted": "blue",
  missing: "default",
  unreadable: "orange",
  oversized: "orange",
};

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export default function MemoryExport() {
  const t = useT();
  const [data, setData] = useState<MemoryExportData | null>(null);
  const [lang, setLang] = useState<Lang>("zh");
  const [cli, setCli] = useState<string>("all");
  const [withProject, setWithProject] = useState(true);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .memoryExport({ cli: cli === "all" ? undefined : cli, withProject })
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [cli, withProject]);

  useEffect(() => {
    load();
  }, [load]);

  const cliOptions = useMemo(
    () => ["all", ...new Set((data?.reports ?? []).map((r) => r.cli).filter((c) => c !== "project"))],
    [data],
  );

  const markdown = lang === "zh" ? data?.markdown_zh ?? "" : data?.markdown_en ?? "";

  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      message.success(t("copied"));
    } catch {
      message.error(t("copyFailed"));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="ah-bar flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-2.5">
        <Typography.Text className="ah-meta">{t("memoryDesc")}</Typography.Text>
        <Segmented
          size="small"
          value={lang}
          onChange={(v) => setLang(v as Lang)}
          options={[
            { label: "中", value: "zh" },
            { label: "EN", value: "en" },
          ]}
        />
        <Segmented
          size="small"
          value={cli}
          onChange={(v) => setCli(String(v))}
          options={cliOptions.map((c) => ({ label: c === "all" ? t("allClis") : c, value: c }))}
        />
        <span className="ah-meta flex items-center gap-1.5">
          <Switch size="small" checked={withProject} onChange={setWithProject} />
          {t("memoryProjectFiles")}
        </span>
        <div className="ml-auto! flex items-center gap-2">
          <Button icon={<ReloadOutlined spin={loading} />} size="small" onClick={load}>
            {t("refresh")}
          </Button>
          <Button size="small" icon={<CopyOutlined />} disabled={!markdown} onClick={copyMarkdown}>
            {t("copy")} Markdown
          </Button>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            disabled={!markdown}
            onClick={() => download(`memory-export-${lang}.md`, markdown)}
          >
            .md
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!data && <Typography.Text className="ah-meta">{t("loading")}</Typography.Text>}
        {data && (
          <div className="flex flex-col gap-4">
            {data.secret_flags.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message={t("memorySecretTitle")}
                description={
                  <ul className="m-0 list-disc pl-5">
                    {data.secret_flags.map((f, i) => (
                      <li key={i} className="font-mono">
                        {f.label} @ {f.offset} ({f.length} chars)
                      </li>
                    ))}
                  </ul>
                }
              />
            )}

            <div className="grid gap-4 lg:grid-cols-2">
              {CATEGORIES.map((cat) => {
                const entries = data.entries.filter((e) => e.category === cat);
                return (
                  <section key={cat} className="rounded-lg border p-4" style={{ borderColor: "var(--ah-line)" }}>
                    <h3 className="mb-2 mt-0 text-sm font-semibold">
                      {lang === "zh" ? t(`memoryCat_${cat}`) : cat}
                      <span className="ah-meta ml-2 font-normal">{entries.length}</span>
                    </h3>
                    {entries.length === 0 ? (
                      <Typography.Text className="ah-meta">{t("memoryEmpty")}</Typography.Text>
                    ) : (
                      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                        {entries.map((e, i) => (
                          <li key={i} className="flex gap-2 text-[13px] leading-relaxed">
                            <span className="ah-meta shrink-0 whitespace-nowrap font-mono">
                              [{e.date === "unknown" ? t("memoryUnknown") : e.date}]
                            </span>
                            {/* dir="auto" + tx-user: the entry is the user's own
                                text in any script; we shape nothing ourselves. */}
                            <span dir="auto" className="tx-user min-w-0 flex-1">
                              <Tooltip title={`${e.source} ${e.path}`}>
                                <span className="ah-meta mr-1.5 font-mono" dir="auto" style={{ unicodeBidi: "isolate" }}>
                                  ({e.source})
                                </span>
                              </Tooltip>
                              {e.text}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                );
              })}
            </div>

            <section className="rounded-lg border p-4" style={{ borderColor: "var(--ah-line)" }}>
              <h3 className="mb-2 mt-0 text-sm font-semibold">{t("memorySources")}</h3>
              <Table<MemoryReport>
                size="small"
                rowKey={(r) => `${r.cli}:${r.path}`}
                dataSource={data.reports}
                pagination={false}
                columns={[
                  { title: "CLI", dataIndex: "cli", width: 110 },
                  {
                    title: "path",
                    dataIndex: "path",
                    render: (v: string) => (
                      <span className="font-mono" dir="auto" style={{ unicodeBidi: "isolate" }}>
                        {v}
                      </span>
                    ),
                  },
                  {
                    title: "status",
                    dataIndex: "status",
                    width: 130,
                    render: (v: string) => <Tag color={STATUS_TONE[v] ?? "default"}>{v}</Tag>,
                  },
                  { title: "entries", dataIndex: "entries", width: 80 },
                  {
                    title: "detail",
                    dataIndex: "detail",
                    render: (v: string) => (v ? <span className="ah-meta tx-user">{v}</span> : null),
                  },
                ]}
              />
            </section>

            <section className="rounded-lg border p-4" style={{ borderColor: "var(--ah-line)" }}>
              <h3 className="mb-2 mt-0 text-sm font-semibold">{t("memoryCompleteness")}</h3>
              <Typography.Paragraph className="tx-user !mb-0" style={{ color: "var(--ah-fg)" }}>
                {lang === "zh" ? data.completeness_zh : data.completeness_en}
              </Typography.Paragraph>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
