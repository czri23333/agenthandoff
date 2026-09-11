# ruff: noqa: E501  -- the gallery is embedded TSX; its lines are JSX, not Python.
"""Ask the browser whether each M3 rule can apply to anything.

    python scripts/audit_component_rules.py            # audit and clean up
    python scripts/audit_component_rules.py --keep     # leave the gallery behind

Why this exists, in one sentence: **a rule can read every token it names and
still apply to nothing.** `tests/test_tokens_components.py` proves the stylesheet
and the token file agree about *names*; it cannot prove a single one of those
rules reaches an element. That gap shipped five dead families — the tooltip
(`.ant-tooltip-inner` is a v5 name), the dialog, progress, checkbox and radio —
and one of them was visible: a white snackbar with black text over the dark
surface, because antd 6 renders `message` as `.ant-message-notice`.

So this builds a gallery **outside the repo** that mounts every antd family the
sheet writes rules for, plus every `.ah-*` class, against this worktree's own
`theme.ts` and `index.css` (through a directory junction, so there is nothing to
keep in sync), then walks the CSSOM and asks of each rule that reads a
`--ah-c-*` property whether its selector matches a real element. Two page states
are audited and merged, because a dialog traps the pointer and a dropdown only
exists while it is open.

It needs Playwright and a Node toolchain, so it is a maintainer tool rather than
a pytest — the same standing as `sanitize_fixtures.py`, which needs a live store.
The static gates run everywhere; this one runs where a browser is.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"

# How many focusable elements per route the focus sweep reads. The dashboard has
# 14; the cap is here so one pathological page cannot turn the sweep into a
# minute of focus/blur round trips.
FOCUS_LIMIT = 60
# How many Tab presses per route the keyboard pass makes. The dashboard has 16
# focusable elements; the cap also covers the ones a synthetic sweep cannot
# reach, and stops one pathological page from turning the gate into a minute of
# key presses.
FOCUS_TAB_STEPS = 45


def free_port() -> int:
    """A port nobody is listening on.

    A fixed port looked simpler and is not: a previous run whose preview server
    outlived its shell holds it, and the next run then fails with "port already
    in use" against a *stale* process — which reads as a broken audit rather than
    a leaked child.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def kill_tree(process: subprocess.Popen) -> None:
    """Kill the server, not the shell that launched it.

    `npx` is a `.cmd` shim on Windows, so the Popen handle is a `cmd.exe` whose
    child is the real node process; `terminate()` alone leaves the port bound.
    """
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()

# Selectors that legitimately match nothing at rest. Each entry is a *reason*,
# not a name: the audit fails if a rule falls outside all of them.
# States, in both spellings antd uses: pseudo-classes, and the classes it puts on
# an element to mean the same thing (`.ant-switch-disabled`,
# `.ant-segmented-item-active`). A rule that only applies while something is
# disabled, hovered or focused is not dead — the audit's page states do not hold
# a pointer over every control at once.
STATES = (
    ":hover", ":active", ":focus", ":disabled", ":focus-visible", ":focus-within",
    "-disabled", "-focused", "-option-active", "-item-active", "-checked:hover",
)
# antd renders these only during a motion or while a popup is open, and the
# audit's two page states do not cover every popup in antd.
TRANSIENT = (
    "-thumb",  # Segmented's floating selection, present only mid-switch
    "-zoom-",  # Modal's enter/leave classes
    "-dropdown",  # a Select/Dropdown's popup
    "-menu",  # a Dropdown's menu
    "-loading-icon",
    "-switch-loading",
    "-option-selected",
)
# Components the gallery does not mount, with the reason. The audit reports
# these as *unverified* rather than clean.
UNMOUNTED = {
    "-btn-link": "the cockpit renders no Button type=\"link\"",
    "-divider-vertical": "the cockpit renders no vertical Divider",
    "-badge-dot": "the cockpit renders no dot Badge",
    "-arrow": "a Tooltip's arrow, present only while one is open",
}


AUDIT_JS = """
(scope) => {
  const strip = (sel) => sel.replace(/:root/g, 'html').replace(/::?[a-z-]+(\\([^)]*\\))?/g,
    (m) => [':disabled', ':hover', ':active', ':focus-visible', ':focus-within',
            ':focus', ':checked'].includes(m) ? m : '');
  const out = [];
  const seen = new Set();
  const walk = (rules) => {
    for (const rule of rules) {
      if (rule.cssRules && !rule.selectorText) { walk(rule.cssRules); continue; }
      const text = rule.cssText || '';
      if (!text.includes('var(--ah-c-') || !rule.selectorText) continue;
      for (const raw of rule.selectorText.split(',')) {
        const sel = raw.trim();
        if (!sel || seen.has(sel)) continue;
        seen.add(sel);
        const probe = strip(sel).replace(/:not\\([^)]*\\)/g, '').replace(/::-?[a-z-]+/g, '').trim();
        let matched = -1;
        try { matched = probe ? document.querySelectorAll(probe).length : -1; } catch (e) { matched = -2; }
        out.push({ scope, rule: sel, probe, matched });
      }
    }
  };
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    walk(rules);
  }
  return out;
}
"""

# Two contracts that only a rendered page can check, because the values come
# from antd's own runtime stylesheet rather than from ours:
#
#   * M3 publishes weights 400 and 500 and nothing heavier. `th` was drawing 600.
#   * every rendered text size is one of Google's roles (11/12/14/16/22/24).
#
# `tests/test_typography_scale.py` enforces both over *our* sources; this
# enforces them over the computed result, which is where a vendor default can
# hide. It found the 600 on the first run.
OFFICIAL_SIZES = {11, 12, 14, 16, 22, 24}
M3_WEIGHTS = {400, 500}

SWEEP_JS = """
() => {
  const bad = { weights: {}, sizes: {} };
  const bump = (bucket, value, where) => {
    const key = `${value} :: ${where}`;
    bucket[key] = (bucket[key] || 0) + 1;
  };
  for (const el of document.querySelectorAll('body *')) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    const cs = getComputedStyle(el);
    // Skip empty boxes: a container with no text cannot render a weight wrongly.
    const hasText = [...el.childNodes].some(
      (n) => n.nodeType === 3 && (n.textContent || '').trim().length > 0
    );
    if (!hasText) continue;
    const where = el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0];
    bump('weights', cs.fontWeight, where);
    bump('sizes', cs.fontSize, where);
  }
  return bad;
}
"""

