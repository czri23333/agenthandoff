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
  /** M3 tonal containers: semantic ink at low mix on the theme surface. */
  accentContainer: string;
  okContainer: string;
  warnContainer: string;
  errContainer: string;
  cli: Record<string, CliInk>;
}

/** M3 shape scale (px), from tokens.json. `full` is Google's corner-full. */
export interface ShapeScale {
  xs: number;
  sm: number;
  md: number;
  lg: number;
  xl: number;
  full: number;
}

/** Google's composed corners, derived in the generator from the shape scale. */
export interface ComposedCorners {
  corners: Record<
    "extra-small-top" | "large-top" | "large-start" | "large-end" | "extra-large-top",
    string
  >;
}

/**
 * M3 interaction state: the opacity of a surface's own content colour composited
 * over it. Google's four, plus the disabled pair (which M3 publishes only as
 * prose, so those two numbers are ours).
 */
export interface StateTokens {
  opacity: Record<string, number>;
  disabled: Record<string, number>;
}

/** M3 elevation: official dp levels and the MDC-Web box-shadow for each. */
export interface ElevationTokens {
  levels: Record<string, number>;
  shadow: Record<string, string>;
}

/**
 * Google's full M3 baseline colour scheme. `roles` is the resolved output of the
 * official role→tone mapping (`_md-sys-color.scss`) over the official tones
 * (`_md-ref-palette.scss`); the generator stores the *references*, so this is the
 * derived half and `tokens.json` is the auditable half.
 */
export interface ColorRoleTokens {
  tones: Record<string, Record<string, string>>;
  roles: Record<Effective, Record<string, string>>;
}

/** M3 type roles, with Google's size / line-height / tracking / weight. */
export interface TypescaleTokens {
  cjkFloor: number;
  roles: Record<
    string,
    { size: number; line: number; tracking: number; weight: number; mono_only?: boolean }
  >;
}

/**
 * Per-component anatomy, from tokens.json. Every value here is Google's, and
 * every nestable one is a *reference* the generator already validated, keeping
 * its kind as a prefix so this file can switch on it instead of guessing:
 *
 *   role:<name>   → var(--ah-<name>)                        (official colour role)
 *   type:<role>   → var(--ah-type-<role>-{size,line,tracking,weight})
 *   elev:<level>  → var(--ah-elevation-<level>)             (a shadow recipe)
 *   corner:<name> → var(--ah-corner-<name>)                 (a composed corner)
 *   spring:<name> → var(--ah-spring-<name>-{duration,easing})
 *
 * A plain integer is px; a plain fraction in (0, 1) is an opacity and is emitted
 * as a percentage, because the only thing that spends one is `color-mix`. The
 * generator's gate asserts both halves of that convention (every fraction is in
 * (0, 1), every length is an integer), and the consumption gate — mirrored in
 * `tests/test_tokens_components.py` — refuses a `--ah-c-*` custom property that
 * `m3.css` reads but this function never emits, or emits but nothing reads.
 */
export interface ComponentTokens {
  [family: string]: unknown;
}

/**
 * M3E motion contract, from tokens.json. Durations and the standard/emphasized/
 * linear easings are Google's (material-web v0_192). `spring` is Google's M3E
 * motion scheme (androidx material3 tokens v0_14_0) realised for the web: the
 * official damping/stiffness pair, the `linear()` easing sampled from it, that
 * sample's settle time, and a cubic-bezier `fallback` for engines without
 * `linear()`. Nothing in the app writes a duration or a curve by hand: components
 * read these as `--ah-motion-*` custom properties, which is what makes a motion
 * change a token change (and therefore reviewable and gate-checked).
 */
export interface MotionTokens {
  duration: Record<string, string>;
  easing: Record<string, string>;
  stagger: Record<string, string>;
  spring: Record<
    string,
    { damping: number; stiffness: number; duration: string; easing: string; fallback: string }
  >;
}

/* The token *names* are a closed set, so a typo must not compile. Typing these
   from the imported JSON rather than as `string` is the difference between
   `dur("short-4")` being an error and it silently shipping an empty duration to
   antd and `transition: … var(--ah-motion-duration-short-4, )` to CSS. */
type DurationName = keyof (typeof tokensJson)["motion"]["duration"];
type EasingName = keyof (typeof tokensJson)["motion"]["easing"];
type SpringName = keyof (typeof tokensJson)["motion"]["spring"];
type TypeRole = keyof (typeof tokensJson)["typescale"]["roles"];
type ElevationLevel = keyof (typeof tokensJson)["elevation"]["levels"];

