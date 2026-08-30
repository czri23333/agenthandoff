// Typed client for the cockpit REST contract (server/app.py is the source of truth).

export interface SessionMeta {
  cli: string;
  session_id: string;
  title: string;
  cwd: string;
  started_at: string | null;
  updated_at: string | null;
  model: string | null;
  provider: string | null;
  origin: string | null;
  parent_session_id: string | null;
  status: string | null; // proven end-state, null = unknown
  domain: string; // config-driven project grouping (ADR-009)
}

export interface UsageModel {
  model: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  reasoning: number | null;
  cache_write: number | null;
  cache_read: number | null;
  avg_ttft_ms: number | null;
  tok_per_s: number | null;
  avg_duration_ms: number | null;
}

export interface UsageData {
  models: UsageModel[];
  totals: { calls: number; tokens_in: number; tokens_out: number };
}

export interface TranscriptMessage {
  role: string;
  text: string;
  at: string | null;
}

export interface StoreInfo {
  cli: string;
  kind: string;
  path: string;
  readable: boolean;
  via_wsl: boolean;
  detail: string;
}

export interface Interruption {
  kind: string;
  detail: string;
  pending_user_text: string;
}

export interface BundleData {
  bundle_version: string;
  meta: Record<string, unknown> & SessionMeta;
  objective: string;
  interruption: Interruption;
  state: { done: string[]; in_progress: string[]; blocked: string[] };
  directives: string[];
  files_touched: { path: string; hits: number }[];
  next_steps: string[];
  context_notes: string[];
  tool_summary: { tool: string; calls: number }[];
  topics: { opener: string; messages: number }[];
}

export interface SessionDetail {
  bundle: BundleData;
  markdown: string;
  brief: string;
  interruption: Interruption;
  topics: { opener: string; messages: number }[];
  usage: UsageData | null;
  messages: TranscriptMessage[];
}

export interface ThreadGroup {
  lines: string[];
  session_ids: string[];
  clis: string[];
  last_active: string | null;
}

export interface InboxItem {
  path: string;
  title: string;
  cli: string;
  session_id: string;
  published_at: string;
  claimed: boolean;
  claimed_by: string;
}

export interface Launcher {
  cli: string;
  kind: "verified" | "unverified";
  command: string;
  headless?: string;
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

export const api = {
  stores: () => get<StoreInfo[]>("/api/stores"),
  sessions: (filters: { cli?: string; cwd?: string; q?: string } = {}) => {
    const p = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]);
    return get<SessionMeta[]>(`/api/sessions?${p}`);
  },
  detail: (cli: string, sid: string, lang = "en", maxChars = 12000) =>
    get<SessionDetail>(
      `/api/sessions/${encodeURIComponent(cli)}/${encodeURIComponent(sid)}/detail?lang=${lang}&max_chars=${maxChars}`,
    ),
  threads: (cwd?: string) => get<ThreadGroup[]>(`/api/threads${cwd ? `?cwd=${encodeURIComponent(cwd)}` : ""}`),
  inbox: (globalScope = false) => get<InboxItem[]>(`/api/inbox?global_scope=${globalScope}`),
  launcher: (cli: string, sid: string) =>
    get<Launcher>(`/api/launcher/${encodeURIComponent(cli)}/${encodeURIComponent(sid)}`).catch(() => null),
  publish: (cli: string, sid: string, note?: string, globalScope = false) =>
    post<{ published: string }>("/api/publish", { cli, session_id: sid, note, global_scope: globalScope }),
  claim: (path: string, by?: string) => post<{ claimed: string }>("/api/claim", { path, by }),
};

export function relTime(iso: string | null): string {
  if (!iso) return "?";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso.slice(0, 10);
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}