# The same question asked of a *running app* rather than of the gallery: every
# distinct computed colour, radius, size and weight, each one checked against the
# token table. This is what found `th { font-weight: 600 }` (antd's rule, in
# antd's stylesheet, invisible to every source-scanning gate), a status tag at
# 3.37:1 in the light theme, and the last two values that were not from a token.
APP_SWEEP_JS = """
() => {
  const out = {};
  const bump = (bucket, value, where) => {
    if (!value || value === 'none' || value === 'normal' || value === 'auto') return;
    out[bucket] = out[bucket] || {};
    const key = `${value} :: ${where}`;
    out[bucket][key] = (out[bucket][key] || 0) + 1;
  };
  // Tokens live on `:root` *and* on elements: a CLI identity chip carries
  // `--ah-cli-bg` on itself, so a reader that only looks at the root reports
  // every chip colour as off-token.
  const values = {};
  for (const el of [document.documentElement, ...document.querySelectorAll('[data-cli]')]) {
    const cs = getComputedStyle(el);
    for (const name of cs) {
      if (!name.startsWith('--ah')) continue;
      const v = cs.getPropertyValue(name).trim();
      if (v) values[v] = true;
    }
  }
  for (const el of document.querySelectorAll('body *')) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    const cs = getComputedStyle(el);
    const where = el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0];
    const hasText = [...el.childNodes].some(
      (n) => n.nodeType === 3 && (n.textContent || '').trim().length > 0
    );
    if (hasText) {
      bump('weights', cs.fontWeight, where);
      bump('sizes', cs.fontSize, where);
    }
    bump('radii', cs.borderTopLeftRadius, where);
    bump('colors', cs.color, where);
    if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)') bump('colors', cs.backgroundColor, where);
  }
  // The comparison against the token table happens in Python, not here: a
  // decision that only a browser can make is a decision no test can check.
  // This side collects; `off_token()` decides.
  // The distinct *values* per bucket, not the distinct (value, element) pairs:
  // "188 colours examined" should mean 188 colours, not the same 20 counted
  // once per element that happens to have them.
  const distinct = {};
  for (const bucket of Object.keys(out)) {
    distinct[bucket] = [...new Set(Object.keys(out[bucket]).map((k) => k.split(' :: ')[0]))];
  }
  return { buckets: out, tokens: Object.keys(values), values: distinct };
}
"""


def gallery_sources() -> dict[str, str]:
    return {
        "index.html": (
            '<!doctype html><html lang="en"><head><meta charset="UTF-8" />'
            "<title>component-rule gallery</title></head><body>"
            '<div id="root"></div><script type="module" src="/src/main.tsx"></script>'
            "</body></html>\n"
        ),
        "vite.config.ts": (
            'import { defineConfig } from "vite";\n'
            'import react from "@vitejs/plugin-react";\n\n'
            "export default defineConfig({ plugins: [react()], build: { outDir: \"dist\" } });\n"
        ),
        "src/main.tsx": GALLERY_TSX,
    }


