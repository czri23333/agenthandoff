import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, theme, App as AntApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import App from "./App";
import "./index.css";

// Ant Design provides the enterprise-grade component foundation (states,
// spacing, a11y, notification). Language is owned by our i18n layer and
// mirrored into antd's ConfigProvider so tables/dates localize too.
function Root() {
  const [lang, setLang] = React.useState<"zh" | "en">(
    () => (localStorage.getItem("ah-lang") as "zh" | "en") || "zh",
  );
  React.useEffect(() => {
    const sync = () => setLang((localStorage.getItem("ah-lang") as "zh" | "en") || "zh");
    window.addEventListener("ah-lang-change", sync);
    return () => window.removeEventListener("ah-lang-change", sync);
  }, []);
  return (
    <ConfigProvider
      locale={lang === "zh" ? zhCN : enUS}
      theme={{ algorithm: theme.darkAlgorithm, token: { colorPrimary: "#5b8def", borderRadius: 8 } }}
    >
      <AntApp>
        <LangSetter setLang={setLang} />
        <App />
      </AntApp>
    </ConfigProvider>
  );
}

// App.tsx flips localStorage + dispatches the event; Root mirrors it into antd.
function LangSetter({ setLang }: { setLang: (l: "zh" | "en") => void }) {
  React.useEffect(() => {
    const sync = () => setLang((localStorage.getItem("ah-lang") as "zh" | "en") || "zh");
    window.addEventListener("ah-lang-change", sync);
    return () => window.removeEventListener("ah-lang-change", sync);
  }, []);
  return null;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
