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
import contextlib
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
    // The element *and* three ancestors, because an off-token value is usually
    // painted by a rule on an ancestor and reported on the node that inherits
    // it: the first version said `path.[object` and left the reader to guess
    // which popup it was in.
    const where =
      el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0] +
      (() => {
        const chain = [];
        let node = el.parentElement;
        for (let i = 0; i < 3 && node && node.tagName !== 'BODY'; i += 1) {
          chain.push(node.tagName.toLowerCase() + '.' + String(node.className).split(' ')[0]);
          node = node.parentElement;
        }
        return chain.length ? ' < ' + chain.join(' < ') : '';
      })();
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

const params = new URLSearchParams(location.search);
const wantModal = params.has("modal");
const wantConfirm = params.has("confirm");
// The gallery used to be dark-only, which meant every computed value the audit
// read from it was dark-only too — including the disabled opacities, where the
// light and dark palettes composite different inks. `?theme=light` is the same
// page against the other palette.
const THEME = params.get("theme") === "light" ? "light" : "dark";
localStorage.setItem("ah-theme", THEME);
applyTheme(THEME);

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
        {/* The three families the audit used to list as *unverified* because the
            gallery did not mount them: a dot Badge (the cockpit shows counts,
            never dots), a vertical Divider and a link Button. Mounting them is
            what turns "no rule reads this" into a measurement. */}
        <Badge dot id="g-badge-dot"><span>dot</span></Badge>
        <Button type="link" id="g-btn-link">link</Button>
        <span>a<Divider type="vertical" id="g-divider-v" />b</span>
        {/* Disabled variants: the live product has exactly two (the pager's
            previous button on page one), so disabled geometry has to be measured
            where it exists — here. */}
        <button className="ah-iconbtn" disabled id="g-ah-iconbtn-disabled"><span className="anticon">+</span></button>
        <button className="ah-fab" disabled id="g-ah-fab-disabled"><span className="anticon">+</span></button>
        <button className="ah-mchip ah-mchip--filter" disabled id="g-ah-chip-disabled">chip</button>
        <button className="ah-filterchip" disabled id="g-ah-filterchip-disabled">filter</button>
        <Button type="primary" disabled id="g-btn-disabled-primary">primary</Button>
        <Button disabled id="g-btn-disabled-default">default</Button>
        <Switch disabled id="g-switch-disabled" />
        <Checkbox disabled id="g-checkbox-disabled">off</Checkbox>
        <Radio disabled id="g-radio-disabled">off</Radio>
        <Segmented disabled options={["a", "b"]} id="g-segmented-disabled" />
        <Select disabled className="ah-select-chip" placeholder="off" options={[{ value: "a", label: "a" }]} id="g-select-chip-disabled" />
        <Input disabled placeholder="off" id="g-input-disabled" />
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


# ── Eclipsed rules ───────────────────────────────────────────────────────────
#
# The sweeps above ask whether *our* rule exists and whether it reaches an
# element. They cannot ask whether it *wins*: antd writes its rules with
# `:where(.css-hash)`, which drops the hash from the specificity count but not
# the classes around it, and its stylesheet is injected into the head *after*
# this bundle. So a rule of ours can match an element, be reported as reaching
# it, and still lose — which is how the display-settings menu kept antd's
# 14px/22px row while the token said body-large 16px/24px, and how nothing
# failed. The check is the only one that needs to know antd's selector shape, so
# each entry names it in full and says which token has to win.

# The routes the cockpit actually has, so the sweep covers the surfaces rather
# than the one the app opens on. Measured with a family inventory on 2026-09-12:
# the dashboard draws segmented controls and a Select, the inbox draws switches
# and the empty state, the threads view draws the sliders, and the two table
# views are the doctor's and the memory export's.
LIST_ROUTES: tuple[str, ...] = ("#/", "#/inbox", "#/threads", "#/memory", "#/doctor")

# ── The M3E press morph ──────────────────────────────────────────────────────
#
# M3E buttons and chips answer a press with *geometry*: the corner goes from the
# resting rung to the pressed one and back, on a spatial spring. The stylesheet
# says so in seven places and `--states` has been recording the radius on every
# press since it was written 鈥?without ever asserting it. This is that assertion:
# the resting radius, the radius while held (or hovered, for a list item) and the
# radius after release all have to equal the token the component names, and the
# transition has to run on the published curve rather than the browser default.
MORPH: tuple[dict[str, str], ...] = (
    {
        "label": "small button",
        "selector": ".ah-btn:not(.ah-btn--medium):not(.ah-btn--large)",
        "rest": "--ah-c-button-sizes-small-shape",
        "moved": "--ah-c-button-sizes-small-shape-pressed",
        "how": "press",
    },
    {
        "label": "medium button",
        "selector": ".ah-btn--medium",
        "rest": "--ah-c-button-sizes-medium-shape",
        "moved": "--ah-c-button-sizes-medium-shape-pressed",
        "how": "press",
    },
    {
        "label": "large button",
        "selector": ".ah-btn--large",
        "rest": "--ah-c-button-sizes-large-shape",
        "moved": "--ah-c-button-sizes-large-shape-pressed",
        "how": "press",
    },
    {
        "label": "icon button",
        "selector": ".ah-iconbtn",
        "rest": "--ah-c-icon-button-small-shape",
        "moved": "--ah-c-icon-button-small-shape-pressed",
        "how": "press",
    },
    {
        "label": "assist chip",
        "selector": ".ah-mchip--assist",
        "rest": "--ah-c-chip-variant-assist-shape",
        "moved": "--ah-c-chip-variant-assist-shape-pressed",
        "how": "press",
    },
    {
        "label": "filter chip",
        "selector": ".ah-mchip--filter",
        "rest": "--ah-c-chip-variant-filter-shape",
        "moved": "--ah-c-chip-variant-filter-shape-pressed",
        "how": "press",
    },
    {
        "label": "input chip",
        "selector": ".ah-mchip--input",
        "rest": "--ah-c-chip-variant-input-shape",
        "moved": "--ah-c-chip-variant-input-shape-pressed",
        "how": "press",
    },
    {
        "label": "list item",
        "selector": ".ah-li",
        "rest": "--ah-c-list-item-shape-rest",
        "moved": "--ah-c-list-item-shape-hover",
        "how": "hover",
    },
)
MORPH_CURVE = "--ah-ease-fast-spatial"
MORPH_DURATION = "--ah-dur-fast-spatial"


def run_morph_sweep(page, url: str, theme: str) -> dict:
    """Press (or hover) each morphing family and read its corner at every step."""

    page.goto(f"{url}?theme={theme}", wait_until="domcontentloaded")
    page.wait_for_selector("#ah-tokens", state="attached")
    page.wait_for_timeout(1400)
    rows: list[dict] = []
    for entry in MORPH:
        element = page.query_selector(entry["selector"])
        if element is None:
            rows.append({"label": entry["label"], "theme": theme, "missing": True})
            continue
        element.scroll_into_view_if_needed(timeout=2000)
        box = element.bounding_box()
        if not box or box["width"] < 6 or box["height"] < 6:
            rows.append({"label": entry["label"], "theme": theme, "missing": True})
            continue
        tokens = page.evaluate(
            "(names) => { const s = getComputedStyle(document.documentElement);"
            " const out = {}; for (const n of names) out[n] = s.getPropertyValue(n).trim();"
            " return out; }",
            [entry["rest"], entry["moved"], MORPH_CURVE, MORPH_DURATION],
        )
        page.evaluate("(el) => { window.__morphEl = el; }", element)
        page.mouse.move(5, 5)
        page.wait_for_timeout(40)
        row = {
            "label": entry["label"],
            "theme": theme,
            "rest_token": tokens[entry["rest"]],
            "moved_token": tokens[entry["moved"]],
            "curve_token": tokens[MORPH_CURVE],
            "duration_token": tokens[MORPH_DURATION],
            "rest": morph_corner(page),
            "transition": morph_transition(page),
        }
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        if entry["how"] == "press":
            page.mouse.down()
        page.wait_for_timeout(260)
        row["moved"] = morph_corner(page)
        if entry["how"] == "press":
            page.mouse.up()
        page.mouse.move(5, 5)
        page.wait_for_timeout(600)
        row["after"] = morph_corner(page)
        rows.append(row)
    return {"rows": rows}


def morph_corner(page) -> str:
    """The corner, after every finite animation on the element has been settled.

    Settling first is what makes this a measurement rather than a race: a
    transition read 40ms in is a point *on* the curve, not the value the token
    names.
    """

    return page.evaluate(
        """() => {
      const el = window.__morphEl;
      if (!el) return null;
      el.getAnimations({subtree: true}).forEach((a) => {
        const t = a.effect && a.effect.getComputedTiming();
        if (!t || t.iterations === Infinity) return;
        try { a.finish(); } catch (err) {}
      });
      return getComputedStyle(el).borderTopLeftRadius;
    }"""
    )


def morph_transition(page) -> str:
    """The timing function and duration that the browser applies to `border-radius`.

    Not `transition` read as one string: a button transitions seven properties,
    the first of which is `box-shadow` on the *effects* curve, so a substring
    search finds the wrong spring and reports every morph as off-curve. The
    computed `transition-property`/`-timing-function`/`-duration` lists are
    index-aligned, so the corner's own entry is the one to compare.
    """

    return page.evaluate(
        """() => {
      const el = window.__morphEl;
      if (!el) return null;
      const cs = getComputedStyle(el);
      // A comma-separated CSS list, split at depth 0: `linear(0 0%, .5 50%)`
      // contains commas of its own, and splitting naively hands back half a
      // curve ("0.065 4.2%") which then never matches the token.
      const split = (text) => {
        const out = [];
        let depth = 0;
        let current = '';
        for (const ch of text) {
          if (ch === '(') depth += 1;
          if (ch === ')') depth -= 1;
          if (ch === ',' && depth === 0) { out.push(current.trim()); current = ''; continue; }
          current += ch;
        }
        if (current.trim()) out.push(current.trim());
        return out;
      };
      const props = split(cs.transitionProperty);
      const timing = split(cs.transitionTimingFunction);
      const duration = split(cs.transitionDuration);
      const index = props.indexOf('border-radius');
      if (index < 0) return {timing: '', duration: '', property: null};
      return {
        property: 'border-radius',
        timing: timing[index] || '',
        duration: duration[index] || '',
      };
    }"""
    )