/**
 * camelCase token keys become kebab-case custom properties (`oneLine` →
 * `one-line`, `shapePressed` → `shape-pressed`), so every `--ah-c-*` name in the
 * stylesheet is lower-case and a `.` in the token path is always a `-` in the
 * property. `tests/test_tokens_components.py` applies the same transform, which
 * is what makes the consumption gate a comparison rather than an opinion.
 */
function kebab(key: string): string {
  return key.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
}

const TOKENS = tokensJson as unknown as {
  themes: Record<Effective, Palette>;
  cli: string[];
  colorRoles: ColorRoleTokens;
  shape: ShapeScale;
  shapeComposed: ComposedCorners;
  state: StateTokens;
  elevation: ElevationTokens;
  typescale: TypescaleTokens;
  component: ComponentTokens;
  motion: MotionTokens;
};
const KEY = "ah-theme";
const STYLE_ID = "ah-tokens";
const listeners = new Set<() => void>();

export const palettes = TOKENS.themes;
export const cliIds = TOKENS.cli;
export const shape = TOKENS.shape;
export const motion = TOKENS.motion;
/** Named duration, e.g. `dur("short3")` → `150ms`. Unknown names do not compile. */
export function dur(name: DurationName): string {
  return motion.duration[name];
}
/** Named curve, e.g. `curve("emphasized")`. */
export function curve(name: EasingName): string {
  return motion.easing[name];
}
/** A spring's settle duration, sampled easing and fallback bezier. */
export function spring(name: SpringName) {
  return motion.spring[name];
}
/** A type role's size / line-height / tracking / weight, e.g. `typeRole("body-small")`. */
export function typeRole(name: TypeRole) {
  return TOKENS.typescale.roles[name];
}
/** An elevation level's box-shadow, e.g. `elevation("level2")` (level0 is `none`). */
export function elevation(level: ElevationLevel): string {
  return TOKENS.elevation.shadow[level];
}

/* -- css injection ---------------------------------------------------------- */

/** 0.08 → "8%": state opacities are stored as fractions, CSS wants a percentage. */
function pct(fraction: number): string {
  return `${Number((fraction * 100).toFixed(2))}%`;
}

/**
 * The theme-independent half of the contract: shape, state layers, elevation,
 * the type scale and motion. These do not change with the palette, so they are
 * injected once on `:root` instead of being duplicated inside both theme blocks.
 */
function contractVars(): string {
  return [
    `--ah-shape-xs:${shape.xs}px;`,
    `--ah-shape-sm:${shape.sm}px;`,
    `--ah-shape-md:${shape.md}px;`,
    `--ah-shape-lg:${shape.lg}px;`,
    `--ah-shape-xl:${shape.xl}px;`,
    `--ah-shape-full:${shape.full}px;`,
    ...Object.entries(TOKENS.shapeComposed.corners).map(([k, v]) => `--ah-corner-${k}:${v};`),
    ...Object.entries(TOKENS.state.opacity).map(([k, v]) => `--ah-state-${k}:${pct(v)};`),
    ...Object.entries(TOKENS.state.disabled).map(([k, v]) => `--ah-state-disabled-${k}:${pct(v)};`),
    ...Object.entries(TOKENS.elevation.shadow).map(([k, v]) => `--ah-elevation-${k}:${v};`),
    ...Object.entries(TOKENS.typescale.roles).flatMap(([role, r]) => [
      `--ah-type-${role}-size:${r.size}px;`,
      `--ah-type-${role}-line:${r.line}px;`,
      `--ah-type-${role}-tracking:${r.tracking}px;`,
      `--ah-type-${role}-weight:${r.weight};`,
    ]),
    `--ah-type-cjk-floor:${TOKENS.typescale.cjkFloor}px;`,
    ...Object.entries(motion.duration).map(([k, v]) => `--ah-motion-duration-${k}:${v};`),
    ...Object.entries(motion.easing).map(([k, v]) => `--ah-motion-easing-${k}:${v};`),
    ...Object.entries(motion.stagger).map(([k, v]) => `--ah-motion-stagger-${k}:${v};`),
    ...Object.entries(motion.spring).flatMap(([name, s]) => [
      `--ah-spring-${name}-duration:${s.duration};`,
      `--ah-spring-${name}-easing:${s.easing};`,
      `--ah-spring-${name}-fallback:${s.fallback};`,
    ]),
    componentVars(),
  ].join("");
}

