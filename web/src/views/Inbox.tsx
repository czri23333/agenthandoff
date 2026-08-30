import { useEffect, useState } from "react";
import { Alert, Button, Empty, List, Switch, Tooltip, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { api, type InboxItem } from "../api";
import { CliBadge, CopyButton } from "../components";
import { useT } from "../i18n";

/** Published handoffs waiting to be claimed by another agent session. */
export default function Inbox() {
  const t = useT();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [globalScope, setGlobalScope] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = async () => setItems(await api.inbox(globalScope));
  useEffect(() => {
    load().catch((e) => setMsg(String(e)));
  }, [globalScope]);

  const doClaim = async (path: string) => {
    try {
      await api.claim(path);
      await load();
    } catch (e) {
      setMsg(String(e));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="ah-bar flex flex-wrap items-center gap-3 px-5 py-2.5">
        <Typography.Text className="ah-meta">{t("inboxDesc")}</Typography.Text>
        <div className="ml-auto flex items-center gap-3">
          <Tooltip title={t("globalHint")}>
            <span className="ah-meta flex items-center gap-1.5">
              <Switch size="small" checked={globalScope} onChange={setGlobalScope} /> {t("global")}
            </span>
          </Tooltip>
          <Button icon={<ReloadOutlined spin={items === null} />} size="small" onClick={() => void load()}>
            {t("refresh")}
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {msg && <Alert type="error" showIcon message={msg} className="mb-3!" closable onClose={() => setMsg(null)} />}
        {items === null && (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="ah-skeleton h-14" />
            ))}
          </div>
        )}
        {items?.length === 0 && (
          <Empty
            description={
              <span className="ah-meta">
                {t("inboxEmpty")} <code>handoff publish &lt;bundle&gt;</code>
              </span>
            }
          />
        )}
        <List
          dataSource={items ?? []}
          renderItem={(it) => (
            <List.Item
              className="ah-row mb-1.5! flex! items-center gap-3 px-3! py-2.5!"
              actions={[
                it.claimed ? (
                  <span key="c" className="ah-inset px-2 py-0.5 font-mono text-[12px]">
                    {t("claimed")} · {it.claimed_by}
                  </span>
                ) : (
                  <Button key="c" size="small" color="green" variant="outlined" onClick={() => void doClaim(it.path)}>
                    {t("claim")}
                  </Button>
                ),
                <CopyButton key="p" text={it.path} label="path" />,
              ]}
            >
              <List.Item.Meta
                avatar={<CliBadge cli={it.cli} />}
                title={<span className="ah-title">{it.title}</span>}
                description={
                  <span className="ah-faint font-mono">
                    {it.published_at} · {it.session_id}
                  </span>
                }
              />
            </List.Item>
          )}
        />
      </div>
    </div>
  );
}
