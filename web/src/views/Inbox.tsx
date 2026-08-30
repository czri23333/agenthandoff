import { useEffect, useState } from "react";
import { Alert, Button, Empty, List, Switch, Tag, Tooltip, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { api, type InboxItem } from "../api";
import { CliBadge, CopyButton } from "../components";
import { useT } from "../i18n";

export default function Inbox() {
  const t = useT();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [globalScope, setGlobalScope] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = async () => setItems(await api.inbox(globalScope));
  useEffect(() => {
    load();
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
      <div className="flex flex-wrap items-center gap-3 border-b border-zinc-800/70 px-5 py-2.5">
        <Typography.Text type="secondary" className="text-[12px]">{t("inboxDesc")}</Typography.Text>
        <div className="ml-auto flex items-center gap-3">
          <Tooltip title="跨项目交接箱：~/.agenthandoff">
            <span className="flex items-center gap-1.5 text-[11px] text-zinc-500">
              <Switch size="small" checked={globalScope} onChange={setGlobalScope} /> {t("global")}
            </span>
          </Tooltip>
          <Button icon={<ReloadOutlined spin={items === null} />} size="small" onClick={load}>
            {t("refresh")}
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {msg && <Alert type="error" showIcon message={msg} className="mb-3!" />}
        {items === null && <Skeleton active />}
        {items?.length === 0 && <Empty description={<span className="text-[12px]">{t("inboxEmpty")} <code>handoff publish &lt;bundle&gt;</code></span>} />}
        <List
          dataSource={items ?? []}
          renderItem={(it) => (
            <List.Item
              className="mb-1.5! rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3! py-2!"
              actions={[
                it.claimed ? (
                  <Tag key="c" className="mr-0! font-mono!">{t("claimed")} · {it.claimed_by}</Tag>
                ) : (
                  <Button key="c" size="small" color="green" variant="outlined" onClick={() => doClaim(it.path)}>
                    {t("claim")}
                  </Button>
                ),
                <CopyButton key="p" text={it.path} label="path" />,
              ]}
            >
              <List.Item.Meta
                avatar={<CliBadge cli={it.cli} />}
                title={<span className="text-[13px] text-zinc-200">{it.title}</span>}
                description={<span className="font-mono text-[11px] text-zinc-600">{it.published_at} · {it.session_id}</span>}
              />
            </List.Item>
          )}
        />
      </div>
    </div>
  );
}

function Skeleton({ active }: { active: boolean }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-11 animate-pulse rounded-lg bg-zinc-900" style={{ opacity: 1 - i * 0.12 }} />
      ))}
      {active ? null : null}
    </div>
  );
}