/**
 * Flatten `tokens.json`'s `component` block into `--ah-c-<path>` custom
 * properties, resolving the references the generator validated. The path is the
 * token path verbatim (`component.button.sizes.small.height` →
 * `--ah-c-button-sizes-small-height`) so a value in the stylesheet can always be
 * traced back to a line of the token file by reading its own name.
 */
function componentVars(): string {
  const out: string[] = [];
  const walk = (node: unknown, path: string[]): void => {
    if (node !== null && typeof node === "object" && !Array.isArray(node)) {
      for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
        // `_source` / `_readme` are documentation, not values.
        if (key.startsWith("_")) continue;
        walk(value, [...path, key]);
      }
      return;
    }
    if (node === null || node === undefined) return;
    const name = `--ah-c-${path.map(kebab).join("-")}`;
    if (typeof node === "number") {
      out.push(
        Number.isInteger(node)
          ? `${name}:${node}px;`
          : `${name}:${Number((node * 100).toFixed(2))}%;`,
      );
      return;
    }
    if (typeof node !== "string") return;
    const [kind, target] = node.split(":", 2);
    switch (kind) {
      case "role":
        out.push(`${name}:var(--ah-${target});`);
        break;
      case "elev":
        out.push(`${name}:var(--ah-elevation-${target});`);
        break;
      case "corner":
        out.push(`${name}:var(--ah-corner-${target});`);
        break;
      case "type":
        out.push(
          `${name}-size:var(--ah-type-${target}-size);`,
          `${name}-line:var(--ah-type-${target}-line);`,
          `${name}-tracking:var(--ah-type-${target}-tracking);`,
          `${name}-weight:var(--ah-type-${target}-weight);`,
        );
        break;
      case "spring":
        out.push(
          `${name}-duration:var(--ah-spring-${target}-duration);`,
          `${name}-easing:var(--ah-spring-${target}-easing);`,
        );
        break;
      default:
        // Throwing here is deliberate: the only way to reach it is a token the
        // generator emitted with a reference kind this switch does not know, and
        // a silent skip would ship a component reading an undefined property.
        throw new Error(`component token ${path.join(".")}: unknown kind in ${node}`);
    }
  };
  walk(TOKENS.component, []);
  return out.join("");
}

