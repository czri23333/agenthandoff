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
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"


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
  Alert, App as AntApp, Badge, Button, Card, Checkbox, ConfigProvider, Divider,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="leave the gallery on disk")
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
    print(
        json.dumps(
            {
                "rules_reading_component_tokens": len(rows),
                "matched": matched,
                "defects": defects,
                "unverified": unverified,
            },
            indent=2,
        )
    )
    if defects:
        print(f"\n{len(defects)} rule(s) read component tokens and reach nothing.")
        return 1
    print(f"\nno dead rules. {matched}/{len(rows)} reach an element; "
          f"{len(unverified)} are unverified (see the reasons above).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