GALLERY_TSX = """
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import {
  Alert, App as AntApp, Badge, Button, Card, Checkbox, ConfigProvider, Divider, Empty,
  Input, Modal, Progress, Radio, Segmented, Select, Slider, Space, Switch,
  Table, Tooltip, Typography, message,
} from "antd";
// `srcwork` is a junction to the worktree's web/src, so this compiles the same
// theme engine and stylesheets the app ships.
import { antdConfig, applyTheme } from "../srcwork/theme";
import "../srcwork/index.css";

const THEME = "dark" as const;
localStorage.setItem("ah-theme", THEME);
applyTheme(THEME);

const params = new URLSearchParams(location.search);
const wantModal = params.has("modal");
const wantConfirm = params.has("confirm");

function Gallery() {
  useEffect(() => {
    message.success("gallery message");
    if (wantConfirm) Modal.confirm({ title: "confirm title", content: "confirm body" });
  }, []);
  return (
    <div style={{ padding: 16 }}>
      <Space wrap>
        <button className="ah-btn" id="g-ah-btn"><span className="anticon">+</span>filled</button>
        <button className="ah-btn ah-btn--filled" id="g-ah-btn-filled">filled explicit</button>
        <button className="ah-btn ah-btn--tonal" id="g-ah-btn-tonal"><svg /><span className="anticon">+</span>tonal</button>
        <button className="ah-btn ah-btn--elevated" id="g-ah-btn-elevated">elevated</button>
        <button className="ah-btn ah-btn--outlined" id="g-ah-btn-outlined">outlined</button>
        <button className="ah-btn ah-btn--text" id="g-ah-btn-text">text</button>
        <button className="ah-btn ah-btn--medium" id="g-ah-btn-medium">
          <span className="anticon">+</span><svg />medium
        </button>
        <button className="ah-btn ah-btn--large" id="g-ah-btn-large">
          <span className="anticon">+</span><svg />large
        </button>
        <button className="ah-btn ah-btn--square" id="g-ah-btn-square">square</button>
        <button className="ah-btn ah-btn--square ah-btn--medium" id="g-ah-btn-square-m">sq m</button>
        <button className="ah-btn ah-btn--square ah-btn--large" id="g-ah-btn-square-l">sq l</button>
        <button className="ah-btn ah-btn--medium ah-btn--outlined" id="g-ah-btn-m-out">m out</button>
        <button className="ah-btn ah-btn--large ah-btn--outlined" id="g-ah-btn-l-out">l out</button>
        <button className="ah-btn" disabled id="g-ah-btn-disabled">disabled</button>
        <button className="ah-iconbtn" id="g-ah-iconbtn"><span className="anticon">+</span></button>
        <button className="ah-iconbtn" id="g-ah-iconbtn-svg"><svg /></button>
        <button className="ah-iconbtn ah-iconbtn--filled" id="g-ah-iconbtn-filled"><span className="anticon">+</span></button>
        <button className="ah-iconbtn ah-iconbtn--tonal" id="g-ah-iconbtn-tonal"><span className="anticon">+</span></button>
        <button className="ah-iconbtn ah-iconbtn--outlined" id="g-ah-iconbtn-outlined"><span className="anticon">+</span></button>
        <button className="ah-iconbtn ah-iconbtn--square" id="g-ah-iconbtn-square"><span className="anticon">+</span></button>
        <button className="ah-iconbtn ah-iconbtn--narrow" id="g-ah-iconbtn-narrow"><span className="anticon">+</span></button>
        <button className="ah-iconbtn ah-iconbtn--wide" id="g-ah-iconbtn-wide"><span className="anticon">+</span></button>
        <button className="ah-iconbtn ah-iconbtn--default" id="g-ah-iconbtn-default"><span className="anticon">+</span></button>
        <button className="ah-fab" id="g-ah-fab"><span className="anticon">+</span></button>
        <button className="ah-fab ah-fab--small" id="g-ah-fab-small">
          <span className="anticon">+</span><svg />
        </button>
        <button className="ah-fab ah-fab--medium" id="g-ah-fab-medium">
          <span className="anticon">+</span><svg />
        </button>
        <button className="ah-fab ah-fab--large" id="g-ah-fab-large">
          <span className="anticon">+</span><svg />
        </button>
        <button className="ah-mchip ah-mchip--assist" id="g-ah-chip-assist"><span className="anticon">+</span>assist</button>
        <button className="ah-mchip ah-mchip--assist" id="g-ah-chip-assist-svg"><svg />assist svg</button>
        <button className="ah-mchip ah-mchip--filter" id="g-ah-chip-filter" aria-pressed="false">filter</button>
        <button className="ah-mchip ah-mchip--filter" id="g-ah-chip-filter-on" aria-pressed="true">
          <span className="ah-mchip__check">C</span><svg />filter on
        </button>
        <button className="ah-mchip ah-mchip--filter" id="g-ah-chip-filter-on2" aria-pressed="true">
          <span className="ah-mchip__check">C</span><span className="anticon">+</span>filter on 2
        </button>
        <button className="ah-mchip ah-mchip--input" id="g-ah-chip-input">input</button>
        <span className="ah-mchip__avatar" id="g-ah-chip-avatar" />
        <button className="ah-filterchip" id="g-ah-filterchip">off</button>
        <button className="ah-filterchip" id="g-ah-filterchip-on" aria-pressed="true">
          <svg />on
        </button>
        <button className="ah-filterchip" id="g-ah-filterchip-on2" aria-pressed="true">
          <span className="anticon">+</span>on 2
        </button>
      </Space>
      <div className="ah-li ah-li--two-line" id="g-ah-li">
        <span className="ah-li__icon">o</span>
        <span className="ah-li__avatar" id="g-ah-li-avatar" />
        <span><span className="ah-li__overline">over</span>
          <span className="ah-li__label">label</span>
          <span className="ah-li__supporting">supporting</span></span>
      </div>
      <div className="ah-li ah-li--three-line" id="g-ah-li-3" aria-selected="true">three</div>
      <div className="ah-field" id="g-ah-field">
        <span className="ah-field__icon">o</span>
        <input className="ah-field__input" placeholder="ph" />
        <span className="ah-field__label">label</span>
        <span className="ah-field__indicator" />
      </div>
      <div className="ah-field ah-field--outlined" id="g-ah-field-outlined">
        <input className="ah-field__input" /><span className="ah-field__label">label</span>
      </div>
      <div className="ah-field ah-field--dense" id="g-ah-field-dense">
        <input className="ah-field__input" />
      </div>
      <div className="ah-field ah-field--error" id="g-ah-field-error">
        <input className="ah-field__input" /><span className="ah-field__label">label</span>
        <span className="ah-field__supporting">supporting</span>
      </div>
      <div className="ah-field ah-field--outlined ah-field--populated" id="g-ah-field-out-pop">
        <input className="ah-field__input" /><span className="ah-field__label">label</span>
      </div>
      <div className="ah-field ah-field--populated" id="g-ah-field-populated">
        <input className="ah-field__input" /><span className="ah-field__label">label</span>
      </div>
      <div className="ah-field ah-field--with-label" id="g-ah-field-withlabel">
        <input className="ah-field__input" />
      </div>
      <div className="ah-field" id="g-ah-field-disabled"><input className="ah-field__input" disabled /></div>
      <div className="ah-field ah-field--outlined" id="g-ah-field-out-disabled">
        <input className="ah-field__input" disabled />
      </div>
      <div className="ah-progress" id="g-ah-progress"><i style={{ width: "60%" }} /></div>
      <div className="ah-progress ah-progress--indeterminate" id="g-ah-progress-ind"><i /></div>
      <div className="ah-progress-circular" id="g-ah-progress-circular" />
      <span className="ah-slider-value" id="g-ah-slider-value">42</span>
      <div className="ah-appbar" id="g-ah-appbar">
        <h1 className="ah-appbar__title">title</h1>
        <span className="ah-appbar__subtitle">sub</span>
      </div>
      <div className="ah-appbar ah-appbar--medium" id="g-ah-appbar-medium" />
      <div className="ah-dialog" id="g-ah-dialog"><div className="ah-dialog__actions" /></div>
      <div className="ah-empty" id="g-ah-empty" />
      <div className="ah-navbar" id="g-ah-navbar">
        <span className="ah-navbar__indicator" />
        <span className="ah-navbar__item ah-navbar__item--active"><svg /></span>
        <span className="ah-navbar__item ah-navbar__item--inactive"><svg /></span>
        <span className="ah-navbar__item ah-navbar__item--active" id="g-ah-navbar-item-a">
          <span className="anticon">+</span>
        </span>
        <span className="ah-navbar__item ah-navbar__item--inactive" id="g-ah-navbar-item-i">
          <span className="anticon">+</span>
        </span>
      </div>
      <div className="ah-navbar ah-navbar--tall" id="g-ah-navbar-tall" />
      <div className="ah-navrail__header" id="g-ah-navrail-header" />
      <div className="ah-navrail__item" id="g-ah-navrail-item"><span className="anticon">+</span></div>
      <div className="ah-navrail__item" id="g-ah-navrail-item-svg"><svg /></div>
      <div className="ah-navrail__indicator" id="g-ah-navrail-indicator" />
      <div className="ah-snackbar--two-line" id="g-ah-snackbar" />
      <span className="ah-snackbar__action" id="g-ah-snackbar-action">undo</span>
      <span className="ah-segmented__icon" id="g-ah-segmented-icon">+</span>
      <div className="ah-searchbar" id="g-ah-searchbar">
        <span className="ah-searchbar__icon">Q</span>
        <input className="ah-searchbar__input" placeholder="search" />
        <span className="ah-searchbar__icon ah-searchbar__icon--trailing">x</span>
        <span className="ah-searchbar__avatar" id="g-ah-searchbar-avatar">A</span>
      </div>
      <nav className="ah-tabs" id="g-ah-tabs">
        <span className="ah-tabs__indicator" id="g-ah-tabs-indicator"
              style={{ translate: "0px", width: "80px" }} />
        <button className="ah-tab ah-tab--active" id="g-ah-tab-active">
          <svg />one<span className="ah-tab__key">1</span>
        </button>
        <button className="ah-tab ah-tab--inactive" id="g-ah-tab-inactive">
          <svg />two
        </button>
        <button className="ah-tab ah-tab--active" id="g-ah-tab-active-icon">
          <span className="anticon">+</span>four
        </button>
        <button className="ah-tab ah-tab--inactive" id="g-ah-tab-inactive-icon">
          <span className="anticon">+</span>five
        </button>
        <button className="ah-tab ah-tab--with-icon" id="g-ah-tab-icon">
          <span className="anticon">+</span>three
        </button>
      </nav>
      <div className="ah-docked-toolbar" id="g-ah-docked-toolbar" />
      <div className="ah-docked-toolbar ah-detailbar" id="g-ah-detailbar" />
      <div className="ah-shell" id="g-ah-shell" />
      <span className="ah-tag ah-tag--neutral" id="g-ah-tag-neutral">neutral</span>
      <span className="ah-tag ah-tag--ok" id="g-ah-tag-ok">ok</span>
      <span className="ah-tag ah-tag--accent" id="g-ah-tag-accent">accent</span>
      <span className="ah-tag ah-tag--warn" id="g-ah-tag-warn">warn</span>
      <span className="ah-tag ah-tag--err" id="g-ah-tag-err">err</span>
      <div className="ah-skeleton" id="g-ah-skeleton" />
      <Empty
        className="ah-empty"
        image={<span className="ah-empty__mark" id="g-ah-empty-mark">◇</span>}
        description={<span className="ah-meta">nothing here</span>}
      />
      <button className="ah-row" id="g-ah-row">row</button>
      <button className="ah-row" id="g-ah-row-sel" aria-selected="true">row sel</button>
      <span className="ah-loading" id="g-ah-loading" />
      <span className="ah-loading ah-loading--uncontained" id="g-ah-loading-u" />
      <div className="ah-card" id="g-ah-card">
        <div className="ah-card__head ah-card__rule ah-card__rule--ok">
          <span className="ah-label ah-ok">done</span>
        </div>
        <div className="ah-card__body">body</div>
      </div>
      <div className="ah-card" id="g-ah-card-accent">
        <div className="ah-card__head ah-card__rule ah-card__rule--accent" />
      </div>
      <div className="ah-card" id="g-ah-card-err">
        <div className="ah-card__head ah-card__rule ah-card__rule--err" />
      </div>
      <Space wrap>
        <Button type="primary" id="g-primary">primary</Button>
        <Button id="g-default">default</Button>
        <Button type="text" id="g-text">text</Button>
        <Button danger id="g-danger">danger</Button>
        <Button size="small" id="g-small">small</Button>
        <Button size="large" id="g-large">large</Button>
        <Button type="primary" icon={<span>+</span>} id="g-icononly" />
        <Segmented options={["a", "b", "c"]} defaultValue="a" id="g-segmented" />
        <Switch defaultChecked id="g-switch" />
        <Slider defaultValue={40} dots id="g-slider" />
        <Checkbox defaultChecked id="g-checkbox">check</Checkbox>
        <Radio defaultChecked id="g-radio">radio</Radio>
        <Tooltip title="gallery tooltip"><span id="g-tooltip">hover me</span></Tooltip>
        <Badge count={5} id="g-badge"><span>badge</span></Badge>
        <Input placeholder="input" id="g-input" />
        <Select className="ah-select-chip" defaultValue="a"
                options={[{ value: "a", label: "a" }]} id="g-select-chip" />
        <Select className="ah-select-chip" placeholder="empty"
                options={[{ value: "a", label: "a" }]} id="g-select-chip-empty" />
        <Progress percent={40} id="g-progress-line" />
        <Progress type="circle" percent={40} id="g-progress-circle" />
      </Space>
      <Divider id="g-divider" />
      <Alert type="warning" showIcon message="alert" id="g-alert" />
      <Card id="g-card" title="card">card body</Card>
      <Table id="g-table" size="small" columns={[{ title: "k", dataIndex: "k" }]}
             dataSource={[{ key: "1", k: "v" }]} pagination={false} />
      <Typography.Title level={5} id="g-title">title</Typography.Title>
      {wantModal && (
        <Modal open title="modal" id="g-modal" footer={<Button type="primary">ok</Button>}>
          modal body
        </Modal>
      )}
      <nav className="ah-tabs" id="g-ah-tabs-2">
        <button className="ah-tab ah-tab--active">x</button>
      </nav>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider theme={antdConfig(THEME)}>
      <AntApp><Gallery /></AntApp>
    </ConfigProvider>
  </StrictMode>,
);
"""