def _curve_values(text: str) -> list[float] | None:
    """The sample values of a `linear()` easing, in order.

    Percentages are dropped rather than compared: Chrome rewrites an implicit
    first stop (`linear(0, 0.056 4.2%, ...)`) as an explicit one (`linear(0 0%,
    0.056 4.2%, ...)`), so two spellings of one curve differ as text. The values
    themselves are what the curve *is*.
    """

    if not isinstance(text, str) or "linear(" not in text:
        return None
    inner = text[text.index("linear(") + len("linear(") :]
    inner = inner.split(")", 1)[0]
    values: list[float] = []
    for stop in inner.split(","):
        numbers = re.findall(r"[-+]?[0-9]*\.?[0-9]+", stop)
        if numbers:
            values.append(float(numbers[0]))
    return values or None


def morph_defects(rows: list[dict]) -> list[str]:
    """Every corner has to be the token it names, and the move has to be on curve."""

    defects: list[str] = []
    for row in rows:
        where = f"{row['label']} ({row['theme']})"
        if row.get("missing"):
            defects.append(f"{where}: nothing matches the selector")
            continue
        for step, token in (
            ("rest", "rest_token"),
            ("moved", "moved_token"),
            ("after", "rest_token"),
        ):
            got, want = _px(row.get(step)), _px(row.get(token))
            if got is None or want is None or abs(got - want) > 0.01:
                defects.append(
                    f"{where}: the corner {step} the press is {row.get(step)}, "
                    f"but the token {row.get(token)} says {row.get(token) and row[token]}"
                )
        transition = row.get("transition") or {}
        token_values = _curve_values(str(row.get("curve_token", "")))
        computed_values = _curve_values(str(transition.get("timing", "")))
        if not token_values:
            defects.append(f"{where}: {MORPH_CURVE} is not defined")
        elif transition.get("property") != "border-radius":
            defects.append(
                f"{where}: nothing transitions the corner, so there is no morph to "
                "be on a curve"
            )
        elif not computed_values or [
            round(value, 3) for value in computed_values[:12]
        ] != [round(value, 3) for value in token_values[:12]]:
            defects.append(
                f"{where}: the corner runs on {str(transition.get('timing'))[:70]!r}, "
                f"not the {MORPH_CURVE} samples "
                f"{[round(v, 3) for v in token_values[:6]]}"
            )
        expected_duration = _seconds(str(row.get("duration_token", "")))
        measured_duration = _seconds(str(transition.get("duration", "")))
        if expected_duration is not None and measured_duration != expected_duration:
            defects.append(
                f"{where}: the corner takes {transition.get('duration')}, but "
                f"{MORPH_DURATION} is {row.get('duration_token')}"
            )
    return defects


def _seconds(text: str) -> float | None:
    """`'240ms'` and `'0.24s'` are the same duration; compare them as seconds."""

    text = text.strip()
    for suffix, scale in (("ms", 0.001), ("s", 1.0)):
        if text.endswith(suffix):
            try:
                return round(float(text[: -len(suffix)]) * scale, 6)
            except ValueError:
                return None
    return None


def _px(value: object) -> float | None:
    """`'12px'` -> 12.0, `'9999px'` -> 9999.0, anything else -> None."""

    if not isinstance(value, str) or not value.endswith("px"):
        return None
    try:
        return float(value[:-2])
    except ValueError:
        return None


def run_dialog_sweep(page, base: str, theme: str) -> dict:
    """Open a confirm dialog, then close it, reading both springs while they run.

    The enter animation is easy to catch; the exit one only exists for the ~360ms
    between the click and antd unmounting the node, so it is read 60ms in. A
    dialog that simply disappears never reaches this code path at all, which is
    the defect this is here to catch.
    """

    page.goto(f"{base}?confirm=1&theme={theme}", wait_until="domcontentloaded")
    page.wait_for_selector(".ant-modal-container", state="attached", timeout=8000)
    page.wait_for_timeout(700)
    tokens = page.evaluate(
        """() => {
      const s = getComputedStyle(document.documentElement);
      return {
        enterDuration: s.getPropertyValue('--ah-c-dialog-enter-duration').trim(),
        enterEasing: s.getPropertyValue('--ah-c-dialog-enter-easing').trim(),
        exitDuration: s.getPropertyValue('--ah-c-dialog-exit-duration').trim(),
        exitEasing: s.getPropertyValue('--ah-c-dialog-exit-easing').trim(),
      };
    }"""
    )
    enter = page.evaluate(
        """() => {
      const el = document.querySelector('.ant-modal-container');
      if (!el) return null;
      const cs = getComputedStyle(el);
      return {name: cs.animationName, duration: cs.animationDuration,
              timing: cs.animationTimingFunction};
    }"""
    )
    ok = page.query_selector(".ant-modal-confirm-btns .ant-btn-primary")
    if ok is None:
        ok = page.query_selector(".ant-btn-primary")
    if ok is not None:
        ok.click()
    page.wait_for_timeout(60)
    leave = page.evaluate(
        """() => {
      const el = document.querySelector('.ant-modal-container');
      if (!el) return {name: null, duration: null, timing: null, gone: true};
      const cs = getComputedStyle(el);
      return {name: cs.animationName, duration: cs.animationDuration,
              timing: cs.animationTimingFunction, gone: false};
    }"""
    )
    return {
        "rows": [
            {
                "label": "dialog",
                "theme": theme,
                "tokens": tokens,
                "enter": enter,
                "exit": leave,
            }
        ]
    }


def run_snackbar_sweep(page, base: str, theme: str) -> dict:
    """Read the snackbar's transition in both phases, while each is running.

    The gallery raises one `message.success` on mount, so the appear phase is
    there to read; the leave phase needs waiting for antd's own 3s timer, which is
    the only way to see the curve a reader gets when it is dismissed.
    """

    page.goto(f"{base}?theme={theme}", wait_until="domcontentloaded")
    page.wait_for_selector(".ant-message-notice", state="attached", timeout=8000)
    page.wait_for_timeout(120)
    tokens = page.evaluate(
        """() => {
      const s = getComputedStyle(document.documentElement);
      return {
        enter: s.getPropertyValue('--ah-motion-duration-medium2').trim(),
        enterCurve: s.getPropertyValue('--ah-motion-easing-emphasized-decelerate').trim(),
        leave: s.getPropertyValue('--ah-motion-duration-short4').trim(),
        leaveCurve: s.getPropertyValue('--ah-motion-easing-emphasized-accelerate').trim(),
      };
    }"""
    )
    read = """() => {
      const notice = document.querySelector('.ant-message-notice');
      if (!notice) return null;
      const cs = getComputedStyle(notice);
      const split = (text) => {
        const out = []; let depth = 0; let current = '';
        for (const ch of text) {
          if (ch === '(') depth += 1;
          if (ch === ')') depth -= 1;
          if (ch === ',' && depth === 0) { out.push(current.trim()); current = ''; continue; }
          current += ch;
        }
        if (current.trim()) out.push(current.trim());
        return out;
      };
      const props = split(cs.transitionProperty);
      const opacity = props.indexOf('opacity');
      return {
        cls: String(notice.className),
        property: props[opacity] || null,
        duration: split(cs.transitionDuration)[opacity] || null,
        timing: split(cs.transitionTimingFunction)[opacity] || null,
      };
    }"""
    appear = page.evaluate(read)
    # antd's own timer dismisses it; poll for the leave class rather than
    # guessing a duration.
    leave = None
    for _ in range(40):
        page.wait_for_timeout(150)
        candidate = page.evaluate(read)
        if candidate and "leave" in candidate["cls"]:
            leave = candidate
            break
    return {
        "rows": [
            {
                "label": "snackbar",
                "theme": theme,
                "tokens": tokens,
                "appear": appear,
                "leave": leave,
            }
        ]
    }


def run_tooltip_sweep(page, base: str, theme: str) -> dict:
    """Hover the tooltip anchor, then leave it, reading both animations."""

    page.goto(f"{base}?theme={theme}", wait_until="domcontentloaded")
    page.wait_for_selector("#g-tooltip", state="attached", timeout=8000)
    page.wait_for_timeout(700)
    tokens = page.evaluate(
        """() => {
      const s = getComputedStyle(document.documentElement);
      return {
        appear: s.getPropertyValue('--ah-motion-duration-short4').trim(),
        appearCurve: s.getPropertyValue('--ah-motion-easing-emphasized-decelerate').trim(),
        leave: s.getPropertyValue('--ah-motion-duration-short3').trim(),
        leaveCurve: s.getPropertyValue('--ah-motion-easing-emphasized-accelerate').trim(),
      };
    }"""
    )
    read = """() => {
      const tip = document.querySelector('.ant-tooltip');
      if (!tip) return null;
      const cs = getComputedStyle(tip);
      return {cls: String(tip.className), name: cs.animationName,
              duration: cs.animationDuration,
              timing: String(cs.animationTimingFunction)};
    }"""
    anchor = page.query_selector("#g-tooltip")
    if anchor is not None:
        anchor.hover()
    appear = None
    for _ in range(20):
        page.wait_for_timeout(50)
        candidate = page.evaluate(read)
        if candidate and candidate["name"] not in (None, "none", "") and "appear" in candidate["cls"]:
            appear = candidate
            break
    page.mouse.move(5, 5)
    leave = None
    for _ in range(30):
        page.wait_for_timeout(50)
        candidate = page.evaluate(read)
        if candidate and "leave" in candidate["cls"]:
            leave = candidate
            break
    return {
        "rows": [
            {
                "label": "tooltip",
                "theme": theme,
                "tokens": tokens,
                "appear": appear,
                "leave": leave,
            }
        ]
    }


