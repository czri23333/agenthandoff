import { useEffect, useState, type ReactNode } from "react";
import { Alert, Button, List, Switch, Tooltip, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { api, relTime, type InboxItem } from "../api";
import { CliBadge, CopyButton, EmptyState } from "../components";
import { useT } from "../i18n";

/**
 * Published handoffs waiting to be claimed.
 *
 * A row can be in three states, and the difference matters to the agent reading
 * it: free (claim it), claimed (somebody took it), or leased (somebody is
 * working on it right now, and claiming will be refused until the lease expires).
 * The third one is only useful if it is visible, which is the point of this file.
 */
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
      // A held lease answers 409 with who holds it and until when. That text is
      // the useful message; "fetch failed" would hide the reason to wait.
      setMsg(String(e));
    }
  };

  const doRelease = async (path: string) => {
    try {
      await api.release(path, undefined, true);
      await load();
    } catch (e) {
      setMsg(String(e));
    }
  };

  const actionsFor = (it: InboxItem): ReactNode[] => {
    const actions: ReactNode[] = [];
    if (it.leased) {
      actions.push(
        <Tooltip key="l" title={t("leaseHint")}>
          <span className="ah-inset ah-warn px-2 py-0.5 font-mono text-[12px]">
            🔒 {t("leased")} · {it.lease_by} · {relTime(it.lease_until || null)}
          </span>
        </Tooltip>,
        <Button key="r" size="small" onClick={() => void doRelease(it.path)}>
          {t("release")}
        </Button>,
      );
    }
    actions.push(
      it.claimed ? (
        <span key="c" className="ah-inset px-2 py-0.5 font-mono text-[12px]">
          {t("claimed")} · {it.claimed_by}
        </span>
      ) : (
        <Button
          key="c"
          type="primary"
          onClick={() => void doClaim(it.path)}
        >
          {t("claim")}
        </Button>
      ),
      <CopyButton key="p" text={it.path} label="path" />,
    );
    return actions;
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
              <div key={i} className="ah-skeleton" />
            ))}
          </div>
        )}
        {/* One empty state, not two. `List` renders its own `locale.emptyText`
            when the data source is empty, so this page was drawing ours *and*
            antd's underneath — which only became obvious when ours stopped being
            antd's illustration too. */}
        {items?.length === 0 && (
          <EmptyState
            text={
              <>
                {t("inboxEmpty")} <code>handoff publish &lt;bundle&gt;</code>
              </>
            }
          />
        )}
        {/* The list is mounted only when it has rows. `List` paints its own
            `locale.emptyText` for an empty source and its `locale` prop does not
            accept `null`, so the page drew our empty state *and* the library's
            underneath — invisible while both were the library's illustration,
            obvious the moment one of them stopped being. */}
        {(items?.length ?? 0) > 0 && (
          <List
            dataSource={items ?? []}
            renderItem={(it) => (
            <List.Item
              /* `px-3!` used to be here, and an `!important` utility beats the
                 unlayered `.ah-row` rule — so this one row kept 12px leading
                 space while every other list item took ListTokens' 16. The
                 row's horizontal spacing belongs to `.ah-row` now. */
              className="ah-row mb-1.5! flex! items-center gap-3 py-2.5!"
              actions={actionsFor(it)}
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
        )}
      </div>
    </div>
  );
}
