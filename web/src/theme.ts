import { useMemo, useSyncExternalStore } from "react";
import { theme as antdAlgorithms, type ConfigProviderProps } from "antd";
import tokensJson from "./tokens.json";

/**
 * Theme engine: turns `tokens.json` (the single source of truth, WCAG-AA gated by
 * tests/test_tokens_contrast.py) into CSS custom properties plus the matching
 * antd ConfigProvider theme, so no component ever picks a colour by hand.
 *
 * Why not just use antd's dark algorithm: the cockpit mixes antd components with
 * hand-written Tailwind rows/chips. The shipped bug this replaces was exactly
 * that split — `Tag color="sky"` is not an antd preset in v6, so the zcode and
 * qodercn-ide badges rendered white text on a #f2f2f2 chip (1.1:1, unreadable).
 * Owning the CLI chips here makes identity colour a checked token instead.
 */

export type ThemeMode = "auto" | "dark" | "light";
export type Effective = "dark" | "light";

export interface CliInk {
  fg: string;
  bg: string;
  border: string;
}

export interface Palette {
  surface0: string;
  surface1: string;
  surface2: string;
  line: string;
  lineStrong: string;
  text1: string;
  text2: string;
  text3: string;
  accent: string;
  ok: string;
  warn: string;
  err: string;
  codeBg: string;
  placeholder: string;
  scheme: "dark" | "light";
  cli: Record<string, CliInk>;
}

const TOKENS = tokensJson as unknown as { themes: Record<Effective, Palette>; cli: string[] };
const KEY = "ah-theme";
const STYLE_ID = "ah-tokens";
const listeners = new Set<() => void>();

export const palettes = TOKENS.themes;
export const cliIds = TOKENS.cli;

/* -- css injection ---------------------------------------------------------- */

function cssVars(p: Palette): string {
  return [
    `color-scheme:${p.scheme};`,
    `--ah-surface-0:${p.surface0};`,
    `--ah-surface-1:${p.surface1};`,
    `--ah-surface-2:${p.surface2};`,
    `--ah-line:${p.line};`,
    `--ah-line-strong:${p.lineStrong};`,
    `--ah-text-1:${p.text1};`,
    `--ah-text-2:${p.text2};`,
    `--ah-text-3:${p.text3};`,
    `--ah-accent:${p.accent};`,
    `--ah-ok:${p.ok};`,
    `--ah-warn:${p.warn};`,
    `--ah-err:${p.err};`,
    `--ah-code-bg:${p.codeBg};`,
  ].join("");
}

function cliRules(name: Effective): string {
  const p = palettes[name];
  return Object.entries(p.cli)
    .map(
      ([cli, ink]) =>
        `:root[data-theme="${name}"] [data-cli="${cli}"]{` +
        `--ah-cli-fg:${ink.fg};--ah-cli-bg:${ink.bg};--ah-cli-border:${ink.border};}`,
    )
    .join("");
}

function injectStyles(): void {
  if (typeof document === "undefined") return;
  let el = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement("style");
    el.id = STYLE_ID;
    document.head.appendChild(el);
  }
  el.textContent =
    `:root[data-theme="dark"]{${cssVars(palettes.dark)}}` +
    `:root[data-theme="light"]{${cssVars(palettes.light)}}` +
    cliRules("dark") +
    cliRules("light");
}

/* -- mode store ------------------------------------------------------------- */

export function getThemeMode(): ThemeMode {
  if (typeof localStorage === "undefined") return "auto";
  const raw = localStorage.getItem(KEY);
  return raw === "dark" || raw === "light" || raw === "auto" ? raw : "auto";
}