def tooltip_defects(rows: list[dict]) -> list[str]:
    """Both phases have to be our keyframes on the published system tokens."""

    defects: list[str] = []
    for row in rows:
        where = f"tooltip ({row['theme']})"
        tokens = row.get("tokens") or {}
        for phase, want_name, duration_key, curve_key in (
            ("appear", "ah-tooltip-in", "appear", "appearCurve"),
            ("leave", "ah-tooltip-out", "leave", "leaveCurve"),
        ):
            seen = row.get(phase)
            if not seen:
                defects.append(
                    f"{where}: the {phase} animation was never observed, so the "
                    f"tooltip's {phase} motion is unmeasured"
                )
                continue
            if seen.get("name") != want_name:
                defects.append(
                    f"{where}: the {phase} runs {seen.get('name')!r} "
                    f"({seen.get('duration')} {str(seen.get('timing'))[:40]!r}), not "
                    f"{want_name} on the system tokens"
                )
                continue
            expected = _seconds(str(tokens.get(duration_key, "")))
            measured = _seconds(str(seen.get("duration", "")))
            if expected is not None and measured != expected:
                defects.append(
                    f"{where}: the {phase} takes {seen.get('duration')}, but the "
                    f"token says {tokens.get(duration_key)}"
                )
            curve = str(tokens.get(curve_key, "")).strip()
            timing = str(seen.get("timing", "")).strip()
            if curve and " ".join(timing.split()) != " ".join(curve.split()):
                defects.append(
                    f"{where}: the {phase} runs on {timing!r}, not {curve_key} {curve!r}"
                )
    return defects


def snackbar_defects(rows: list[dict]) -> list[str]:
    """Both phases have to run on the published system tokens, not antd's curve."""

    defects: list[str] = []
    for row in rows:
        where = f"snackbar ({row['theme']})"
        tokens = row.get("tokens") or {}
        for phase, duration_key, curve_key in (
            ("appear", "enter", "enterCurve"),
            ("leave", "leave", "leaveCurve"),
        ):
            seen = row.get(phase)
            if not seen:
                defects.append(
                    f"{where}: the {phase} phase was never observed, so the snackbar's "
                    f"{phase} curve is unmeasured"
                )
                continue
            if seen.get("property") != "opacity":
                defects.append(
                    f"{where}: nothing transitions the {phase} opacity "
                    f"(property list has {seen.get('property')!r})"
                )
                continue
            expected = str(tokens.get(duration_key, "")).strip()
            measured = str(seen.get("duration", "")).strip()
            if expected:
                got, want = _seconds(measured), _seconds(expected)
                if got is None or want is None or got != want:
                    defects.append(
                        f"{where}: the {phase} takes {measured}, but the token says "
                        f"{expected}"
                    )
            curve = str(tokens.get(curve_key, "")).strip()
            timing = str(seen.get("timing", "")).strip()
            if curve and " ".join(timing.split()) != " ".join(curve.split()):
                defects.append(
                    f"{where}: the {phase} runs on {timing!r}, not {curve_key} {curve!r}"
                )
    return defects


def dialog_defects(rows: list[dict]) -> list[str]:
    """Both springs: the published curve, the published duration, actually running."""

    defects: list[str] = []
    for row in rows:
        where = f"dialog ({row['theme']})"
        tokens = row.get("tokens") or {}
        for phase, name, duration_key, easing_key in (
            ("enter", "ah-dialog-in", "enterDuration", "enterEasing"),
            ("exit", "ah-dialog-out", "exitDuration", "exitEasing"),
        ):
            seen = row.get(phase) or {}
            if seen.get("name") != name:
                defects.append(
                    f"{where}: the {phase} animation is {seen.get('name')!r}, so the "
                    f"dialog does not play {name}"
                )
                continue
            expected = _seconds(str(tokens.get(duration_key, "")))
            measured = _seconds(str(seen.get("duration", "")))
            if expected is not None and measured != expected:
                defects.append(
                    f"{where}: the {phase} takes {seen.get('duration')}, but "
                    f"the token says {tokens.get(duration_key)}"
                )
            token_values = _curve_values(str(tokens.get(easing_key, "")))
            computed = _curve_values(str(seen.get("timing", "")))
            if not token_values:
                defects.append(f"{where}: {easing_key} is not a sampled curve")
            elif not computed:
                # Saying "could not be read" here would read like a limitation of
                # the check. It is not: the animation is on a curve that is not a
                # token, which is the defect.
                defects.append(
                    f"{where}: the {phase} runs on {str(seen.get('timing'))[:60]!r}, "
                    f"not the sampled {easing_key} [{', '.join(str(v) for v in token_values[:4])}...]"
                )
            elif [round(v, 3) for v in computed[:8]] != [
                round(v, 3) for v in token_values[:8]
            ]:
                defects.append(
                    f"{where}: the {phase} runs on {str(seen.get('timing'))[:60]!r}, "
                    f"not {easing_key} {[round(v, 3) for v in token_values[:4]]}"
                )
    return defects


ECLIPSED: tuple[dict[str, str], ...] = (
    {
        "label": "dropdown menu item type",
        "when": "dropdown",
        "selector": ":root .ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item",
        "against": ".ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item",
        "property": "fontSize",
        "token": "--ah-c-menu-type-role-size",
    },
    {
        "label": "dropdown menu item ink",
        "when": "dropdown",
        "selector": ":root .ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item",
        "against": ".ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item",
        "property": "color",
        "token": "--ah-c-menu-content",
    },
    {
        "label": "dropdown menu item corner",
        "when": "dropdown",
        "selector": ":root .ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item",
        "against": ".ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item",
        "property": "borderRadius",
        "token": "--ah-c-menu-item-shape",
    },
    {
        "label": "dropdown menu corner",
        "when": "dropdown",
        "selector": ":root .ant-dropdown .ant-dropdown-menu",
        "against": ".ant-dropdown .ant-dropdown-menu",
        "property": "borderRadius",
        "token": "--ah-c-menu-shape",
    },
    {
        "label": "select item type",
        "when": "select",
        "selector": ":root .ant-select-dropdown .ant-select-item",
        "against": ".ant-select-dropdown .ant-select-item",
        "property": "fontSize",
        "token": "--ah-c-menu-type-role-size",
    },
    {
        "label": "select item ink",
        "when": "select",
        "selector": ":root .ant-select-dropdown .ant-select-item",
        "against": ".ant-select-dropdown .ant-select-item",
        "property": "color",
        "token": "--ah-c-menu-content",
    },
    {
        "label": "select popup corner",
        "when": "select",
        "selector": ":root .ant-select-dropdown",
        "against": ".ant-select-dropdown",
        "property": "borderRadius",
        "token": "--ah-c-menu-shape",
    },
    # The rest of what the product mounts, measured rather than assumed: these
    # are the families the family inventory found on a real route
    # (table, segmented, switch, slider, progress, tooltip), each of which antd
    # also paints. A rule of ours that matches but loses shows up here.
    {
        "label": "segmented item type",
        "when": "page",
        "selector": ":root .ant-segmented .ant-segmented-item",
        "against": ".ant-segmented .ant-segmented-item",
        "property": "fontSize",
        "token": "--ah-c-segmented-type-role-size",
    },
    {
        "label": "segmented item corner",
        "when": "page",
        "selector": ":root .ant-segmented .ant-segmented-item",
        "against": ".ant-segmented .ant-segmented-item",
        "property": "borderRadius",
        "token": "--ah-c-segmented-shape",
    },
    {
        "label": "switch track width",
        "when": "page",
        "route": "#/inbox",
        "selector": ":root .ant-switch",
        "against": ".ant-switch",
        "property": "width",
        "token": "--ah-c-switch-track-width",
    },
    {
        "label": "switch track corner",
        "when": "page",
        "route": "#/inbox",
        "selector": ":root .ant-switch",
        "against": ".ant-switch",
        "property": "borderRadius",
        "token": "--ah-c-switch-track-shape",
    },
    {
        "label": "slider rail height",
        "when": "page",
        "route": "#/threads",
        "selector": ":root .ant-slider .ant-slider-rail",
        "against": ".ant-slider .ant-slider-rail",
        "property": "height",
        "token": "--ah-c-slider-track-height",
    },
    {
        "label": "slider rail ink",
        "when": "page",
        "route": "#/threads",
        "selector": ":root .ant-slider .ant-slider-rail",
        "against": ".ant-slider .ant-slider-rail",
        "property": "backgroundColor",
        "token": "--ah-c-slider-inactive",
    },
    {
        "label": "table head weight",
        "when": "page",
        "route": "#/doctor",
        "selector": ":root .ant-table-thead > tr > th",
        "against": ".ant-table-thead > tr > th",
        "property": "fontWeight",
        "token": "--ah-type-label-large-weight",
    },
    {
        "label": "tooltip bubble ink",
        "when": "tooltip",
        "selector": ":root .ant-tooltip .ant-tooltip-container",
        "against": ".ant-tooltip .ant-tooltip-container",
        "property": "backgroundColor",
        "token": "--ah-c-tooltip-container",
    },
    {
        "label": "tooltip bubble corner",
        "when": "tooltip",
        "selector": ":root .ant-tooltip .ant-tooltip-container",
        "against": ".ant-tooltip .ant-tooltip-container",
        "property": "borderRadius",
        "token": "--ah-c-tooltip-shape",
    },
    {
        "label": "tooltip bubble type",
        "when": "tooltip",
        "selector": ":root .ant-tooltip .ant-tooltip-container",
        "against": ".ant-tooltip .ant-tooltip-container",
        "property": "fontSize",
        "token": "--ah-c-tooltip-type-role-size",
    },
)


