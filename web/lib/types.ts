export type SourceKind = "platform" | "social" | "web";
export type Sentiment = "neg" | "neu" | "pos";
export type Impact = "high" | "med" | "low";
export type Audience = "theme" | "partner" | "merchant";
export type ItemStatus = "new" | "doing" | "done" | "dismissed";

export interface TranscriptPoint {
  t: number;
  text: string;
}

export interface Transcript {
  status: "pending" | "processing" | "done" | "error" | "skipped" | string;
  via: string | null;
  points: TranscriptPoint[];
  duration_s: number | null;
  error: string;
}

export interface Item {
  id: number;
  source: { id: string; name: string; kind: SourceKind; type: string };
  url: string;
  title: string;
  summary: string | null;
  content: string | null;
  author: string | null;
  media_type: string | null;
  published_at: string | null;
  first_seen: string | null;
  last_seen: string | null;
  seen_count: number;
  score: number;
  /** 0–10: interaction vs. the same source, decaying with age. The Feed sorts by it. */
  hot: number;
  metrics: Record<string, number>;
  extra: Record<string, unknown>;
  keyword_groups: string[];
  /** Priority topics (config/priorities.txt) this item mentions. */
  priority: string[];
  analyzed: boolean;
  tag: { id: number; name: string } | null;
  relevance: number | null;
  sentiment: Sentiment | null;
  impact: Impact | null;
  /** Who it affects: theme code, the company as Theme Store partner, merchants using the theme. */
  affects: Audience[];
  deadline: string | null;
  days_left: number | null;
  status: ItemStatus;
  owner: string;
  transcript: Transcript | null;
}

export interface ItemList {
  items: Item[];
  total: number;
}

export interface Overview {
  kpis: {
    new_7d: number;
    new_prev_7d: number;
    todo: number;
    todo_unassigned: number;
    deadlines_90d: number;
    nearest_deadline_days: number | null;
    negative_ratio: number | null;
    negative_ratio_prev: number | null;
  };
  daily: { date: string; platform: number; social: number; web: number }[];
  topics: { tag: string; count: number; previous: number }[];
  todo: Item[];
  priority: { topics: string[]; items: Item[] };
  last_run: string | null;
  schedule: string;
}

export interface Edition {
  edition: string;
  url: string;
  first_seen: string | null;
  total: number;
  relevant: number;
  unanalyzed: number;
  tags: { tag: string; count: number }[];
  sections: { section: string; count: number }[];
}

export interface Source {
  id: string;
  name: string;
  kind: SourceKind;
  type: string;
  enabled: boolean;
}

export interface Tag {
  id: number;
  name: string;
  description: string;
}

export interface SourceHealth {
  id: string;
  name: string;
  kind: SourceKind;
  type: string;
  enabled: boolean;
  configured_backends: string[];
  status: "ok" | "warn" | "error" | "never" | "off" | string;
  backend: string;
  message: string;
  last_run: string | null;
  duration_ms: number;
  items_last_run: number;
  new_24h: number;
}

export interface LoginCheck {
  name: string;
  status: "ok" | "warn" | "error" | string;
  message: string;
}

export interface HealthResponse {
  sources: SourceHealth[];
  /** Cookie/login checks of the collector tools (rdt-cli, twitter-cli…). Older APIs omit it. */
  logins?: { checked_at: string | null; checks: LoginCheck[] } | null;
  /** Admin only: the Groq key pool (keys shown by their last 4 characters). */
  groq_keys?: { name: string; status: "ok" | "resting"; until: string | null; reason: string }[];
  videos: {
    subtitle_24h: number;
    groq_24h: number;
    audio_minutes_24h: number;
    failed_24h: number;
    processing: number;
    skipped_24h: number;
  };
}

export interface ReportSummary {
  id: number;
  kind: string;
  period_start: string;
  period_end: string;
  created_at: string | null;
  items_considered: number;
  model: string;
}

export interface ReportPoint {
  text: string;
  item_ids?: number[];
}

export interface ReportDetail extends ReportSummary {
  content: {
    summary?: string;
    risks?: ReportPoint[];
    opportunities?: ReportPoint[];
    actions?: { text: string; owner?: string }[];
    tag_counts?: { tag: string; count: number; previous: number }[];
  };
  items: Record<string, { id: number; title: string; url: string }>;
}

export interface SettingFile {
  name: string;
  value: string;
  origin: "db" | "file";
  updated_by: string;
  updated_at: string | null;
}

export interface Usage {
  days: number;
  total_cost: number;
  by_task: {
    task: string;
    calls: number;
    cost: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
  }[];
  by_model: { model: string; cost: number }[];
  daily: { date: string; cost: number }[];
  groq: { videos: number; audio_minutes: number };
}
