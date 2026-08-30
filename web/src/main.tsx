import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import App from "./App";
import { LangContext, getLang, useLang } from "./i18n";
import { antdConfig, applyTheme, useTheme } from "./theme";
import "./index.css";

// Ant Design provides the component foundation (states, spacing, a11y, focus
// rings). Language and palette are owned by our layers and mirrored into antd's
// ConfigProvider from the same tokens, so nothing can drift.
applyTheme(); // tokens + data-theme before first paint: no flash of wrong palette
document.documentElement.lang = getLang() === "zh" ? "zh-CN" : "en";

function Root() {
  const lang = useLang();
  const { effective } = useTheme();
  return (
    <ConfigProvider locale={lang === "zh" ? zhCN : enUS} theme={antdConfig(effective)}>
      <AntApp>
        <LangContext.Provider value={lang}>
          <App />
        </LangContext.Provider>
      </AntApp>
    </ConfigProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