def eclipse_rows(page, items: tuple[dict[str, str], ...]) -> list[dict]:
    """Read the computed value and the token value, on the element that renders.

    The element is found with the *antd* selector (`against`), so the check
    cannot pass by matching a wrapper of our own; the token is resolved through a
    probe element, because a custom property holds `#1d1b20` where the computed
    colour is `rgb(29, 27, 32)`.
    """

    return page.evaluate(
        """(items) => {
      const root = getComputedStyle(document.documentElement);
      const probe = document.createElement('span');
      probe.style.position = 'absolute';
      document.body.appendChild(probe);
      const rows = [];
      for (const item of items) {
        const el = document.querySelector(item.against);
        const raw = root.getPropertyValue(item.token).trim();
        // Only a colour needs resolving: `4px` handed to `style.color` is
        // invalid, and the probe then reports the colour it inherited, which is
        // how this comparison first reported every radius as a mismatch.
        let token = raw;
        if (/^(#|rgb|hsl|color\\()/i.test(raw)) {
          probe.style.color = raw;
          token = getComputedStyle(probe).color;
        }
        rows.push({
          label: item.label,
          selector: item.against,
          property: item.property,
          token_name: item.token,
          token: token,
          raw_token: raw,
          computed: el ? getComputedStyle(el)[item.property] : null,
        });
      }
      probe.remove();
      return rows;
    }""",
        list(items),
    )


def eclipse_defects(rows: list[dict]) -> list[str]:
    """Where the token and the pixels disagree, in either direction.

    Grouped by label, because an entry is read once per route and it only has to
    exist on *one* of them: a switch is on the inbox, a slider on the threads
    view, and reporting "nothing matches" for the four routes that legitimately
    do not draw one would bury the entries that never matched anywhere.
    """

    defects: list[str] = []
    by_label: dict[str, list[dict]] = {}
    for row in rows:
        by_label.setdefault(row["label"], []).append(row)
    for label, group in sorted(by_label.items()):
        if not group[0].get("raw_token"):
            defects.append(f"{label}: {group[0]['token_name']} is not defined")
            continue
        seen = [row for row in group if row.get("computed") is not None]
        if not seen:
            defects.append(
                f"{label}: nothing matched {group[0]['selector']} on any of the "
                f"{len(group)} route(s) swept"
            )
            continue
        for row in seen:
            got, want = row["computed"], row["token"]
            if row["property"] in {"fontSize", "borderRadius"}:
                got = f"{float(got.rstrip('px'))}px"
                want = f"{float(want.rstrip('px'))}px"
            if _rgb(got) != _rgb(want):
                defects.append(
                    f"{label}: {row['selector']} computes {got}, "
                    f"but {row['token_name']} is {want}"
                )
    return defects


# Computed values the sweep is *expected* to find and that are not defects, each
# with the reason it is allowed. The pattern matches the element half of a
# bucket key (`<value> :: <tag>.<class>`). Allowed rows are still reported, with
# their reason, so this cannot become a place where a real off-token value hides:
# anything that does not match a pattern below stays a defect.
OFF_TOKEN_ALLOWED: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^span\.hljs-[a-z]+(?: | < |$)"),
        "the vendored highlight.js syntax palette: it colours code, not chrome",
    ),
    (
        re.compile(r"^code\.hljs(?: | < |$)"),
        "the code block's own ink, from the same vendored syntax palette",
    ),
    (
        re.compile(r"^tr\.(?: | < |$)"),
        "a zebra stripe: color-mix(surface-2 45%, transparent) inside rendered "
        "Markdown, so the value is derived from a token rather than being one",
    ),
)


def off_token(sweep: dict) -> tuple[list[str], list[str], list[str]]:
    """Colours and radii from a running app that are in no token anywhere.

    Weights and sizes are closed sets and `off_scale` checks them exactly.
    Colours and radii are open — a value is only wrong if *nothing* in the token
    table equals it — so this is the weaker question, and it is the one that
    found a status tag at 3.37:1 whose pair antd's algorithm derived.
    """
    tokens = {_rgb(value) for value in sweep.get("tokens", [])}
    buckets = sweep.get("buckets", {})
    allowed: list[str] = []

    def token_at_alpha(value: str) -> str | None:
        """A `color-mix(in srgb, <token> N%, transparent)` result, or None.

        The mix keeps the token's channels and takes its alpha from the
        percentage, so un-mixing is exact rather than a tolerance: if the
        channels are a token's, the value *is* that token at N%. That is a
        stronger statement than an allowlist of selectors, and it is what makes
        every disabled ink in the sheet (38% of on-surface) legal without listing
        the components that spend it.
        """

        match = re.fullmatch(
            r"color\(srgb ([0-9.]+) ([0-9.]+) ([0-9.]+)(?: / ([0-9.]+))?\)", value
        )
        if not match:
            return None
        red, green, blue, alpha = (float(part) for part in match.groups(default="1"))
        if alpha >= 0.999:
            return None
        channels = f"rgb({round(red * 255)}, {round(green * 255)}, {round(blue * 255)})"
        return f"{channels} at {round(alpha * 100)}% alpha" if channels in tokens else None

    def rows(bucket: str) -> list[str]:
        out: list[str] = []
        for key, count in buckets.get(bucket, {}).items():
            value = key.split(" :: ")[0]
            if _rgb(value) in tokens:
                continue
            mixed = token_at_alpha(value)
            if mixed is not None:
                allowed.append(f"{key} (x{count}) -- {mixed}, a token with a state layer on it")
                continue
            where = key.split(" :: ", 1)[1] if " :: " in key else ""
            reason = next(
                (text for pattern, text in OFF_TOKEN_ALLOWED if pattern.match(where)),
                None,
            )
            if reason is not None:
                allowed.append(f"{key} (x{count}) -- {reason}")
                continue
            out.append(f"{key} (x{count})")
        return sorted(out)

    return rows("colors"), rows("radii"), sorted(allowed)