def build_gallery(root: Path) -> None:
    for rel, body in gallery_sources().items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
    _junction(root / "node_modules", WEB / "node_modules")
    _junction(root / "srcwork", WEB / "src")


def _junction(link: Path, target: Path) -> None:
    if link.exists():
        return
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, shell=(os.name == "nt"))


def chromium_path(pw) -> str | None:
    """The headless shell to launch, or None to let Playwright decide.

    Playwright pins the browser revision it was built against, and a wheel can
    be older or newer than what is on the disk — on the machine this was written
    on, the wheel wants rev 1234 and 1243 is installed. Falling back to whatever
    `chromium_headless_shell-*` exists keeps the tool usable instead of asking a
    maintainer to re-download a browser to run an audit.
    """
    expected = Path(pw.chromium.executable_path)
    if expected.exists():
        return None  # Playwright's own choice is right
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "ms-playwright"
    if not root.is_dir():
        alt = Path.home() / ".cache" / "ms-playwright"
        root = alt if alt.is_dir() else root
    found = sorted(root.glob("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell*"))
    return str(found[-1]) if found else None


def off_scale(sweep: dict) -> tuple[list[str], list[str]]:
    """The computed values that break an M3 contract with a closed set.

    M3 publishes weights 400 and 500 and nothing heavier, and a fixed set of
    text sizes. Both are closed sets, so a rendered page can be *checked* against
    them rather than eyeballed — and both were broken by antd's own stylesheet
    rather than by ours, which is why the source-scanning gates in
    `tests/test_typography_scale.py` could not see it.
    """
    def split(bucket: dict) -> list[tuple[str, str, int]]:
        out = []
        for key, count in bucket.items():
            value, _, where = key.partition(" :: ")
            out.append((value, where, count))
        return out

    weights = sorted(
        f"{value} at {where} (x{count})"
        for value, where, count in split(sweep.get("weights", {}))
        if int(float(value)) not in M3_WEIGHTS
    )
    sizes = sorted(
        f"{value} at {where} (x{count})"
        for value, where, count in split(sweep.get("sizes", {}))
        # Compared as a float against the float form of the scale, not rounded:
        # `round(13.5)` is 14, and 14 is on the scale, so rounding let a
        # half-pixel size through — which is exactly the kind of value the check
        # exists to find.
        if float(value.rstrip("px")) not in {float(size) for size in OFFICIAL_SIZES}
    )
    return weights, sizes


def _rgb(value: str) -> str:
    """A CSS colour in `rgb(r, g, b)` form, so hex and computed can be compared.

    Tokens are stored as hex and computed values come back as `rgb(...)`; a raw
    string comparison reports every single colour as off-token, which is how the
    first version of this sweep produced a page of false positives.
    """
    text = " ".join(value.split())
    six = re.fullmatch(r"#([0-9a-fA-F]{6})", text)
    if six:
        n = int(six.group(1), 16)
        return f"rgb({(n >> 16) & 255}, {(n >> 8) & 255}, {n & 255})"
    three = re.fullmatch(r"#([0-9a-fA-F]{3})", text)
    if three:
        c = three.group(1)
        return (
            f"rgb({int(c[0] * 2, 16)}, {int(c[1] * 2, 16)}, {int(c[2] * 2, 16)})"
        )
    return text


def off_token(sweep: dict) -> tuple[list[str], list[str]]:
    """Colours and radii from a running app that are in no token anywhere.

    Weights and sizes are closed sets and `off_scale` checks them exactly.
    Colours and radii are open — a value is only wrong if *nothing* in the token
    table equals it — so this is the weaker question, and it is the one that
    found a status tag at 3.37:1 whose pair antd's algorithm derived.
    """
    tokens = {_rgb(value) for value in sweep.get("tokens", [])}
    buckets = sweep.get("buckets", {})

    def rows(bucket: str) -> list[str]:
        out: list[str] = []
        for key, count in buckets.get(bucket, {}).items():
            value = key.split(" :: ")[0]
            if _rgb(value) in tokens:
                continue
            out.append(f"{key} (x{count})")
        return sorted(out)

    return rows("colors"), rows("radii")


