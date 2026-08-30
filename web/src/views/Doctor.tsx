import { useEffect, useState } from "react";
import { Badge, Button, Empty, Table, Tag, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { api, type StoreInfo } from "../api";
import { useT } from "../i18n";

export default function Doctor() {
  const t = useT();
  const [stores, setStores] = useState<StoreInfo[] | null>(null);

  const load = () => api.stores().then(setStores);
  useEffect(() => {
    load();
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-zinc-800/70 px-5 py-2.5">
        <Typography.Text type="secondary" className="text-[12px]">{t("doctorDesc")}</Typography.Text>
        <Button icon={<ReloadOutlined spin={stores === null} />} size="small" className="ml-auto!" onClick={load}>
          {t("reprobe")}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {stores === null && <Typography.Text type="secondary">{t("loading")}</Typography.Text>}
        {stores?.length === 0 && <Empty description={t("noStores")} />}
        {stores && stores.length > 0 && (
          <Table<StoreInfo>
            size="small"
            rowKey={(s) => `${s.cli}:${s.path}`}
            dataSource={stores}
            pagination={false}
            columns={[
              {
                title: "",
                width: 40,
                render: (_, s) => <Badge status={s.readable ? "success" : "default"} />,
              },
              { title: "CLI", dataIndex: "cli", width: 140, render: (v) => <span className="font-mono text-[12px]">{v}</span> },
              {
                title: "via",
                width: 70,
                render: (_, s) => (s.via_wsl ? <Tag color="purple" className="mr-0!">WSL</Tag> : null),
              },
              {
                title: "path",
                dataIndex: "path",
                ellipsis: true,
                render: (v) => <Typography.Text type="secondary" className="font-mono! text-[11px]" ellipsis={{ tooltip: v }}>{v}</Typography.Text>,
              },
              {
                title: "detail",
                dataIndex: "detail",
                width: 320,
                render: (v) => <span className="text-[11px] text-zinc-500">{v}</span>,
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}