def reachable(
    rows: list[dict], unopened: tuple[str, ...] = ()
) -> tuple[list[str], list[str], list[str]]:
    """Split the audit into defects, unverified and fine.

    A rule is a **defect** when it reads component tokens, matches nothing, and
    is not a state, not a transient popup, and not a component the gallery does
    not mount. Everything else is reported rather than hidden: `unverified` is
    the honest middle, and a maintainer can move a name out of `UNMOUNTED` by
    mounting it.

    `unopened` names rules whose surface the sweep tried and failed to open (a
    click or a hover that timed out on a loaded machine). Those are **unverified**,
    not dead: the gallery reported `:root .ant-select-item` and the tooltip
    container as "dead rules" on a run where the machine was busy enough that the
    popups never appeared, and the product proved both alive in the same minute.
    A gate that calls a load flake a defect is worse than one that says it does
    not know.
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
        elif any(name in rule for name in unopened):
            unverified.append(
                f"{rule}  (the sweep could not open the surface it lives in: "
                "a click or hover timed out, so this run does not know)"
            )
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


# ── Hover and press ─────────────────────────────────────────────────────────
# The focus ring taught this tool that a static read is not evidence. These are
# the states a pointer produces, and the check is the same shape: put the real
# mouse on the control, let the transitions *settle*, and compare what changed
# against the token table and against the published opacities (hover 8%, pressed
# 12%). It found what reading the sheet did not: every icon button answered the
# pointer with nothing at all — hover layer alpha `0.000` on all ten of them —
# because the family had a press rule and no hover rule.
STATE_SELECTOR = (
    'button, [role="button"], .ah-row, .ah-tab, .ah-filterchip, '
    ".ah-select-chip, .ant-segmented-item, .ant-slider-handle"
)
STATE_LIMIT = 22  # per route, per theme
# Sample by *family*, not by document order: a route with 187 rows would
# otherwise spend every slot on rows and never reach the controls below them.
# antd's runtime hash classes are stripped first, so `ant-btn css-wgezi7` and
# `ant-btn css-abc123` are one family.
# `query_selector_all` hands back handles that React invalidates on its next
# render — measured as 16 of 25 families skipped with "Element is not attached to
# the DOM", i.e. the sweep was quietly sampling only the controls that happened
# to survive. These two functions replace handles with a family key plus a live
# index, and the interaction goes through a locator, which re-resolves.
STATE_FAMILIES_JS = r"""
([sel, limit]) => {
  const key = (el) => el.tagName + "." + String(el.className)
    .split(" ")
    .filter(c => c && !/^css-[a-z0-9]+$/i.test(c) && !/^css-var-/i.test(c))
    .slice(0, 3)
    .join(".");
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(sel)) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") continue;
    if (el.disabled) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const k = key(el);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(k);
    if (out.length >= limit) break;
  }
  return out;
}
"""

STATE_INDEX_JS = r"""
([sel, wanted]) => {
  const key = (el) => el.tagName + "." + String(el.className)
    .split(" ")
    .filter(c => c && !/^css-[a-z0-9]+$/i.test(c) && !/^css-var-/i.test(c))
    .slice(0, 3)
    .join(".");
  const els = [...document.querySelectorAll(sel)];
  for (let i = 0; i < els.length; i++) {
    if (key(els[i]) === wanted) return i;
  }
  return -1;
}
"""
STATE_HOVER_ALPHA = 0.08
STATE_PRESS_ALPHA = 0.12
STATE_ALPHA_TOLERANCE = 0.02

STATE_SNAP_JS = r"""
() => {
  const el = window.__stateEl;
  if (!el) return null;
  // `{subtree: true}` includes the pseudo-elements' transitions — a tab's state
  // layer lives on `::before`, and finishing only the element's own animations
  // reads a half-started transition as "no feedback at all".
  el.getAnimations({subtree: true}).forEach(a => {
    const t = a.effect && a.effect.getComputedTiming();
    if (!t || t.iterations === Infinity) return;
    try { a.finish(); } catch (err) {}
  });
  const c = getComputedStyle(el);
  return {
    cls: String(el.className).slice(0, 44),
    tag: el.tagName,
    bg: c.backgroundColor,
    bd: c.borderTopColor,
    sh: c.boxShadow.slice(0, 110),
    radius: c.borderTopLeftRadius,
    filter: c.filter,
    outline: c.outline,
    outlineOffset: c.outlineOffset,
    pseudo: ["::before", "::after"].map(p => {
      const q = getComputedStyle(el, p);
      return { p, bg: q.backgroundColor, sh: q.boxShadow.slice(0, 90) };
    }),
  };
}
"""

STATE_TOKENS_JS = r"""
() => {
  const root = getComputedStyle(document.documentElement);
  const out = [];
  for (const p of root) {
    const v = root.getPropertyValue(p).trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) out.push(v.toLowerCase());
  }
  return out;
}
"""


def _colour_and_alpha(value: str) -> tuple[str | None, float]:
    """`rgb()`/`rgba()`/`color(srgb …)` → (`#hex`, alpha).

    Rounded, not truncated: `0.270588 * 255` is 68.99994, and `int()` turned a
    token's `#49454f` into `#49444f` — a colour in no table, reported as a defect
    that did not exist.
    """
    text = value or ""
    m = re.match(r"rgba?\(([^)]+)\)", text)
    if m:
        n = [float(x.strip()) for x in m.group(1).split(",")]
        return (
            f"#{round(n[0]):02x}{round(n[1]):02x}{round(n[2]):02x}",
            n[3] if len(n) > 3 else 1.0,
        )
    m = re.match(r"color\(srgb ([^)]+)\)", text)
    if m:
        n = [float(x) for x in m.group(1).replace("/", " ").split()]
        return (
            f"#{round(n[0] * 255):02x}{round(n[1] * 255):02x}{round(n[2] * 255):02x}",
            n[3] if len(n) > 3 else 1.0,
        )
    return None, 1.0


def _state_layer(snap: dict) -> tuple[str | None, float]:
    """The state layer a snapshot shows: an inset overlay, or a pseudo-element's
    translucent background — whichever the component uses.

    Commas are split at the top level only: `rgba(103, 80, 164, 0.12) 0 0 0 9999px
    inset` has four commas and three of them are inside the colour, so a plain
    `split(",")` hands the parser a fragment that matches nothing — which is how
    the first version of this function reported "no hover feedback" for every
    control whose layer is a shadow.
    """
    for part in re.split(r",(?![^()]*\))", snap.get("sh") or ""):
        if "inset" in part:
            colour, alpha = _colour_and_alpha(part)
            if colour and alpha < 1:
                return colour, alpha
    for pseudo in snap.get("pseudo", []):
        colour, alpha = _colour_and_alpha(pseudo.get("bg") or "")
        if colour and alpha < 1:
            return colour, alpha
    return None, 1.0


def state_defects(rows: list[dict]) -> list[str]:
    """What a pointer sees on hover and press, as failure lines.

    Four questions, all measurable: is there a layer at all; is its opacity the
    published 8%/12%; is its colour one the token file publishes; and did the
    control answer by *swapping* a colour (a mechanism M3 does not use) or by
    filtering itself (which turns the wrong direction in exactly one theme).

    Each row carries the token set of *its own theme*, because the two palettes
    publish different hexes and judging a dark row against the light table is how
    the focus gate first reported fifty defects that were one measurement bug.
    """
    out: list[str] = []
    for row in rows:
        where = row["label"]
        tokens = {c.lower() for c in row.get("tokens", [])}
        hover, press, rest = row["hover"], row["press"], row["rest"]
        if row.get("forced"):
            # Forced colours drop `box-shadow`, so the state layer *cannot* be the
            # feedback here: the mode's answer is an outline in system colours, and
            # that is what this pass requires. Colour and opacity are the user's in
            # this mode, so they are not judged.
            for state, snap in (("hover", hover), ("press", press)):
                if not _outline_is_visible(str(snap.get("outline") or "")):
                    out.append(
                        f"{where}: no visible {state} feedback in forced-colors "
                        "(box-shadow is dropped by the mode)"
                    )
            if hover["filter"] != rest["filter"]:
                out.append(f"{where}: hover changes `filter` in forced-colors")
            continue
        if hover["filter"] != rest["filter"]:
            out.append(
                f"{where}: hover changes `filter` ({rest['filter']} -> {hover['filter']})"
            )
        hover_colour, hover_alpha = _state_layer(hover)
        press_colour, press_alpha = _state_layer(press)
        if not hover_colour:
            out.append(f"{where}: no hover feedback")
        else:
            if abs(hover_alpha - STATE_HOVER_ALPHA) > STATE_ALPHA_TOLERANCE:
                out.append(
                    f"{where}: hover layer is {hover_alpha:.3f}, want {STATE_HOVER_ALPHA}"
                )
            if hover_colour not in tokens:
                out.append(f"{where}: hover layer colour {hover_colour} is in no token")
        if not press_colour:
            out.append(f"{where}: no press feedback")
        else:
            if abs(press_alpha - STATE_PRESS_ALPHA) > STATE_ALPHA_TOLERANCE:
                out.append(
                    f"{where}: press layer is {press_alpha:.3f}, want {STATE_PRESS_ALPHA}"
                )
            if press_colour not in tokens:
                out.append(f"{where}: press layer colour {press_colour} is in no token")
        for key in ("bg", "bd"):
            colour, alpha = _colour_and_alpha(hover[key])
            if (
                colour
                and alpha > 0.95
                and colour not in tokens
                and hover[key] != rest[key]
            ):
                out.append(f"{where}: hover swaps {key} to {colour}, which is in no token")
    return out


# ── Disabled controls ───────────────────────────────────────────────────────
# M3 publishes a disabled *content* opacity (0.38) and a disabled *container*
# opacity (0.12), and it publishes no state layer for a control that cannot be
# used. Three things are therefore checkable, and each of them has been wrong in
# some codebase's lifetime: the control does not fade itself with `opacity` (a
# blanket fade takes the focus ring and every child with it), it cannot take
# focus, and it does not light up under the pointer. The live product has two
# disabled controls on the entire build — the pager's previous button and its
# inner `<button>` — so this runs against the gallery, where every family has a
# disabled variant.
DISABLED_SELECTOR = (
    'button:disabled, input:disabled, select:disabled, textarea:disabled, '
    '[aria-disabled="true"], .ant-switch-disabled, .ant-select-disabled, '
    ".ant-btn-disabled, .ant-checkbox-disabled, .ant-radio-disabled, "
    ".ant-segmented-disabled"
)
DISABLED_LIMIT = 40
DISABLED_JS = r"""
(sel) => {
  const onSurface = getComputedStyle(document.documentElement)
    .getPropertyValue("--ah-on-surface").trim();
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (cs.display === "none" || cs.visibility === "hidden") continue;
    if (r.width < 6 || r.height < 6) continue;
    out.push({
      cls: String(el.className).slice(0, 46),
      tag: el.tagName,
      opacity: cs.opacity,
      bg: cs.backgroundColor,
      bd: cs.borderTopColor,
      bw: cs.borderTopWidth,
      colour: cs.color,
      sh: cs.boxShadow.slice(0, 90),
      focusable: el.tabIndex >= 0 && !el.disabled,
    });
    if (out.length >= 40) break;
  }
  return { onSurface, controls: out };
}
"""


# Which families publish a *whole-element* disabled opacity, and where that value
# lives in the token file. Checkbox and radio do (`disabled.opacity: 0.38`: the
# published treatment for those two is the control at 38%); switch, field,
# segmented and slider publish per-part opacities instead, so their element must
# stay at 1 and let the parts carry it. Reading the expectation from the token
# file is what makes this a comparison rather than an opinion.
# Which family each control belongs to, so its disabled expectations can be read
# from the token file instead of being asserted here. Checkbox and radio publish
# a whole-element `disabled.opacity`; switch and the fields publish per-part
# opacities; the rest fall back to the generic `state.disabled` pair.
DISABLED_FAMILIES = {
    ".ah-btn": "button",
    ".ant-btn": "button",
    ".ah-iconbtn": "iconButton",
    ".ah-mchip": "chip",
    ".ah-filterchip": "chip",
    ".ah-fab": None,  # FabTokens publishes no disabled pair
    ".ah-field": "textField",
    ".ant-input": "textField",
    ".ant-switch": "switch",
    ".ant-segmented": "segmented",
    ".ant-checkbox": "checkbox",
    ".ant-radio": "radio",
}
DISABLED_OPACITY_TOLERANCE = 0.02
# How far a disabled composite may sit from the theme's `on-surface` and still be
# the same neutral. antd's disabled container is white-on-dark and black-on-light,
# which lands within 32/255 of `on-surface` in both palettes — near-neutral by
# construction, and nowhere near a hue like primary or error.
DISABLED_NEUTRAL_DELTA = 32


def _channel_delta(a: str, b: str) -> int:
    """The largest per-channel difference between two `#rrggbb` strings."""
    if len(a) != 7 or len(b) != 7:
        return 255
    return max(abs(int(a[i : i + 2], 16) - int(b[i : i + 2], 16)) for i in (1, 3, 5))


_OUTLINE_STYLE_RE = re.compile(
    r"\b(none|hidden|solid|dashed|dotted|double|groove|ridge|inset|outset)\b"
)
_OUTLINE_WIDTH_RE = re.compile(r"(\d+(?:\.\d+)?)px")


def _outline_is_visible(text: str) -> bool:
    """Is a computed `outline` string an outline a reader can see?

    Keyword-matching, not positional: `rgb(0, 0, 0) none 3px`.split(" ")[1] is
    `"0,"`, so the first version of this check read every invisible outline as
    visible and reported "forced-colors feedback is fine" on a build where it was
    not. (Same comma trap as `_state_layer`, one function earlier.)
    """
    style = _OUTLINE_STYLE_RE.search(text or "")
    if not style or style.group(1) in ("none", "hidden"):
        return False
    width = _OUTLINE_WIDTH_RE.search(text or "")
    return bool(width) and float(width.group(1)) > 0


def load_disabled_expectations() -> dict[str, dict[str, float | None]]:
    """`class substring -> {element, content, container, outline}` from tokens.json.

    Read, not asserted: the file publishes `disabled.opacity` for checkbox and
    radio (the whole control at 38%), `disabled.content/container/outline` for the
    fields, `content-opacity`/`track-opacity` for the switch, and nothing for the
    FAB — which is why the generic `state.disabled` pair is the fallback rather
    than a constant in this tool.
    """
    tokens = json.loads((WEB / "src" / "tokens.json").read_text(encoding="utf-8"))
    component = tokens["component"]
    generic = tokens["state"]["disabled"]

    def number(value: object) -> float | None:
        return None if value is None else float(value)  # type: ignore[arg-type]

    out: dict[str, dict[str, float | None]] = {}
    for marker, family in DISABLED_FAMILIES.items():
        spec: dict[str, object] = {}
        if family:
            spec = dict(component.get(family, {}).get("disabled", {}) or {})
        out[marker] = {
            "element": number(spec.get("opacity")),
            "content": number(
                spec.get("content")
                if spec.get("content") is not None
                else spec.get("content-opacity", generic["content"])
            ),
            "container": number(
                spec.get("container")
                if spec.get("container") is not None
                else spec.get("track-opacity", generic["container"])
            ),
            "outline": number(
                spec.get("outline", spec.get("container", generic["container"]))
            ),
        }
    return out


def disabled_defects(
    rows: list[dict], expectations: dict[str, dict[str, float | None]]
) -> list[str]:
    """What a disabled control must not do, as failure lines.

    `opacity: 0` is skipped rather than judged: antd's checkbox and radio keep a
    real `<input>` at opacity 0 as the focus proxy and draw the control on a
    sibling, so the element is invisible by design and the visible sibling is
    measured on its own line.
    """
    out: list[str] = []
    for row in rows:
        where = row["label"]
        measured = float(row.get("opacity") or "1")
        if measured == 0 and row.get("tag") == "INPUT":
            continue
        expected = 1.0
        spec: dict[str, float | None] = {}
        for marker, family in expectations.items():
            if marker.lstrip(".") in row["label"] or marker in row["label"]:
                expected = family.get("element") or 1.0
                spec = family
                break
        if abs(measured - expected) > DISABLED_OPACITY_TOLERANCE:
            out.append(
                f"{where}: opacity {measured:.2f}, want {expected:.2f} — a blanket "
                "fade takes the focus ring and every child with it"
            )
        if row.get("forced"):
            # Forced colours replace the ink with system colours on purpose, so a
            # composed `on-surface` is exactly what must *not* be expected here.
            # The opacity, focus and pointer checks above still apply.
            pass
        elif spec and expected == 1.0:
            # The *composed* treatment: every translucent colour the control
            # paints has to be the theme's `on-surface` at the published opacity.
            # That is the check the light pass exists for — light's ink is dark
            # where dark's is light, so a rule can be right in one and wrong in
            # the other, and comparing only element opacity would never notice.
            on_surface = row.get("on_surface") or ""
            rest = row.get("rest") or {}
            for key, want in (
                ("color", spec.get("content")),
                ("bg", spec.get("container")),
                ("bd", spec.get("outline")),
            ):
                if want is None:
                    continue
                if key == "bd" and str(rest.get("bw") or "0px") in ("0px", "0"):
                    # No border: `border-top-color` is just `currentColor`, so
                    # judging it reports the *content* opacity as a border defect.
                    continue
                colour, alpha = _colour_and_alpha(str(rest.get(key) or ""))
                # Only a *partial* alpha is a composite. `rgba(0, 0, 0, 0)` is
                # nothing painted (its RGB channels are meaningless), and an
                # opaque colour is not compositing anything — the first version
                # called every transparent border `#000000` and reported ten
                # defects that were its own arithmetic.
                if colour is None or alpha >= 1 or alpha == 0:
                    continue
                if on_surface and _channel_delta(colour, on_surface) > DISABLED_NEUTRAL_DELTA:
                    out.append(
                        f"{where}: disabled {key} composites {colour}, which is not "
                        f"the theme's on-surface {on_surface} (or a neutral within "
                        f"{DISABLED_NEUTRAL_DELTA})"
                    )
                elif abs(alpha - float(want)) > DISABLED_OPACITY_TOLERANCE:
                    out.append(
                        f"{where}: disabled {key} is {alpha:.2f}, want {want:.2f}"
                    )
        if row.get("focusable"):
            out.append(f"{where}: is disabled and can still take focus")
        hover, press, rest = row.get("hover"), row.get("press"), row.get("rest")
        if not (hover and press and rest):
            continue
        for state, snap in (("hover", hover), ("press", press)):
            for key in ("bg", "bd", "sh"):
                if snap[key] != rest[key]:
                    out.append(
                        f"{where}: answers the pointer while disabled "
                        f"({state} changes {key})"
                    )
                    break
    return out


def run_disabled_sweep(
    page, url: str, theme: str = "dark", forced: bool = False
) -> dict:
    """Every disabled control on the gallery page, with and without a pointer.

    Per palette: the disabled look composites `on-surface`, and light's ink is
    dark where dark's is light, so a rule can be right in one and wrong in the
    other. The gallery used to be dark-only and this sweep inherited that.
    """
    page.goto(f"{url}?theme={theme}", wait_until="domcontentloaded")
    if forced:
        page.emulate_media(forced_colors="active")
    page.wait_for_timeout(1500)
    found = page.evaluate(DISABLED_JS, DISABLED_SELECTOR)
    on_surface = found.get("onSurface", "")
    controls = found.get("controls", [])
    rows: list[dict] = []
    for index, row in enumerate(controls[:DISABLED_LIMIT]):
        handle = page.locator(DISABLED_SELECTOR).nth(index)
        rest = {
            "bg": row["bg"],
            "bd": row["bd"],
            "bw": row["bw"],
            "sh": row["sh"],
            "color": row["colour"],
        }
        hover = press = None
        try:
            box = handle.bounding_box()
            if box and box["width"] >= 6 and box["height"] >= 6:
                element = handle.element_handle()
                if element is not None:
                    page.evaluate("(el) => { window.__stateEl = el; }", element)
                    page.mouse.move(5, 5)
                    page.wait_for_timeout(30)
                    # Settle before the baseline: the gallery animates its cards in,
                    # and a mid-transition `box-shadow` reads as "the pointer
                    # changed something" on a control that ignores the pointer.
                    settled = page.evaluate(STATE_SNAP_JS)
                    if settled:
                        rest = {
                            "bg": settled["bg"],
                            "bd": settled["bd"],
                            "sh": settled["sh"],
                            "color": settled["colour"],
                        }
                    page.mouse.move(
                        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    )
                    page.wait_for_timeout(120)
                    hover = page.evaluate(STATE_SNAP_JS)
                    page.mouse.down()
                    page.wait_for_timeout(120)
                    press = page.evaluate(STATE_SNAP_JS)
                    page.mouse.up()
        except Exception:  # noqa: BLE001 - a control that moves is not a finding
            pass
        finally:
            with contextlib.suppress(Exception):
                page.mouse.move(5, 5)
        rows.append(
            {
                "label": f'{"forced " if forced else ""}{theme} {row["tag"]}.{row["cls"][:30]}',
                "tag": row["tag"],
                "forced": forced,
                "on_surface": on_surface,
                "opacity": row["opacity"],
                "focusable": row["focusable"],
                "rest": rest,
                "hover": {**rest, **(hover or {})} if hover else None,
                "press": {**rest, **(press or {})} if press else None,
            }
        )
    if forced:
        page.emulate_media(forced_colors="none")
    return {"rows": rows, "examined": len(rows)}


def run_state_sweep(page, url: str, routes: list[str], forced: bool = False) -> dict:
    """Hover and press every interactive control, in both themes.

    Returns `{"rows": [...], "examined": n}` so the caller can judge the rows and
    show that the sweep was not empty.

    `forced=True` repeats the pass under `forced-colors: active`, where the
    platform drops every `box-shadow` and the feedback has to come from an
    outline instead. That pass exists because the alternative is a hand-written
    selector list nobody checks — and the first version of that list named only
    `.ah-*` classes, which most buttons in this app do not carry, so it silently
    did nothing.
    """
    rows: list[dict] = []
    tokens: set[str] = set()
    if forced:
        page.emulate_media(forced_colors="active")
    for theme in ("light", "dark"):
        page.goto(url, wait_until="domcontentloaded")
        page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["ah-theme", theme])
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("#ah-tokens", state="attached")
        page.wait_for_timeout(1200)
        tokens = {c.lower() for c in page.evaluate(STATE_TOKENS_JS)}
        for route in routes:
            page.goto(url.rstrip("/") + "/" + route, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            families = page.evaluate(
                STATE_FAMILIES_JS, [STATE_SELECTOR, STATE_LIMIT]
            )
            for family in families:
                try:
                    index = page.evaluate(
                        STATE_INDEX_JS, [STATE_SELECTOR, family]
                    )
                    if index < 0:
                        continue
                    handle = page.locator(STATE_SELECTOR).nth(index)
                    handle.scroll_into_view_if_needed(timeout=1500)
                    box = handle.bounding_box()
                    if not box or box["width"] < 6 or box["height"] < 6:
                        continue
                    element = handle.element_handle()
                    if element is None:
                        continue
                    page.evaluate("(el) => { window.__stateEl = el; }", element)
                    page.mouse.move(5, 5)
                    page.wait_for_timeout(30)
                    rest = page.evaluate(STATE_SNAP_JS)
                    page.mouse.move(
                        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    )
                    page.wait_for_timeout(120)
                    hover = page.evaluate(STATE_SNAP_JS)
                    page.mouse.down()
                    page.wait_for_timeout(120)
                    press = page.evaluate(STATE_SNAP_JS)
                    page.mouse.up()
                except Exception:  # noqa: BLE001 - a control that moves is not a finding
                    continue
                finally:
                    with contextlib.suppress(Exception):
                        page.mouse.move(5, 5)
                if not (rest and hover and press):
                    continue
                rows.append(
                    {
                        "label": f"{theme} {route} {hover['cls'][:26]}",
                        "tokens": sorted(tokens),
                        "forced": forced,
                        "rest": rest,
                        "hover": hover,
                        "press": press,
                    }
                )
    if forced:
        page.emulate_media(forced_colors="none")
    return {"rows": rows, "examined": len(rows)}


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
    style: effective.s,
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
      // `disabled` is not decoration: the pager's inner `<button>` on page 1 is
      // disabled, `focus()` on it is a no-op, and judging the nothing that
      // happens reports "focused without the focus-ring choreography" for a
      // control no keyboard can reach.
      return cs.display !== 'none' && cs.visibility !== 'hidden' && !e.disabled;
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
    if (document.activeElement !== el) continue;  // not focusable in practice
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
      style: effective.s,
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
        # A synthetic `focus()` cannot reproduce every antd state (the segmented
        # item marks itself focused only for a real key focus), so an element with
        # no box is not judged from that pass — the keyboard pass judges it. This
        # has to come *before* the forced-colours branch too: that branch was
        # written above it once and immediately reported the 0x0 segmented input
        # as "nothing around it draws the ring".
        if r.get("invisible") and r.get("pass") == "synthetic":
            continue
        if r.get("forced"):
            # `forced-colors: active` replaces every colour with a system one, so
            # the ring cannot be compared against `--ah-secondary` — the
            # requirement becomes "there is still a ring". Measured on the app:
            # it is the UA's `Highlight` at 3px and a 2px offset, because the ring
            # is an `outline` and forced colours keep outlines (they only force
            # the colour). This pass is what proves that per *element*, including
            # the ones whose ring is delegated to an ancestor.
            # The *style* has to be part of the string: `"3px rgb(...)"` has no
            # keyword for `_outline_is_visible` to find, so the first version of
            # this branch reported "no visible focus ring" for every element in
            # the mode — a check that had forgotten what an outline is made of.
            outline = f'{r.get("style", "")} {r.get("width", "")} {r.get("colour", "")}'
            where = f'{r.get("theme", "")}{r.get("route", "")} {r["cls"] or r["tag"]}'.strip()
            if not _outline_is_visible(str(outline)):
                out.append(f"{where}: no visible focus ring in forced-colors")
            if r.get("radiusBefore") not in (None, "") and r.get("radiusBefore") != r.get(
                "radiusAfter"
            ):
                out.append(
                    f"{where}: border-radius changed on focus "
                    f"({r['radiusBefore']} -> {r['radiusAfter']})"
                )
            if r.get("invisible") and not r.get("delegated"):
                out.append(
                    f"{where}: the focused node has no visible box and nothing "
                    "around it draws the ring"
                )
            continue
        theme = r.get("theme", "")
        want = _rgb(expected[theme] if isinstance(expected, dict) else expected)
        where = f'{r.get("theme", "")}{r.get("route", "")} {r["cls"] or r["tag"]}'.strip()
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


def run_eclipse_sweep(page, url: str, routes: list[str]) -> dict:
    """Read both sides of every entry, on the page state that renders it.

    Each entry names the state it needs (`when`): `page` for something a route
    draws, `dropdown`/`select`/`tooltip` for the three popups the cockpit mounts,
    and `detail` for the session view. One state per page load, because opening a
    popup covers the toolbar, `Escape` does not always close it, and the sweep
    then measures a Select that never opened 鈥?which is exactly the "nothing
    matches" defect it reported on its first run.

    An entry whose element does not appear is reported by `eclipse_defects` as
    "nothing matches" rather than skipped: the failure mode this sweep exists to
    catch is a rule that looks alive because nothing ever checked it.
    """

    rows: list[dict] = []

    def group(where: str, route: str | None = None) -> tuple[dict[str, str], ...]:
        """The entries for one state, on one route.

        An entry with a `route` is only read there; one without is read wherever
        the state it names is prepared.
        """

        return tuple(
            e
            for e in ECLIPSED
            if e["when"] == where and (route is None or e.get("route") in (None, route))
        )

    def open_route(route: str) -> None:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("#ah-tokens", state="attached")
        page.wait_for_timeout(1200)
        page.goto(url.rstrip("/") + "/" + route, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

    for route in routes:
        open_route(route)
        rows.extend(eclipse_rows(page, group("page", route)))

    # The three popups are one page state each, and each is prepared on the
    # route that owns the trigger, so a single pass covers every entry.
    base = routes[0]
    for state, prepare in (
        ("dropdown", lambda: _click(page, "header button.ah-iconbtn")),
        ("select", lambda: _click(page, ".ah-select-chip, .ant-select")),
        ("tooltip", lambda: _hover(page, "header button.ah-iconbtn")),
    ):
        wanted = group(state)
        if not wanted:
            continue
        open_route(base)
        prepare()
        page.wait_for_timeout(500)
        rows.extend(eclipse_rows(page, wanted))
    return {"rows": rows, "examined": len(rows)}


def _click(page, selector: str) -> None:
    """Click if it is there; the rows below report what did not appear."""

    element = page.query_selector(selector)
    if element is None:
        return
    # An overlay left by a previous pass can swallow the click; that is not a
    # defect here, because the rows report whatever failed to appear.
    with contextlib.suppress(Exception):
        element.click(timeout=3000)


def _hover(page, selector: str) -> None:
    element = page.query_selector(selector)
    if element is None:
        return
    with contextlib.suppress(Exception):
        element.hover(timeout=3000)


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


def run_focus_sweep(
    page, url: str, routes: list[str], forced: bool = False
) -> dict:
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
    if forced:
        # The ring is an `outline`, and forced colours keep outlines while
        # replacing their colour — so the *requirement* stays "there is a ring",
        # and this pass is what proves it element by element instead of assuming
        # it. The judgement in `focus_defects` switches on the same flag.
        page.emulate_media(forced_colors="active")
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
    if forced:
        page.emulate_media(forced_colors="none")
    # One flag for every row this call produced, rather than tagging at three
    # separate collection sites.
    for row in out["rows"]:
        row["forced"] = forced
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
    parser.add_argument(
        "--states",
        action="store_true",
        help=(
            "also hover and press every interactive control with a real pointer, "
            "in both themes, and check the state layer, its opacity and its colour"
        ),
    )
    parser.add_argument(
        "--disabled",
        action="store_true",
        help=(
            "also check the gallery's disabled variants: no self-fade, no focus, "
            "and no answer to the pointer"
        ),
    )
    parser.add_argument(
        "--eclipse",
        action="store_true",
        help=(
            "also check that the rules this bundle writes for antd's popups "
            "actually win: the computed value on the rendered element has to "
            "equal the token it names, not antd's fallback"
        ),
    )
    parser.add_argument(
        "--morph",
        action="store_true",
        help=(
            "also press (or hover) every family that publishes a pressed shape "
            "and check the corner at rest, while held and after release against "
            "the token it names - and that the move runs on the M3E spatial curve"
        ),
    )
    parser.add_argument(
        "--app-only",
        action="store_true",
        help=(
            "skip the gallery and its Vite build, and sweep only the running "
            "cockpit named with --app. For a machine with no memory or disk to "
            "spare (a Vite build is hundreds of megabytes); the report says the "
            "gallery-derived checks were not measured instead of implying they "
            "passed"
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
    if args.app_only and not args.app:
        print("--app-only needs at least one --app URL; there would be nothing to sweep")
        return 2
    preview = None
    base = ""
    log = root / "preview.log"
    if not args.app_only:
        build_gallery(root)
        run(["npx", "--no-install", "vite", "build"], cwd=root)
        # `--host 127.0.0.1` rather than Vite's default `localhost`: on Windows the
        # preview server binds `::1` only, and a probe that asks for the IPv4
        # literal then times out against a server that is running perfectly well.
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
    else:
        print("gallery skipped (--app-only): the rule-reachability sweep will not run")
    try:
        if not args.app_only:
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
        # Popups the gallery is supposed to open. If one does not appear, the
        # rules that live inside it are unverified rather than dead.
        unopened: list[str] = []
        surfaces = (
            (".ah-select-chip:not(.ant-select-disabled)", ".ant-select-dropdown", ".ant-select-item"),
            ("#g-tooltip", ".ant-tooltip-container", ".ant-tooltip-container"),
        )
        with sync_playwright() as pw:
            executable = chromium_path(pw)
            browser = pw.chromium.launch(
                headless=True,
                **({"executable_path": executable} if executable else {}),
            )
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            # Both palettes: the gallery used to run dark-only, so every value
            # this sweep read — disabled opacities, colours, radii against the
            # tokens — had one theme's evidence behind it.
            for url, scope in () if args.app_only else (
                (base, "interactive"),
                (base + "?modal=1", "modal"),
                (base + "?confirm=1", "confirm"),
                (base + "?theme=light", "interactive-light"),
                (base + "?theme=light&modal=1", "modal-light"),
            ):
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(1400)
                if scope == "interactive":
                    # Open the two surfaces that only exist while open.
                    # `:not(.ant-select-disabled)` because the gallery now mounts a
                    # disabled variant *before* the live ones, and clicking a
                    # disabled select opens nothing — which silently turned
                    # `:root .ant-select-item` into a "dead rule" the first time.
                    for trigger, marker, _ in surfaces:
                        for attempt in range(3):
                            element = page.query_selector(trigger)
                            if element is None:
                                break
                            try:
                                element.scroll_into_view_if_needed(timeout=2000)
                                element.hover(timeout=2000)
                                element.click(timeout=2000)
                            except Exception:  # noqa: BLE001 - reported below, not raised
                                pass
                            try:
                                page.wait_for_selector(marker, state="attached", timeout=4000)
                                break
                            except Exception:  # noqa: BLE001
                                if attempt == 2:
                                    break
                                page.wait_for_timeout(800)
                        page.wait_for_timeout(400)
                    for trigger, marker, rule_part in surfaces:
                        if page.query_selector(marker) is None and rule_part not in unopened:
                            unopened.append(rule_part)
                            print(
                                f"  the gallery did not open {trigger} this run: rules "
                                f"reading {rule_part} are unverified, not dead"
                            )
                rows.extend(page.evaluate(AUDIT_JS, scope))
                found = page.evaluate(SWEEP_JS)
                for bucket, entries in found.items():
                    for key, count in entries.items():
                        sweep[bucket][key] = sweep[bucket].get(key, 0) + count

            # Disabled variants live in the gallery: the whole running product
            # has two such controls, so measuring them on the gallery is the only
            # way to cover the families.
            disabled: dict = {"rows": [], "examined": 0}
            morph: dict = {"rows": []}
            dialogs: dict = {"rows": []}
            snacks: dict = {"rows": []}
            tooltips: dict = {"rows": []}
            if args.morph and not args.app_only:
                for theme in ("light", "dark"):
                    found_morph = run_morph_sweep(page, base, theme)
                    morph["rows"].extend(found_morph["rows"])
                    found_dialog = run_dialog_sweep(page, base, theme)
                    dialogs["rows"].extend(found_dialog["rows"])
                    found_snack = run_snackbar_sweep(page, base, theme)
                    snacks["rows"].extend(found_snack["rows"])
                    found_tip = run_tooltip_sweep(page, base, theme)
                    tooltips["rows"].extend(found_tip["rows"])
            if args.disabled and not args.app_only:
                for theme in ("dark", "light"):
                    found = run_disabled_sweep(page, base, theme)
                    disabled["rows"].extend(found["rows"])
                    disabled["examined"] += found["examined"]
                # Then the same variants in high-contrast mode: a disabled control
                # must not become interactive because the platform replaced the
                # palette, and the forced outline the pointer feedback uses must
                # not appear on something the reader cannot use.
                for theme in ("dark", "light"):
                    found = run_disabled_sweep(page, base, theme, forced=True)
                    disabled["rows"].extend(found["rows"])
                    disabled["examined"] += found["examined"]

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
            states: dict = {"rows": [], "examined": 0}
            eclipses: dict = {"rows": [], "examined": 0}
            for url in args.app:
                if args.eclipse:
                    found_eclipses = run_eclipse_sweep(page, url, args.route or list(LIST_ROUTES))
                    eclipses["rows"].extend(found_eclipses["rows"])
                    eclipses["examined"] += found_eclipses["examined"]
                if args.states:
                    found_states = run_state_sweep(page, url, args.route or ["#/"])
                    states["rows"].extend(found_states["rows"])
                    states["examined"] += found_states["examined"]
                    forced_states = run_state_sweep(
                        page, url, args.route or ["#/"], forced=True
                    )
                    states["rows"].extend(forced_states["rows"])
                    states["examined"] += forced_states["examined"]
                if args.overlap:
                    found_overlaps, seen = run_overlap_sweep(
                        page, url, args.route or ["#/"]
                    )
                    overlaps.extend(found_overlaps)
                    overlap_examined += seen
                if args.focus:
                    focus.update(run_focus_sweep(page, url, args.route or ["#/"]))
                    forced_focus = run_focus_sweep(
                        page, url, args.route or ["#/"], forced=True
                    )
                    focus["rows"].extend(forced_focus["rows"])
                    focus["examined"] += forced_focus["examined"]
                    focus["keyboard"] += forced_focus["keyboard"]
                    for theme, value in forced_focus["expect"].items():
                        focus["expect"].setdefault(theme, value)
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
        if preview is not None:
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
    defects, unverified, _ = reachable(rows, tuple(unopened))
    matched = sum(1 for r in rows if r["matched"] > 0)
    gallery_skipped = bool(args.app_only)
    off_weight, off_size = off_scale(sweep)
    app_weights, app_sizes = off_scale(app_sweep)
    app_colors, app_radii, app_allowed = off_token(app_sweep)
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
    state_failures = state_defects(states["rows"]) if args.states else []
    eclipse_failures = eclipse_defects(eclipses["rows"]) if args.eclipse else []
    morph_failures = morph_defects(morph["rows"]) if args.morph else []
    if args.morph:
        morph_failures = [
            *morph_failures,
            *dialog_defects(dialogs["rows"]),
            *snackbar_defects(snacks["rows"]),
            *tooltip_defects(tooltips["rows"]),
        ]
    eclipse_read = len(
        {r["label"] for r in eclipses["rows"] if r.get("computed") is not None}
    )
    if args.eclipse and eclipse_read < len(ECLIPSED):
        # Every entry has to be read at least once: a sweep that reports "the
        # token won" from three of seven entries is the false green this file
        # was written against.
        eclipse_failures.append(
            f"the eclipse sweep read {eclipse_read} of {len(ECLIPSED)} "
            "entries; the ones it never reached are not evidence"
        )
    disabled_failures = (
        disabled_defects(disabled["rows"], load_disabled_expectations())
        if args.disabled
        else []
    )
    if args.disabled and disabled["examined"] < 6:
        disabled_failures.append(
            f"the disabled sweep examined only {disabled['examined']} controls; "
            "an empty sweep is not a pass"
        )
    # The sample is per *family*, so the floor is per family too: a route in this
    # cockpit shows at least two distinct control families (a tab and a button on
    # an empty page), in two themes. An absolute floor of 20 called a legitimate
    # single-route run "empty".
    state_floor = 2 * max(1, len(args.route or ["#/"])) * 2
    if args.states and states["examined"] < state_floor:
        state_failures.append(
            f"the state sweep examined only {states['examined']} controls, "
            f"fewer than the {state_floor} a run over these routes should reach"
        )
    print(
        json.dumps(
            {
                "gallery_skipped": gallery_skipped,
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
                "app_values_allowed_by_name": app_allowed,
                "overlap_sweep": {
                    "enabled": args.overlap,
                    "controls_examined": overlap_examined,
                    "defects": overlap_failures,
                },
                "state_sweep": {
                    "enabled": args.states,
                    "controls_examined": states["examined"],
                    "defects": state_failures,
                },
                "disabled_sweep": {
                    "enabled": args.disabled,
                    "controls_examined": disabled["examined"],
                    "controls": [
                        {"cls": r["label"], "opacity": r["opacity"]}
                        for r in disabled["rows"]
                    ],
                    "defects": disabled_failures,
                },
                "eclipse_sweep": {
                    "enabled": args.eclipse,
                    "entries_examined": eclipses["examined"],
                    "entries": len(ECLIPSED),
                    "rows": [
                        {
                            "label": r["label"],
                            "selector": r["selector"],
                            "property": r["property"],
                            "token": r["raw_token"],
                            "computed": r["computed"],
                        }
                        for r in eclipses["rows"]
                    ],
                    "defects": eclipse_failures,
                },
                "morph_sweep": {
                    "enabled": args.morph,
                    "rows_examined": len(morph["rows"]),
                    "families": len(MORPH),
                    "defects": morph_failures,
                    "measured": [
                        {
                            "label": r["label"],
                            "theme": r["theme"],
                            "rest": r.get("rest"),
                            "moved": r.get("moved"),
                            "after": r.get("after"),
                            "rest_token": r.get("rest_token"),
                            "moved_token": r.get("moved_token"),
                        }
                        for r in morph["rows"]
                        if not r.get("missing")
                    ],
                    "dialogs": [
                        {
                            "theme": r["theme"],
                            "enter": (r.get("enter") or {}).get("name"),
                            "enter_duration": (r.get("enter") or {}).get("duration"),
                            "exit": (r.get("exit") or {}).get("name"),
                            "exit_duration": (r.get("exit") or {}).get("duration"),
                        }
                        for r in dialogs["rows"]
                    ],
                    "snackbars": [
                        {
                            "theme": r["theme"],
                            "appear_duration": (r.get("appear") or {}).get("duration"),
                            "appear_curve": (r.get("appear") or {}).get("timing"),
                            "leave_duration": (r.get("leave") or {}).get("duration"),
                            "leave_curve": (r.get("leave") or {}).get("timing"),
                        }
                        for r in snacks["rows"]
                    ],
                    "tooltips": [
                        {
                            "theme": r["theme"],
                            "appear": (r.get("appear") or {}).get("name"),
                            "appear_duration": (r.get("appear") or {}).get("duration"),
                            "appear_curve": (r.get("appear") or {}).get("timing"),
                            "leave": (r.get("leave") or {}).get("name"),
                            "leave_duration": (r.get("leave") or {}).get("duration"),
                            "leave_curve": (r.get("leave") or {}).get("timing"),
                        }
                        for r in tooltips["rows"]
                    ],
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
        "eclipsed rules": eclipse_failures,
        "press morph": morph_failures,
        "overlapping controls": overlap_failures,
        "hover and press": state_failures,
        "disabled controls": disabled_failures,
    }
    if any(failures.values()):
        for label, items in failures.items():
            for item in items:
                print(f"  {label}: {item}")
        print(f"\n{len(defects)} rule(s) read component tokens and reach nothing.")
        return 1
    if gallery_skipped:
        # Not a pass and not a defect: the gallery was never built, so the
        # reachability question was not asked. Saying "no dead rules" here would
        # be the exact false green this file exists to refuse.
        print(
            "\ngallery skipped (--app-only): rule reachability and the disabled "
            "sweep were NOT measured this run; the app sweeps below were."
        )
    else:
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
    if args.states:
        print(
            f"States: {states['examined']} controls hovered and pressed with a real "
            "pointer; every one shows a token-coloured layer at 8%/12%."
        )
    if args.disabled:
        print(
            f"Disabled: {disabled['examined']} gallery variants checked; none fades "
            "itself, none takes focus, none answers the pointer."
        )
    if args.eclipse:
        print(
            f"Eclipse: {eclipses['examined']} popup properties read on rendered "
            f"elements against {len(ECLIPSED)} entries; every one computes the value "
            "its token names, so no antd rule of equal shape is painting instead."
        )
    if args.morph:
        measured = [r for r in morph["rows"] if not r.get("missing")]
        print(
            f"Morph: {len(measured)} readings across {len(MORPH)} families and "
            f"{len({r['theme'] for r in morph['rows']})} themes; every corner at "
            "rest, while held and after release equals the shape token it names, "
            "and every move runs on the M3E spatial curve. Dialog enter and exit "
            f"were read while running in {len(dialogs['rows'])} theme(s), and so "
            f"were the snackbar's appear and leave transitions "
            f"({len(snacks['rows'])} theme(s)) and the tooltip's two animations "
            f"({len(tooltips['rows'])} theme(s))."
        )
    if app_allowed:
        print(
            f"Allowed: {len(app_allowed)} computed value(s) that are in no token "
            "either because they are a token at reduced alpha (a state layer), or "
            "because a name in OFF_TOKEN_ALLOWED says why 鈥?each is printed above "
            "with its reason."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