def reachable(rows: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """Split the audit into defects, unverified and fine.

    A rule is a **defect** when it reads component tokens, matches nothing, and
    is not a state, not a transient popup, and not a component the gallery does
    not mount. Everything else is reported rather than hidden: `unverified` is
    the honest middle, and a maintainer can move a name out of `UNMOUNTED` by
    mounting it.
    """
    defects: list[str] = []
    unverified: list[str] = []
    for rule in sorted({r["rule"] for r in rows}):
        if any(r["rule"] == rule and r["matched"] > 0 for r in rows):
            continue
        if any(s in rule for s in STATES):
            continue
        if any(t in rule for t in TRANSIENT):
            continue
        reason = next((v for k, v in UNMOUNTED.items() if k in rule), None)
        if reason:
            unverified.append(f"{rule}  ({reason})")
        else:
            defects.append(rule)
    return defects, unverified, []


# ── The keyboard focus indicator ────────────────────────────────────────────
# The rules above ask whether a *class* reaches an element. This asks what a
# keyboard user actually sees: it focuses every focusable element on every route,
# in both themes, settles the ring's choreography, and reads back the computed
# ring. Four things are checked, and each one was a live defect at some point:
#
#   * the ring is `--ah-secondary` at the official 3px / 2px outward offset — not
#     antd's `--ant-color-primary-border` (a colour its algorithm derives, so it
#     was the same grey in both themes and matched no token);
#   * focusing does not change the element's own `border-radius` (a global
#     `border-radius: 4px` on `:focus-visible` squared the slider handle);
#   * the grow/shrink choreography is present, unless the ring is delegated to an
#     ancestor — a Select's focusable node is its inner input while the visible
#     box is the chip around it, so "no ring here" is correct exactly when an
#     ancestor draws one;
#   * the node that draws the ring is a node the reader can see. antd's segmented
#     input is 0x0 with `opacity: 0`: our ring computed correctly on it and was
#     invisible, while antd's grey ring showed on the item around it. A focusable
#     node with no box is only acceptable when the box it sits in draws the ring;
#   * there is no *second* indicator. antd paints one on the slider handle's
#     `::after` (`outline: 6px solid`, `box-shadow: 0 0 0 2.5px`), which a check
#     that only reads the element's own `outline` cannot see;
#   * the producer is not empty: the sweep must have examined elements, and the
#     theme must actually have been applied. An empty sweep is a false green.
FOCUS_SELECTOR = (
    'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
)
FOCUS_OVERLAY_SELECTOR = ".ant-dropdown-menu-item"

# ── Controls that sit on top of each other ──────────────────────────────────
# One antd card head can carry a title, a segmented control and three buttons.
# At the rail's 400px that is ~450px of content, and antd's single-row head
# painted them over one another: measured, the `.zip` button at x 1081–1187 over
# the 摘要/全文 switch at x 1109–1213. Nothing in this repo looked for that — the
# colour, radius, size and focus sweeps all pass on a page whose controls
# overlap — so this is the check for it. Pairs that contain one another are
# skipped (a button inside a row is not an overlap), as are zero-area boxes.
OVERLAP_JS = r"""
() => {
  const sel = 'a[href], button, input, select, textarea, [role="button"], .ant-segmented-item, [tabindex]:not([tabindex="-1"])';
  const els = [...document.querySelectorAll(sel)].filter(e => {
    const c = getComputedStyle(e);
    if (c.display === 'none' || c.visibility === 'hidden' || c.opacity === '0') return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  const MIN = 4;
  const out = [];
  for (let i = 0; i < els.length; i++) {
    for (let j = i + 1; j < els.length; j++) {
      const a = els[i], b = els[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const ox = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const oy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (ox > MIN && oy > MIN) {
        const name = (e) => (e.tagName.toLowerCase() + '.' + String(e.className).split(' ').slice(0, 2).join('.')).slice(0, 46)
          + ' "' + (e.innerText || e.value || '').replace(/\s+/g, ' ').slice(0, 18) + '"';
        out.push({a: name(a), b: name(b), ox: Math.round(ox), oy: Math.round(oy)});
      }
    }
  }
  return {examined: els.length, pairs: out.slice(0, 40), total: out.length};
}
"""


def overlap_defects(where: str, found: dict) -> list[str]:
    """Overlapping controls, as failure lines. Zero examined is a failure too."""
    out: list[str] = []
    if not found.get("examined"):
        return [f"{where}: the overlap sweep examined no controls"]
    for pair in found.get("pairs", []):
        out.append(
            f"{where}: {pair['a']} overlaps {pair['b']} by "
            f"{pair['ox']}x{pair['oy']}px"
        )
    return out


# The synthetic pass calls `element.focus()`, which is not the same event a
# keyboard produces: antd adds `ant-segmented-item-focused` only for a real key
# focus, so the segmented control *passes* a synthetic sweep while the reader
# sees antd's ring. These two functions are the second channel — `Tab` is pressed
# from Python and this measures whatever now holds focus, without focusing it.
FOCUS_ACTIVE_JS = r"""
() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const root = getComputedStyle(document.documentElement);
  const expect = root.getPropertyValue('--ah-secondary').trim();
  const settle = (e) => e.getAnimations()
    .forEach(a => {
      // Every *finite* animation, not just the focus ones: the cockpit
      // transitions `outline-color`/`outline-offset` like any other property, so
      // a reading taken while a transition is still interpolating shows a colour
      // that is neither antd's nor ours — measured on the pager's next button as
      // `rgb(37, 34, 41) at 1px`, which is 15% of the way from
      // `rgb(29, 27, 32)` to `rgb(98, 91, 113)`. Infinite animations (the
      // spinner) are left alone; `finish()` on those never returns a value.
      const t = a.effect && a.effect.getComputedTiming();
      if (!t || t.iterations === Infinity) return;
      try { a.finish(); } catch (err) {}
    });
  const hasBox = (e) => {
    const b = e.getBoundingClientRect();
    return b.width > 0 && b.height > 0;
  };
  const ringOf = (e) => {
    const c = getComputedStyle(e);
    return { w: c.outlineWidth, s: c.outlineStyle, c: c.outlineColor, o: c.outlineOffset };
  };
  const pseudoRings = (e) => {
    const bad = [];
    for (const p of ['::before', '::after']) {
      const q = getComputedStyle(e, p);
      if (!q) continue;
      // Style, not width: antd's slider indicator transitions in from 0px, and at
      // t=0 the width is still 0 while the style is already `solid`. Reading the
      // width here is how the first version of this check missed it.
      const outline = q.outlineStyle !== 'none';
      let spread = false;
      if (q.boxShadow && q.boxShadow !== 'none') {
        for (const part of q.boxShadow.split(/,(?![^()]*\))/)) {
          if (part.includes('inset')) continue;
          if (/rgba\(0,\s*0,\s*0,\s*0\)/.test(part)) continue;
          const lens = (part.match(/-?[\d.]+px/g) || []).map(parseFloat);
          const spreadPx = lens.length >= 4 ? lens[3] : 0;
          if (spreadPx > 0) spread = true;
        }
      }
      if (outline || spread) {
        bad.push(p + (outline ? " outline" : "") + (spread ? " ring" : ""));
      }
    }
    return bad;
  };
  let target = el;
  for (let i = 0; i < 4 && !hasBox(target) && target.parentElement; i++) {
    target = target.parentElement;
  }
  // Read the choreography *before* settling it: `finish()` on a fill-mode-none
  // animation removes it from `getAnimations()`, so reading afterwards reports
  // "no animation" for every element and the check fails on all of them.
  const animations = el.getAnimations()
    .filter(a => (a.animationName || '').startsWith('ah-focus'))
    .map(a => a.animationName);
  settle(el);
  settle(target);
  let effective = ringOf(target);
  let delegated = target !== el;
  if (effective.s === 'none' || effective.w === '0px') {
    let p = target.parentElement;
    for (let i = 0; i < 3 && p; i++, p = p.parentElement) {
      settle(p);
      const c = ringOf(p);
      if (c.s !== 'none' && c.w !== '0px') { effective = c; delegated = true; break; }
    }
  }
  const cs = getComputedStyle(el);
  return {
    tag: el.tagName,
    cls: String(el.className).slice(0, 60),
    width: effective.w,
    colour: effective.c,
    offset: effective.o,
    delegated,
    invisible: !hasBox(el) || cs.opacity === '0',
    targetCls: String(target.className || '').slice(0, 48),
    secondIndicators: [...pseudoRings(el), ...(target === el ? [] : pseudoRings(target))],
    animations,
    expect,
  };
}
"""

FOCUS_JS = r"""
([sel, limit]) => {
  // `width > 0` used to be a filter here, and that is exactly what hid the
  // segmented defect: the node that receives focus is 0x0 and invisible, so it
  // was never examined, and the ring antd drew on the item around it was never
  // compared against ours. Only `display: none` and `visibility: hidden` are
  // skipped now; a zero-sized focusable is *reported*, not dropped.
  const els = [...document.querySelectorAll(sel)]
    .filter(e => {
      const cs = getComputedStyle(e);
      return cs.display !== 'none' && cs.visibility !== 'hidden';
    })
    .slice(0, limit);
  const root = getComputedStyle(document.documentElement);
  const expect = root.getPropertyValue('--ah-secondary').trim();
  const settle = (e) => e.getAnimations()
    .forEach(a => {
      // Same rule as the synthetic pass: finish every finite animation, because
      // a transition still interpolating reports a value that belongs to no rule.
      const t = a.effect && a.effect.getComputedTiming();
      if (!t || t.iterations === Infinity) return;
      try { a.finish(); } catch (err) {}
    });
  const hasBox = (e) => {
    const b = e.getBoundingClientRect();
    return b.width > 0 && b.height > 0;
  };
  const ringOf = (e) => {
    const c = getComputedStyle(e);
    return { w: c.outlineWidth, s: c.outlineStyle, c: c.outlineColor, o: c.outlineOffset };
  };
  // A shadow that is not inset, has a non-zero spread and is not transparent is
  // a ring: that is the shape antd draws on a slider handle's `::after`.
  const pseudoRings = (e) => {
    const bad = [];
    for (const p of ['::before', '::after']) {
      const q = getComputedStyle(e, p);
      if (!q) continue;
      // Style, not width: antd's slider indicator transitions in from 0px, and at
      // t=0 the width is still 0 while the style is already `solid`. Reading the
      // width here is how the first version of this check missed it.
      const outline = q.outlineStyle !== 'none';
      let spread = false;
      if (q.boxShadow && q.boxShadow !== 'none') {
        for (const part of q.boxShadow.split(/,(?![^()]*\))/)) {
          if (part.includes('inset')) continue;
          if (/rgba\(0,\s*0,\s*0,\s*0\)/.test(part)) continue;
          const lens = (part.match(/-?[\d.]+px/g) || []).map(parseFloat);
          const spreadPx = lens.length >= 4 ? lens[3] : 0;
          if (spreadPx > 0) spread = true;
        }
      }
      if (outline || spread) {
        bad.push(p + (outline ? " outline" : "") + (spread ? " ring" : ""));
      }
    }
    return bad;
  };
  const rows = [];
  for (const el of els) {
    const before = getComputedStyle(el);
    const radiusBefore = before.borderTopLeftRadius;
    el.focus();
    const anims = el.getAnimations().filter(a => (a.animationName || '').startsWith('ah-focus'));
    const timings = anims.map(a => {
      const t = a.effect.getComputedTiming();
      return { name: a.animationName, duration: Math.round(t.duration), delay: Math.round(t.delay) };
    });
    anims.forEach(a => { try { a.finish(); } catch (err) {} });
    // The box the reader sees: the element itself, or the nearest ancestor that
    // has a box at all.
    let target = el;
    for (let i = 0; i < 4 && !hasBox(target) && target.parentElement; i++) {
      target = target.parentElement;
    }
    settle(el);
    settle(target);
    const own = ringOf(el);
    let effective = ringOf(target);
    let delegate = null;
    if (effective.s === 'none' || effective.w === '0px') {
      let p = target.parentElement;
      for (let i = 0; i < 3 && p; i++, p = p.parentElement) {
        settle(p);
        const c = ringOf(p);
        if (c.s !== 'none' && c.w !== '0px') {
          delegate = { cls: String(p.className).slice(0, 48), ring: c };
          effective = c;
          break;
        }
      }
    }
    const second = [...pseudoRings(el), ...(target === el ? [] : pseudoRings(target))];
    const cs = getComputedStyle(el);
    el.blur();
    rows.push({
      tag: el.tagName,
      cls: String(el.className).slice(0, 60),
      radiusBefore,
      radiusAfter: cs.borderTopLeftRadius,
      width: effective.w,
      colour: effective.c,
      offset: effective.o,
      delegated: delegate !== null,
      delegateCls: delegate ? delegate.cls : null,
      targetCls: String(target.className || "").slice(0, 48),
      invisible: !hasBox(el) || cs.opacity === "0",
      secondIndicators: second,
      animations: timings,
    });
  }
  return { expect, count: els.length, rows };
}
"""


def focus_defects(rows: list[dict], expected: str | dict[str, str]) -> list[str]:
    """What a keyboard user would see, as a list of things that are wrong.

    Split out from the browser work on purpose: `tests/test_tokens_components.py`
    feeds this function both real and deliberately broken evidence, so the check
    that guards the focus ring is itself checked.

    `expected` is the `--ah-secondary` the page reported: one hex string, or a
    per-theme mapping. It has to be per-theme, because the two palettes publish
    different secondaries (#625b71 against #ccc2dc) and comparing the light rows
    against the dark value is how the first run of this gate reported 50
    failures that were all the same measurement mistake.
    """
    out: list[str] = []
    for r in rows:
        if r.get("tag") == "THEME":
            out.append(f"{r['cls']}: the requested theme was not applied")
            continue
        theme = r.get("theme", "")
        want = _rgb(expected[theme] if isinstance(expected, dict) else expected)
        where = f'{r.get("theme", "")}{r.get("route", "")} {r["cls"] or r["tag"]}'.strip()
        # A synthetic `focus()` cannot reproduce every antd state (the segmented
        # item marks itself focused only for a real key focus), so an element with
        # no box is not judged here — the keyboard pass judges it, and the empty
        # producer check below refuses a run where that pass examined nothing.
        if r.get("invisible") and r.get("pass") == "synthetic":
            continue
        if r["width"] != "3px" or r["colour"] != want or r["offset"] != "2px":
            out.append(
                f"{where}: ring is {r['width']} {r['colour']} at {r['offset']}, "
                f"want 3px {want} at 2px"
            )
        if "radiusBefore" in r and r["radiusBefore"] != r.get("radiusAfter"):
            out.append(
                f"{where}: border-radius changed on focus "
                f"({r['radiusBefore']} -> {r['radiusAfter']})"
            )
        if not r["delegated"] and not r["animations"]:
            out.append(f"{where}: focused without the focus-ring choreography")
        if r.get("invisible") and not r["delegated"]:
            out.append(
                f"{where}: the focused node has no visible box and nothing "
                "around it draws the ring"
            )
        if r.get("secondIndicators"):
            out.append(
                f"{where}: a second focus indicator is painted by "
                + ", ".join(r["secondIndicators"])
                + f" (the box is {r.get('targetCls') or 'itself'})"
            )
    return out


def run_overlap_sweep(page, url: str, routes: list[str]) -> tuple[list[str], int]:
    """Controls that sit on top of one another, in both themes.

    The five list routes plus one session-detail route, because the detail view
    is where the rail lives and it is the only place a card head carries a title,
    a switch and three buttons at 400px.

    Returns the defect lines and how many controls were examined — the count is
    part of the evidence, because "no overlaps" from a page that rendered no
    controls is not a pass.
    """
    out: list[str] = []
    examined = 0
    detail_route = ""
    try:
        with urllib.request.urlopen(
            url.rstrip("/") + "/api/sessions", timeout=90
        ) as resp:
            rows_api = json.loads(resp.read())
        if isinstance(rows_api, list) and rows_api:
            first = rows_api[0]
            detail_route = (
                "#/session/"
                + urllib.parse.quote(str(first["cli"]))
                + "/"
                + urllib.parse.quote(str(first["session_id"]))
            )
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        # Not a pass and not a defect in the app: say what happened.
        out.append(f"could not discover a session-detail route: {exc}")
    for theme in ("light", "dark"):
        page.goto(url, wait_until="domcontentloaded")
        page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["ah-theme", theme])
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("#ah-tokens", state="attached")
        page.wait_for_timeout(1200)
        seen = [*routes, *([detail_route] if detail_route else [])]
        for route in seen:
            page.goto(url.rstrip("/") + "/" + route, wait_until="domcontentloaded")
            # Wait for the page to leave its loading state rather than guessing a
            # duration: the first version waited 4s and measured 160 controls on
            # one run and 630 on the next, because one of those runs was still
            # looking at skeletons. A page that never loads is a defect too — it
            # is the shape of the bug that made this gate necessary.
            page.wait_for_timeout(1200)
            loaded = True
            try:
                page.wait_for_function(
                    "() => document.querySelectorAll('.ah-skeleton').length === 0",
                    timeout=30000,
                )
            except Exception:  # noqa: BLE001 - a slow page is the finding, not a crash
                loaded = False
            page.wait_for_timeout(1200)
            found = page.evaluate(OVERLAP_JS)
            examined += found.get("examined", 0)
            defects = overlap_defects(f"{theme} {route}", found)
            if not loaded:
                defects.append(f"{theme} {route}: still in its loading state after 30s")
            out.extend(defects)
    return out, examined


