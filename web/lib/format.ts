import type { Audience, Impact, ItemStatus, Sentiment, SourceKind } from "./types";

export const TZ = "Asia/Ho_Chi_Minh";

export const IMPACT: Record<Impact, string> = { high: "Cao", med: "Trung bình", low: "Thấp" };
export const AUDIENCE: Record<Audience, { label: string; hint: string }> = {
  theme: { label: "Theme", hint: "Code theme phải sửa hoặc có thể dùng" },
  partner: { label: "Partner", hint: "Công ty với tư cách Partner bán theme: duyệt, chính sách, listing, doanh thu" },
  merchant: { label: "Merchant", hint: "Merchant dùng theme: editor, tính năng, nhu cầu" },
};
export const STATUS: Record<Exclude<ItemStatus, "dismissed">, string> = { new: "Chưa xem", doing: "Đang xử lý", done: "Xong" };
export const SENTIMENT: Record<Sentiment, string> = { neg: "Tiêu cực", neu: "Trung tính", pos: "Tích cực" };
export const KIND: Record<SourceKind, string> = { platform: "Nền tảng", social: "Social", web: "Web search" };
export const TASK: Record<string, string> = {
  classify: "Phân loại",
  summarize: "Tóm tắt video",
  report: "Báo cáo tuần",
  tags: "Tạo tag",
  community: "Thảo luận cộng đồng",
  brief: "Tóm tắt tổng quan",
};

const numberFmt = new Intl.NumberFormat("vi-VN");
export const fmtNumber = (n: number | null | undefined) => (n == null ? "–" : numberFmt.format(n));

export function fmtUsd(n: number | null | undefined, digits = 2): string {
  if (n == null) return "–";
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function parts(iso: string, opts: Intl.DateTimeFormatOptions): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hourCycle: "h23", ...opts }).formatToParts(new Date(iso))) {
    out[p.type] = p.value;
  }
  return out;
}

/** 14/10/2026 09:00 in Vietnam time. */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const p = parts(iso, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}`;
}

/** 14/10 09:00 in Vietnam time. */
export function fmtShortDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const p = parts(iso, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  return `${p.day}/${p.month} ${p.hour}:${p.minute}`;
}

/** 14/10 (timestamp in Vietnam time). */
export function fmtDayMonth(iso: string | null | undefined): string {
  if (!iso) return "–";
  const p = parts(iso, { day: "2-digit", month: "2-digit" });
  return `${p.day}/${p.month}`;
}

/** A calendar date "2026-12-01" → "01/12/2026" (no time zone shift). */
export function fmtDate(date: string | null | undefined, withYear = true): string {
  if (!date) return "–";
  const [y, m, d] = date.slice(0, 10).split("-");
  return withYear ? `${d}/${m}/${y}` : `${d}/${m}`;
}

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "vừa xong";
  if (minutes < 60) return `${minutes} phút trước`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} giờ trước`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} ngày trước`;
  const months = Math.floor(days / 30);
  return months < 12 ? `${months} tháng trước` : `${Math.floor(days / 365)} năm trước`;
}

/** 130 → "02:10", 3725 → "1:02:05". */
export function fmtClock(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

const METRIC_LABEL: Record<string, string> = {
  upvotes: "upvote",
  points: "điểm",
  likes: "lượt thích",
  retweets: "retweet",
  comments: "bình luận",
  views: "lượt xem",
};

export function fmtMetrics(metrics: Record<string, number> | null | undefined): string {
  if (!metrics) return "";
  return Object.keys(METRIC_LABEL)
    .filter((k) => typeof metrics[k] === "number" && metrics[k] > 0)
    .map((k) => `${fmtNumber(metrics[k])} ${METRIC_LABEL[k]}`)
    .join(" · ");
}

/** Signed percent change, or null when there is no baseline. */
export function pctChange(now: number, prev: number): number | null {
  if (!prev) return null;
  return Math.round(((now - prev) / prev) * 100);
}

export function signed(n: number, suffix = ""): string {
  if (n > 0) return `+${n}${suffix}`;
  if (n < 0) return `−${Math.abs(n)}${suffix}`;
  return `±0${suffix}`;
}

// "7 */2 * * *" → "chạy mỗi 2 giờ". Falls back to the raw expression.
export function describeCron(expr: string | null | undefined): string {
  if (!expr) return "";
  const f = expr.trim().split(/\s+/);
  if (f.length !== 5) return `lịch ${expr}`;
  const [min, hour, dom, mon, dow] = f;
  const rest = dom === "*" && mon === "*" && dow === "*";
  if (rest && /^\d+$/.test(min)) {
    if (hour === "*") return "chạy mỗi giờ";
    const every = hour.match(/^\*\/(\d+)$/);
    if (every) return `chạy mỗi ${every[1]} giờ`;
    if (/^\d+$/.test(hour)) return `chạy hằng ngày lúc ${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;
  }
  return `lịch ${expr}`;
}

export function dueClass(days: number): "soon" | "mid" | "far" {
  return days <= 60 ? "soon" : days <= 120 ? "mid" : "far";
}

/** ISO-8601 week number of a "YYYY-MM-DD" date. */
export function isoWeek(date: string): number {
  const [y, m, d] = date.slice(0, 10).split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

export function videoAt(url: string, seconds: number): string {
  try {
    const u = new URL(url);
    u.searchParams.set("t", `${Math.max(0, Math.floor(seconds))}s`);
    return u.toString();
  } catch {
    return `${url}${url.includes("?") ? "&" : "?"}t=${Math.max(0, Math.floor(seconds))}s`;
  }
}

const DETAIL_LINE = /^\[(Ảnh|Tệp|Link|Nội dung ảnh): .*\]$/;

/** A Discord message as the person wrote it, without the [Ảnh: …] / [Link: …] lines describing attachments. */
export function ownText(text: string): string {
  return text
    .split("\n")
    .filter((line) => !DETAIL_LINE.test(line.trim()))
    .join("\n")
    .trim();
}