function cssVars(p: Palette): string {
  return [
    `color-scheme:${p.scheme};`,
    // Every official M3 role, under its own name, so a component can reach for
    // `--ah-primary-container` instead of inventing a mix (the semantic names
    // below are aliases onto these — see the mapping in gen_tokens.py).
    ...Object.entries(TOKENS.colorRoles.roles[p.scheme as Effective]).map(
      ([role, hex]) => `--ah-${role}:${hex};`,
    ),
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
    `--ah-accent-container:${p.accentContainer};`,
    `--ah-ok-container:${p.okContainer};`,
    `--ah-warn-container:${p.warnContainer};`,
    `--ah-err-container:${p.errContainer};`,
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
    `:root{${contractVars()}}` +
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

/**
 * Read a component token out of the generated block, e.g.
 * `num("button.sizes.small.height")`. Throws instead of defaulting: a fallback
 * would turn a renamed token into a control that renders at antd's default size
 * and looks *almost* right, which is the failure mode this slice exists to
 * remove. `tokens.json` is generated and `--check`-gated, so reaching the throw
 * means the generator and this file disagree — a bug, not a runtime condition.
 */
function dig(path: string): unknown {
  let node: unknown = TOKENS.component;
  for (const key of path.split(".")) {
    if (node === null || typeof node !== "object") return undefined;
    node = (node as Record<string, unknown>)[key];
  }
  return node;
}

function num(path: string): number {
  const value = dig(path);
  if (typeof value !== "number") {
    throw new Error(`component token ${path} is not a number: ${JSON.stringify(value)}`);
  }
  return value;
}

/** A px length from a component token, e.g. `px("appBar.small.height")` → "64px". */
function px(path: string): string {
  return `${num(path)}px`;
}

/** The 49 official colour roles for a theme, by role name. */
function roles(effective: Effective): Record<string, string> {
  return TOKENS.colorRoles.roles[effective];
}

/**
 * The official state layer at a component's own opacity, composed over whatever
 * the element already paints. M3 defines feedback as this composition, never as
 * a different background or a filter, and antd exposes several "hover
 * background" tokens — so they take this string rather than a colour.
 */
function layer(role: string, opacityToken: string): string {
  return `color-mix(in srgb, ${role} var(${opacityToken}), transparent)`;
}

export function antdConfig(effective: Effective): NonNullable<ConfigProviderProps["theme"]> {
  const p = palettes[effective];
  const r = roles(effective);
  const stateHover = "--ah-state-hover";
  return {
    algorithm: effective === "dark" ? antdAlgorithms.darkAlgorithm : antdAlgorithms.defaultAlgorithm,
    token: {
      // The accent is the official primary role, not a hand-picked blue: the
      // previous `PRIMARY = "#5b8def"` was the last literal colour in the theme
      // engine and could drift from `--ah-primary` without any gate noticing.
      colorPrimary: r["primary"],
      // M3E shape scale, from the token file: cards lg, controls md, hairlines xs.
      borderRadius: shape.md,
      borderRadiusLG: shape.lg,
      borderRadiusSM: shape.sm,
      borderRadiusXS: shape.xs,
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
      // M3 elevation: level 0 is an outline, shadow is for what floats. antd's
      // popovers, dropdowns, menus, tooltips, dialogs and messages are exactly
      // that, so they take the official recipes instead of antd's own shadows.
      boxShadow: elevation("level3"),
      boxShadowSecondary: elevation("level2"),
      boxShadowTertiary: elevation("level1"),
      // M3 has no 32px control: the small step is 40. antd's three control
      // heights map onto Google's button/text-field sizes.
      controlHeight: num("button.sizes.small.height"),
      controlHeightSM: num("button.sizes.small.height"),
      controlHeightLG: num("button.sizes.medium.height"),
      fontSize: typeRole("body-medium").size,
      // A tooltip is a plain-tooltip: inverse surface with inverse-on-surface ink.
      colorBgSpotlight: r["inverse-surface"],
      colorTextLightSolid: r["inverse-on-surface"],
      // antd's own widgets move on the same curves as ours, so a chip and a
      // Select popup never disagree about what "300ms emphasized" means.
      motionDurationFast: dur("short4"),
      motionDurationMid: dur("medium2"),
      motionDurationSlow: dur("medium4"),
      motionEaseInOut: curve("emphasized"),
      motionEaseOut: curve("emphasized-decelerate"),
    },
    components: {
      Layout: {
        // The official small top app bar: 64px on surface-container.
        headerBg: r["surface-container"],
        bodyBg: p.surface0,
        headerHeight: num("appBar.small.height"),
        headerPadding: `0 ${px("spacing.steps.lg")}`,
        headerColor: r["on-surface"],
      },
      Button: {
        // antd's own button stylesheet is the owner of padding, weight and the
        // shadows; m3.css adds only what antd has no token for (the radius and
        // the M3E press morph). M3 publishes no 32px button, so antd's `small`
        // and `middle` both land on Google's *small* (40px), and antd's `large`
        // on Google's *medium* (56px).
        paddingInline: num("button.sizes.small.leading"),
        paddingInlineSM: num("button.sizes.small.leading"),
        paddingInlineLG: num("button.sizes.medium.leading"),
        paddingBlock: 0,
        paddingBlockSM: 0,
        paddingBlockLG: 0,
        contentFontSize: typeRole("label-large").size,
        contentFontSizeSM: typeRole("label-large").size,
        contentFontSizeLG: typeRole("label-large").size,
        contentLineHeight: typeRole("label-large").line,
        contentLineHeightSM: typeRole("label-large").line,
        contentLineHeightLG: typeRole("label-large").line,
        fontWeight: typeRole("label-large").weight,
        iconGap: num("button.sizes.small.gap"),
        onlyIconSize: num("button.sizes.small.icon"),
        onlyIconSizeSM: num("button.sizes.small.icon"),
        onlyIconSizeLG: num("button.sizes.medium.icon"),
        // M3 elevation is not antd's default button shadow: a filled button is
        // level 1 only while it is hovered, and an outlined one never.
        defaultShadow: "none",
        primaryShadow: "none",
        dangerShadow: "none",
        defaultBg: "transparent",
        defaultColor: r["on-surface-variant"],
        defaultBorderColor: r["outline-variant"],
        defaultHoverBg: "transparent",
        defaultHoverColor: r["on-surface-variant"],
        defaultHoverBorderColor: r["outline"],
        defaultActiveBg: "transparent",
        defaultActiveColor: r["on-surface-variant"],
        defaultActiveBorderColor: r["outline"],
        primaryColor: r["on-primary"],
        textTextColor: r["on-surface-variant"],
        textTextHoverColor: r["on-surface-variant"],
        textTextActiveColor: r["on-surface-variant"],
        solidTextColor: r["on-primary"],
        borderColorDisabled: "transparent",
        defaultBgDisabled: "transparent",
        dashedBgDisabled: "transparent",
      },
      Card: {
        // A card is surface-container-low with an outline, level 0, radius 16.
        colorBgContainer: r["surface-container-low"],
        colorBorderSecondary: r["outline-variant"],
      },
      Table: {
        headerBg: r["surface-container-high"],
        headerColor: r["on-surface-variant"],
        // M3 publishes no data table, so the cell metrics are ours, taken from
        // the spacing scale; the row hover is the official state layer rather
        // than a swapped background, which is what makes it the same feedback
        // mechanism as every other row in the app.
        rowHoverBg: layer(r["on-surface"], stateHover),
        colorBgContainer: p.surface1,
        borderColor: p.line,
        cellPaddingBlock: num("spacing.steps.md"),
        cellPaddingInline: num("spacing.steps.lg"),
        cellPaddingBlockMD: num("spacing.steps.md"),
        cellPaddingInlineMD: num("spacing.steps.lg"),
        cellPaddingBlockSM: num("spacing.steps.sm"),
        cellPaddingInlineSM: num("spacing.steps.md"),
        cellFontSize: typeRole("body-medium").size,
        cellFontSizeMD: typeRole("body-medium").size,
        cellFontSizeSM: typeRole("body-small").size,
      },
      Tag: {
        // Our chips are tokenised; keep antd's own tags legible too (the old bug
        // lived here — an unknown preset fell back to white-on-light-grey).
        defaultBg: p.surface2,
        defaultColor: p.text1,
      },
      Descriptions: { labelColor: p.text2 },
      Empty: { colorTextDescription: p.text2 },
      Input: {
        colorBgContainer: r["surface-container-highest"],
        colorTextPlaceholder: r["on-surface-variant"],
        paddingInline: num("textField.space.leading"),
      },
      Select: { colorTextPlaceholder: p.placeholder },
      Typography: { colorText: p.text1, colorTextDescription: p.text2 },
      Switch: {
        // M3's switch: a 52×32 track with a 24px handle when selected.
        trackHeight: num("switch.track.height"),
        trackMinWidth: num("switch.track.width"),
        handleSize: num("switch.handle.selected"),
        handleBg: r["on-primary"],
      },
      Segmented: {
        // An M3 segmented button is a set of outlined buttons, not a filled
        // track: the selected segment carries secondary-container itself.
        trackBg: "transparent",
        trackPadding: 0,
        itemColor: r["on-surface"],
        itemHoverBg: layer(r["on-surface"], stateHover),
        itemActiveBg: layer(r["on-surface"], stateHover),
        itemSelectedBg: r["secondary-container"],
        itemSelectedColor: r["on-secondary-container"],
      },
      Alert: {
        borderRadius: shape.lg,
        defaultPadding: `${px("spacing.steps.md")} ${px("spacing.steps.lg")}`,
        withDescriptionPadding: `${px("spacing.steps.md")} ${px("spacing.steps.lg")}`,
      },
      Badge: {
        indicatorHeight: num("badge.large"),
        dotSize: num("badge.dot"),
        textFontSize: typeRole("label-small").size,
        paddingInline: num("spacing.steps.xs"),
      },
      Divider: { verticalMarginInline: num("spacing.steps.md") },
      List: { itemPadding: `${px("spacing.steps.lg")} ${px("spacing.steps.lg")}` },
      Slider: {
        // The M3E slider's handle is a 4×44 bar and its track is 16px tall.
        railSize: num("slider.track.height"),
        handleSize: num("slider.handle.height"),
        handleSizeHover: num("slider.handle.height"),
        railBg: r["secondary-container"],
        railHoverBg: r["secondary-container"],
        trackBg: r["primary"],
        trackHoverBg: r["primary"],
        handleColor: r["primary"],
        handleActiveColor: r["primary"],
        dotBorderColor: r["secondary-container"],
        trackBgDisabled: layer(r["on-surface"], "--ah-c-slider-disabled-inactive-track"),
      },
      Modal: {
        // Dialog: corner-extra-large on surface-container-high.
        contentBg: r["surface-container-high"],
        headerBg: r["surface-container-high"],
        titleColor: r["on-surface"],
      },
      Progress: {
        defaultColor: r["primary"],
        remainingColor: r["secondary-container"],
        lineBorderRadius: shape.full,
      },
    },
  };
}