def run_focus_sweep(page, url: str, routes: list[str]) -> dict:
    """Focus every focusable element on every route, in both themes.

    Playwright's page comes in from `main`, because the import lives there — the
    tool reports a missing browser instead of failing to import.
    """
    # The session-detail route is not in the list routes and the read-only review
    # could not reach it either; ask the API for a real id so the surface the rail
    # lives on is covered. Measured: 2.4s to 187 rows, so the waits here are
    # generous on purpose.
    detail_route = ""
    try:
        with urllib.request.urlopen(
            url.rstrip("/") + "/api/sessions", timeout=90
        ) as resp:
            rows_api = json.loads(resp.read())
        if isinstance(rows_api, list) and rows_api:
            detail_route = "#/session/{}/{}".format(
                urllib.parse.quote(str(rows_api[0]["cli"])),
                urllib.parse.quote(str(rows_api[0]["session_id"])),
            )
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        detail_route = ""
    routes = [*routes, *([detail_route] if detail_route else [])]
    out: dict = {
        "rows": [],
        "examined": 0,
        "keyboard": 0,
        "expect": {},
        "themes": {},
    }
    for theme in ("light", "dark"):
        # `localStorage` and then a *real* reload. `goto(url + '#/x')` from `url`
        # is a same-document navigation, so the mode is never re-read and both
        # passes end up measuring one theme — which is exactly how the first
        # version of this sweep reported the light palette for both.
        page.goto(url, wait_until="domcontentloaded")
        page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["ah-theme", theme])
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("#ah-tokens", state="attached")
        page.wait_for_timeout(1200)
        applied = page.evaluate("() => document.documentElement.dataset.theme")
        out["themes"][theme] = applied
        if applied != theme:
            out["rows"].append(
                {
                    "tag": "THEME",
                    "cls": f"requested {theme}, app applied {applied}",
                    "radiusBefore": "",
                    "radiusAfter": "",
                    "width": "",
                    "colour": "",
                    "offset": "",
                    "delegated": False,
                    "animations": [],
                }
            )
        for route in routes:
            page.goto(url.rstrip("/") + "/" + route, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            found = page.evaluate(FOCUS_JS, [FOCUS_SELECTOR, FOCUS_LIMIT])
            out["examined"] += found["count"]
            out["expect"][theme] = found["expect"]
            for row in found["rows"]:
                row["theme"] = theme
                row["route"] = route
                row["pass"] = "synthetic"
            out["rows"].extend(found["rows"])
            # The same route again, this time walked with the Tab key: antd's
            # segmented control only marks itself focused for a real key focus,
            # so the synthetic pass cannot see the ring the reader sees.
            page.goto(url.rstrip("/") + "/" + route, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            page.evaluate("() => { if (document.body) document.body.focus(); }")
            for _ in range(FOCUS_TAB_STEPS):
                page.keyboard.press("Tab")
                row = page.evaluate(FOCUS_ACTIVE_JS)
                if not row:
                    continue
                row["theme"] = theme
                row["route"] = route + " (Tab)"
                row["pass"] = "keyboard"
                out["examined"] += 1
                out["keyboard"] += 1
                out["expect"].setdefault(theme, row.get("expect", ""))
                out["rows"].append(row)
        # One overlay pass per theme. A menu only exists while it is open, and
        # its items are reachable by keyboard (Tab to an icon button, Enter, then
        # Tab again) while the plain walk sees nothing — which is how antd's ring
        # on a dropdown item stayed invisible to this gate.
        page.goto(url.rstrip("/") + "/" + routes[0], wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        opened = False
        for _ in range(24):
            page.keyboard.press("Tab")
            page.wait_for_timeout(60)
            if "ah-iconbtn" in page.evaluate(
                "() => String((document.activeElement || {}).className || '')"
            ):
                page.keyboard.press("Enter")
                page.wait_for_timeout(450)
                opened = True
                break
        if opened:
            page.keyboard.press("Tab")
            page.wait_for_timeout(300)
            found = page.evaluate(
                FOCUS_JS, [FOCUS_OVERLAY_SELECTOR, FOCUS_LIMIT]
            )
            out["examined"] += found["count"]
            for row in found["rows"]:
                row["theme"] = theme
                row["route"] = routes[0] + " (menu open)"
                row["pass"] = "synthetic"
            out["rows"].extend(found["rows"])
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="leave the gallery on disk")
    parser.add_argument(
        "--app",
        action="append",
        metavar="URL",
        default=[],
        help="also sweep a running cockpit (repeatable), e.g. --app http://127.0.0.1:18753/",
    )
    parser.add_argument(
        "--route",
        action="append",
        default=[],
        help="hash route to visit on each --app (repeatable; default #/)",
    )
    parser.add_argument(
        "--focus",
        action="store_true",
        help=(
            "also focus every focusable element on each --app/--route, in both "
            "themes, and check the ring, the radius and the choreography"
        ),
    )
    parser.add_argument(
        "--overlap",
        action="store_true",
        help=(
            "also check that no two rendered controls sit on top of one another, "
            "in both themes and on a session-detail route"
        ),
    )
    args = parser.parse_args()

    if not (WEB / "node_modules").is_dir():
        print(f"{WEB / 'node_modules'} is missing: run `npm ci` in web/ first")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright is not installed in this interpreter. Use the one that has "
            "it, e.g. `D:\\agenthandoff\\.venv\\Scripts\\python.exe "
            "scripts/audit_component_rules.py`."
        )
        return 2

    root = Path(tempfile.mkdtemp(prefix="ah-rule-audit-"))
    print(f"gallery: {root}")
    port = free_port()
    build_gallery(root)
    run(["npx", "--no-install", "vite", "build"], cwd=root)
    # `--host 127.0.0.1` rather than Vite's default `localhost`: on Windows the
    # preview server binds `::1` only, and a probe that asks for the IPv4
    # literal then times out against a server that is running perfectly well.
    log = root / "preview.log"
    with log.open("w", encoding="utf-8") as handle:
        preview = subprocess.Popen(
            [
                "npx", "--no-install", "vite", "preview",
                "--port", str(port), "--strictPort", "--host", "127.0.0.1",
            ],
            cwd=root,
            stdout=handle,
            stderr=subprocess.STDOUT,
            shell=(os.name == "nt"),
        )
    base = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(base, timeout=1)  # noqa: S310 - localhost
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        else:
            print(f"preview server never came up; its log says:\n{log.read_text()}")
            return 2

        rows: list[dict] = []
        sweep: dict[str, dict[str, int]] = {"weights": {}, "sizes": {}}
        with sync_playwright() as pw:
            executable = chromium_path(pw)
            browser = pw.chromium.launch(
                headless=True,
                **({"executable_path": executable} if executable else {}),
            )
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            for url, scope in ((base, "interactive"), (base + "?modal=1", "modal"),
                               (base + "?confirm=1", "confirm")):
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(1400)
                if scope == "interactive":
                    # Open the two surfaces that only exist while open.
                    for selector in (".ah-select-chip", "#g-tooltip"):
                        element = page.query_selector(selector)
                        if element is None:
                            continue
                        try:
                            element.scroll_into_view_if_needed()
                            element.hover(timeout=1500)
                            element.click(timeout=1500)
                        except Exception:  # noqa: BLE001 - the audit reports, it does not fail
                            pass
                        page.wait_for_timeout(700)
                rows.extend(page.evaluate(AUDIT_JS, scope))
                found = page.evaluate(SWEEP_JS)
                for bucket, entries in found.items():
                    for key, count in entries.items():
                        sweep[bucket][key] = sweep[bucket].get(key, 0) + count

            # The running cockpit, if one was named. `domcontentloaded` rather
            # than `networkidle`: the app polls, so the network never goes idle.
            app_sweep: dict[str, dict[str, int]] = {}
            focus: dict = {
                "rows": [],
                "examined": 0,
                "keyboard": 0,
                "expect": "",
                "themes": {},
            }
            overlaps: list[str] = []
            overlap_examined = 0
            for url in args.app:
                if args.overlap:
                    found_overlaps, seen = run_overlap_sweep(
                        page, url, args.route or ["#/"]
                    )
                    overlaps.extend(found_overlaps)
                    overlap_examined += seen
                if args.focus:
                    focus.update(run_focus_sweep(page, url, args.route or ["#/"]))
                for route in (args.route or ["#/"]):
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_selector("#ah-tokens", state="attached")
                    page.wait_for_timeout(1200)
                    page.goto(url.rstrip("/") + "/" + route, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    found = page.evaluate(APP_SWEEP_JS)
                    app_sweep.setdefault("buckets", {})
                    app_sweep.setdefault("tokens", [])
                    app_sweep.setdefault("seen", {})
                    app_sweep["tokens"] = sorted(
                        set(app_sweep["tokens"]) | set(found.get("tokens", []))
                    )
                    for name, entries in found.get("values", {}).items():
                        app_sweep["seen"][name] = sorted(
                            set(app_sweep["seen"].get(name, [])) | set(entries)
                        )
                    for bucket, entries in found.get("buckets", {}).items():
                        target = app_sweep["buckets"].setdefault(bucket, {})
                        for key, count in entries.items():
                            target[key] = target.get(key, 0) + count
            browser.close()
    finally:
        kill_tree(preview)
        if args.keep:
            print(f"kept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    best: dict[str, dict] = {}
    for row in rows:
        if row["rule"] not in best or row["matched"] > best[row["rule"]]["matched"]:
            best[row["rule"]] = row
    rows = list(best.values())
    defects, unverified, _ = reachable(rows)
    matched = sum(1 for r in rows if r["matched"] > 0)
    off_weight, off_size = off_scale(sweep)
    app_weights, app_sizes = off_scale(app_sweep)
    app_colors, app_radii = off_token(app_sweep)
    focus_failures = focus_defects(focus["rows"], focus["expect"]) if args.focus else []
    if args.focus and focus["examined"] < 20:
        # An empty producer is the failure mode this whole script exists to
        # refuse: 0 elements examined is not "no defects", it is "no evidence".
        focus_failures.append(
            f"focus sweep examined only {focus['examined']} elements; "
            "an empty sweep is not a pass"
        )
    if args.focus and focus["keyboard"] < 20:
        # The synthetic pass cannot judge a focusable node with no box (antd's
        # segmented input), so those rows are skipped rather than passed — which
        # means a run whose keyboard pass measured nothing is not a pass either.
        focus_failures.append(
            f"the Tab pass measured only {focus['keyboard']} elements; the nodes "
            "a synthetic focus cannot judge were therefore never judged"
        )
    overlap_failures = overlaps if args.overlap else []
    print(
        json.dumps(
            {
                "rules_reading_component_tokens": len(rows),
                "matched": matched,
                "defects": defects,
                "unverified": unverified,
                "off_scale_font_weights": off_weight,
                "off_scale_font_sizes": off_size,
                "app_off_scale_font_weights": app_weights,
                "app_off_scale_font_sizes": app_sizes,
                "app_colours_in_no_token": app_colors,
                "app_radii_in_no_token": app_radii,
                "overlap_sweep": {
                    "enabled": args.overlap,
                    "controls_examined": overlap_examined,
                    "defects": overlap_failures,
                },
                "focus_sweep": {
                    "enabled": args.focus,
                    "elements_examined": focus["examined"],
                    "examined_by_keyboard": focus["keyboard"],
                    "skipped_synthetic_without_a_box": sum(
                        1
                        for r in focus["rows"]
                        if r.get("invisible") and r.get("pass") == "synthetic"
                    ),
                    "expected_ring": focus["expect"],
                    "themes_applied": focus["themes"],
                    "delegated_rings": sum(
                        1 for r in focus["rows"] if r.get("delegated")
                    ),
                    "defects": focus_failures,
                },
                # How many distinct values the app sweep actually looked at.
                # A violation list is only evidence if nothing produced it
                # vacuously: the brief's own rule is that an empty set from an
                # empty producer is a false green.
                "app_distinct_values_examined": {
                    name: len(entries) for name, entries in app_sweep.get("seen", {}).items()
                },
            },
            indent=2,
        )
    )
    failures = {
        "dead rules": defects,
        "weights": off_weight,
        "sizes": off_size,
        "app weights": app_weights,
        "app sizes": app_sizes,
        "app colours": app_colors,
        "app radii": app_radii,
        "focus": focus_failures,
        "overlapping controls": overlap_failures,
    }
    if any(failures.values()):
        for label, items in failures.items():
            for item in items:
                print(f"  {label}: {item}")
        print(f"\n{len(defects)} rule(s) read component tokens and reach nothing.")
        return 1
    print(f"\nno dead rules. {matched}/{len(rows)} reach an element; "
          f"{len(unverified)} are unverified (see the reasons above). "
          "Every rendered weight is 400 or 500 and every size is an M3 role.")
    if args.focus:
        print(
            f"Focus: {focus['examined']} focusable elements across "
            f"{len(focus['themes'])} themes, ring "
            f"{focus['expect'] or '(none measured)'} at 3px/2px, "
            f"{sum(1 for r in focus['rows'] if r.get('delegated'))} delegated "
            "to the box the reader sees."
        )
    if args.overlap:
        print(
            f"Overlap: {overlap_examined} controls compared across two themes "
            "and a session detail; no two interactives sit on top of one another."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