export function systemTheme(): Effective {
  if (typeof window === "undefined" || !window.matchMedia) return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function effectiveTheme(mode: ThemeMode = getThemeMode()): Effective {
  return mode === "auto" ? systemTheme() : mode;
}

/** Apply mode to <html> + the token stylesheet. Safe to call before React mounts. */
export function applyTheme(mode: ThemeMode = getThemeMode()): Effective {
  const eff = effectiveTheme(mode);
  injectStyles();
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = eff;
    document.documentElement.dataset.themeMode = mode;
  }
  return eff;
}

export function setThemeMode(mode: ThemeMode): void {
  localStorage.setItem(KEY, mode);
  applyTheme(mode);
  listeners.forEach((fn) => fn());
  window.dispatchEvent(new Event("ah-theme-change"));
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const onSystem = () => {
    if (getThemeMode() !== "auto") return;
    applyTheme("auto");
    // A system flip changes the *effective* palette while the stored mode stays
    // "auto", so notify explicitly to keep antd in step with the CSS tokens.
    listeners.forEach((fn) => fn());
  };
  const media = typeof window !== "undefined" ? window.matchMedia?.("(prefers-color-scheme: dark)") : undefined;
  media?.addEventListener("change", onSystem);
  window.addEventListener("ah-theme-change", onSystem);
  return () => {
    listeners.delete(cb);
    media?.removeEventListener("change", onSystem);
    window.removeEventListener("ah-theme-change", onSystem);
  };
}

export function useThemeMode(): ThemeMode {
  return useSyncExternalStore(subscribe, getThemeMode, () => "auto" as ThemeMode);
}

/** Effective palette (resolves "auto" and follows live system changes). */
export function useTheme(): { mode: ThemeMode; effective: Effective; set: (m: ThemeMode) => void } {
  const mode = useThemeMode();
  const effective = useSyncExternalStore(subscribe, () => effectiveTheme(getThemeMode()), () => "dark" as Effective);
  return useMemo(() => ({ mode, effective, set: setThemeMode }), [mode, effective]);
}

/* -- antd bridge ------------------------------------------------------------ */

/** Shared accent so antd widgets and our own tokens never drift apart. */
const PRIMARY = "#5b8def";

export function antdConfig(effective: Effective): NonNullable<ConfigProviderProps["theme"]> {
  const p = palettes[effective];
  return {
    algorithm: effective === "dark" ? antdAlgorithms.darkAlgorithm : antdAlgorithms.defaultAlgorithm,
    token: {
      colorPrimary: PRIMARY,
      borderRadius: 8,
      // The tiers in tokens.json are AA-verified against our surfaces; antd's
      // defaults are not, and its *secondary* text is what most meta rows use.
      colorText: p.text1,
      colorTextSecondary: p.text2,
      colorTextTertiary: p.text2,
      colorTextQuaternary: p.text3,
      colorTextPlaceholder: p.placeholder,
      colorBgContainer: p.surface1,
      colorBgElevated: p.surface2,
      colorBgLayout: p.surface0,
      colorBorder: p.line,
      colorBorderSecondary: p.line,
      fontSize: 14,
    },
    components: {
      Layout: {
        headerBg: p.surface1,
        bodyBg: p.surface0,
        headerHeight: 52,
        headerPadding: "0 20px",
      },
      Card: { colorBgContainer: p.surface1, colorBorderSecondary: p.line },
      Table: {
        headerBg: p.surface2,
        headerColor: p.text2,
        rowHoverBg: p.surface2,
        colorBgContainer: p.surface1,
        borderColor: p.line,
      },
      Tag: {
        // Our chips are tokenised; keep antd's own tags legible too (the old bug
        // lived here — an unknown preset fell back to white-on-light-grey).
        defaultBg: p.surface2,
        defaultColor: p.text1,
      },
      Descriptions: { labelColor: p.text2 },
      Empty: { colorTextDescription: p.text2 },
      Input: { colorBgContainer: p.surface1, colorTextPlaceholder: p.placeholder },
      Select: { colorTextPlaceholder: p.placeholder },
      Typography: { colorText: p.text1, colorTextDescription: p.text2 },
    },
  };
}
