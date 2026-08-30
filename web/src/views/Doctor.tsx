import { useEffect, useState } from "react";
import { Button, Empty, Table, Tooltip, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { api, type StoreInfo } from "../api";
import { CliBadge } from "../components";
import { useT } from "../i18n";

/** Which CLI stores exist here and whether we can actually read them. */
export default function Doctor() {
  const t = useT();
  const [stores, setStores] = useState<StoreInfo[] | null>(null);

  const load = () => api.stores().then(setStores);
  useEffect(() => {
    load();
  }, []);

  const unreadable = (stores ?? []).filter((s) => !s.readable).length;

  return (
    <div className="flex h-full flex-col">
      <div className="ah-bar flex items-center gap-3 px-5 py-2.5">
        <Typography.Text className="ah-meta">{t("doctorDesc")}</Typography.Text>
        {unreadable > 0 && <span className="ah-warn ah-meta">{unreadable} {t("unreadable")}</span>}
        <Button icon={<ReloadOutlined spin={stores === null} />} size="small" className="ml-auto!" onClick={load}>
          {t("reprobe")}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {stores === null && <Typography.Text className="ah-meta">{t("loading")}</Typography.Text>}
        {stores?.length === 0 && <Empty description={<span className="ah-meta">{t("noStores")}</span>} />}
        {stores && stores.length > 0 && (
          <Table<StoreInfo>
            size="small"
            rowKey={(s) => `${s.cli}:${s.path}`}
            dataSource={stores}
            pagination={false}
            columns={[
              {
                title: "",
                width: 36,
                render: (_, s) => (
                  <span className={s.readable ? "ah-ok" : "ah-warn"} aria-label={s.readable ? "ok" : "unreadable"}>
                    {s.readable ? "●" : "○"}
                  </span>
                ),
              },
              {
                title: "CLI",
                dataIndex: "cli",
                width: 150,
                render: (v: string, s) => <CliBadge cli={v} origin={s.via_wsl ? "wsl" : null} />,
              },
              {
                title: "kind",
                dataIndex: "kind",
                width: 90,
                render: (v: string) => <span className="ah-meta font-mono">{v}</span>,
              },
              {
                title: "path",
                dataIndex: "path",
                ellipsis: true,
                render: (v: string) => (
                  <Tooltip title={v}>
                    <span className="ah-meta block truncate font-mono">{v}</span>
                  </Tooltip>
                ),
              },
              {
                title: "detail",
                dataIndex: "detail",
                width: 340,
                render: (v: string) => (
                  <Tooltip title={v}>
                    <span className="ah-meta block truncate">{v}</span>
                  </Tooltip>
                ),
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}
