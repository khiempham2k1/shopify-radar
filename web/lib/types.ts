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
  /** From Shopify itself (platform source or a Shopify domain); listed first. */
  official: boolean;
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
  /** Impact area chosen by Claude (impact_areas.txt); group "none" = not about themes. */
  area: { id: string; label: string; group: string } | null;
  /** Claude's one-line reason for the area. */
  reason: string;
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
  /** Written by Claude every few hours: what stood out, what to read. Null until the first one. */
  brief: {
    created_at: string | null;
    window_days: number | null;
    headline: string;
    summary: string;
    highlights: { text: string; items: { id: number; title: string; url: string; source: string; official: boolean }[] }[];
    must_read: (Item & { why: string })[];
    discussions: (CommunityRef & { why: string })[];
  } | null;
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

export interface CommunityRef {
  id: number;
  url: string;
  title: string;
  text: string;
  summary: string;
  author: string;
  place: string;
  when: string | null;
  reactions: number;
  comments: number;
  is_reply: boolean;
  /** A Discord message (otherwise a Shopify Community thread). */
  is_message?: boolean;
  /** Came in after the digest shown: summed up in the next one. */
  pending?: boolean;
  reply_author?: string;
  reply_text?: string;
  /** Discord attachments. Their links are signed by Discord and stop working after about a day. */
  attachments?: { name: string; url: string; type: string; width: number | null; height: number | null }[];
  /** Link previews. */
  embeds?: { title: string; description: string; url: string; site: string; image: string }[];
  /** What Claude saw in the attached images, in Vietnamese. */
  image_note?: string;
  /** Discord: direct replies, the whole reply chain under it, engagement = 2 × chain + reactions. */
  replies?: number;
  thread?: number;
  engagement?: number;
  /** sort=hot: the replies of this conversation shown here, oldest first. */
  thread_replies?: CommunityRef[];
}

export interface CommunityTopic {
  title: string;
  summary: string;
  kind: "question" | "problem" | "tip" | "news" | "discussion";
  sources: string[];
  item_ids: number[];
  items: CommunityRef[];
  /** Messages about this topic (with their replies) and people taking part, counted by radar; older digests lack them. */
  mentions?: number;
  people?: number;
}

export interface CommunityPage {
  digest: {
    id: number;
    created_at: string | null;
    items_considered: number;
    window_start?: string;
    window_end?: string;
    places?: { name: string; count: number }[];
    /** Messages that did not fit in this digest and wait for the next one. */
    left_for_next?: number;
    overview: string;
    topics: CommunityTopic[];
    open_questions: { text: string; item_ids: number[]; items: CommunityRef[] }[];
  } | null;
  digests: { id: number; created_at: string | null; items_considered: number }[];
  hours: number;
  pending: number;
  sort: "hot" | "new";
  threads: CommunityRef[];
  channels: { name: string; count: number; messages: CommunityRef[] }[];
  sources: { id: string; name: string; enabled: boolean }[];
}
