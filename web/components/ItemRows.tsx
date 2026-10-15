"use client";

import { AUDIENCE, dueClass, fmtClock, fmtDate, fmtDateTime, fmtDayMonth, fmtMetrics, IMPACT, SENTIMENT, timeAgo, videoAt } from "@/lib/format";
import type { Item } from "@/lib/types";
import { useUser } from "./Providers";

function External({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export function Due({ deadline, days }: { deadline: string | null; days: number | null }) {
  if (!deadline || days == null) return null;
  const text = days < 0 ? `quá hạn ${-days} ngày` : days === 0 ? "hạn hôm nay" : `còn ${days} ngày`;
  return (
    <span className={`due ${dueClass(days)}`} title={`Hạn chót ${fmtDate(deadline)}`}>
      {text} · {fmtDate(deadline)}
    </span>
  );
}

export function PriorityTags({ item }: { item: Item }) {
  return (
    <>
      {item.priority.map((p) => (
        <span key={p} className="tag prio" title="Chủ đề ưu tiên">
          ★ {p}
        </span>
      ))}
    </>
  );
}

interface AlsoEntry {
  source_name?: string;
  url?: string;
  author?: string;
  posted_by?: string[];
}

function handles(list: unknown): string[] {
  return Array.isArray(list) ? list.filter((h): h is string => typeof h === "string" && h !== "") : [];
}

/** Accounts that posted it, and the other places the same post was found (merged, not listed twice). */
function Reposts({ item }: { item: Item }) {
  const postedBy = handles(item.extra?.posted_by);
  const also = (Array.isArray(item.extra?.also) ? (item.extra.also as AlsoEntry[]) : []).filter((a) => a && typeof a.url === "string");
  if (postedBy.length < 2 && also.length === 0) return null;
  return (
    <div className="also">
      {postedBy.length >= 2 && <span>Đăng bởi {postedBy.map((h) => "@" + h).join(" · ")}</span>}
      {also.length > 0 && (
        <span>
          Cũng có trên:{" "}
          {also.map((a, i) => {
            const by = handles(a.posted_by);
            const label = `${a.source_name ?? "nguồn khác"}${by.length ? ` (${by.map((h) => "@" + h).join(", ")})` : a.author ? ` (${a.author})` : ""}`;
            return (
              <span key={a.url}>
                {i > 0 && " · "}
                <External href={a.url as string}>{label}</External>
              </span>
            );
          })}
        </span>
      )}
    </div>
  );
}

function Affects({ item }: { item: Item }) {
  if (item.affects.length === 0) return null;
  return (
    <span className="tag aud" title={`Ảnh hưởng tới: ${item.affects.map((a) => AUDIENCE[a].hint).join("; ")}`}>
      Ảnh hưởng: {item.affects.map((a) => AUDIENCE[a].label).join(" · ")}
    </span>
  );
}

export function PlatformRow({ item, compact = false }: { item: Item; compact?: boolean }) {
  const date = item.published_at || item.first_seen;
  return (
    <div className="row">
      <div className={`stripe sev-${item.impact ?? "low"}`} />
      <div style={{ minWidth: 0 }}>
        <div className="t">
          <External href={item.url}>{item.title}</External>
        </div>
        <div className="m">
          <PriorityTags item={item} />
          <span className="src">{item.source.name}</span>
          {date && <span title={fmtDateTime(date)}>{fmtDayMonth(date)}</span>}
          <Affects item={item} />
          {item.tag && <span className="tag">{item.tag.name}</span>}
          {typeof item.extra?.section === "string" && <span className="tag">{item.extra.section}</span>}
        </div>
        {!compact && item.summary && <div className="ai">{item.summary}</div>}
        {!compact && <Reposts item={item} />}
      </div>
      <div className="side">
        {item.impact ? (
          <span className={`pill ${item.impact}`}>Ảnh hưởng {IMPACT[item.impact].toLowerCase()}</span>
        ) : (
          <span className="pill low">{!item.analyzed ? "Chưa phân tích" : item.relevance == null || item.relevance < 0.5 ? "AI: không liên quan theme" : "Chưa rõ ảnh hưởng"}</span>
        )}
        <Due deadline={item.deadline} days={item.days_left} />
      </div>
    </div>
  );
}

function isVideo(item: Item) {
  return item.source.type === "youtube" || item.media_type === "video";
}

function TranscriptBadge({ item }: { item: Item }) {
  const tx = item.transcript;
  if (!tx || !isVideo(item)) return null;
  if (tx.status === "done") return <span className="tx">Đã nghe nội dung</span>;
  if (tx.status === "processing" || tx.status === "pending") return <span className="tx pending">Đang nghe nội dung…</span>;
  if (tx.status === "error")
    return (
      <span className="tx err" title={tx.error || undefined}>
        Chưa nghe được video
      </span>
    );
  return null;
}

function Body({ item }: { item: Item }) {
  const tx = item.transcript;
  if (isVideo(item) && tx?.status === "done") {
    return (
      <>
        <div className="tx-label">Tóm tắt từ nội dung video · {tx.via === "subtitle" ? "phụ đề" : "audio"}</div>
        {item.summary && (
          <div className="ai" style={{ marginTop: 2 }}>
            {item.summary}
          </div>
        )}
        {tx.points.length > 0 && (
          <ul className="points">
            {tx.points.map((p, i) => (
              <li key={i}>
                <a className="ts" href={videoAt(item.url, p.t)} target="_blank" rel="noopener noreferrer" aria-label={`Mở video tại ${fmtClock(p.t)}`}>
                  {fmtClock(p.t)}
                </a>
                <span>{p.text}</span>
              </li>
            ))}
          </ul>
        )}
      </>
    );
  }
  return item.summary ? <div className="ai">{item.summary}</div> : null;
}

export function sevClass(score: number) {
  return score >= 7.8 ? "sev-high" : score >= 6.5 ? "sev-med" : "sev-low";
}

export function FeedRow({
  item,
  compact = false,
  onDismiss,
  showHot = false,
}: {
  item: Item;
  compact?: boolean;
  onDismiss?: (item: Item) => void;
  /** Show the hot score (Feed sorted by hotness) instead of the overall score. */
  showHot?: boolean;
}) {
  const { email } = useUser();
  const date = item.published_at || item.first_seen;
  const duration = (typeof item.extra?.duration === "number" ? item.extra.duration : null) ?? item.transcript?.duration_s ?? null;
  const metrics = fmtMetrics(item.metrics);
  return (
    <div className="row">
      <div className={`stripe ${sevClass(item.score)}`} />
      <div style={{ minWidth: 0 }}>
        <div className="t">
          <External href={item.url}>{item.title}</External>
        </div>
        <div className="m">
          {item.official && (
            <span className="tag official" title="Nguồn chính thức của Shopify">
              ✓ Chính thức
            </span>
          )}
          <PriorityTags item={item} />
          <span className="src">{item.source.name}</span>
          {date && <span title={fmtDateTime(date)}>{timeAgo(date)}</span>}
          {isVideo(item) && duration ? <span className="mono">{fmtClock(duration)}</span> : null}
          {metrics && <span>{metrics}</span>}
          <Affects item={item} />
          {item.tag && <span className="tag">{item.tag.name}</span>}
          {item.keyword_groups.map((k) => (
            <span key={k} className="tag kw" title="Nhóm từ khóa khớp">
              {k}
            </span>
          ))}
        </div>
        {!compact && <Body item={item} />}
        {!compact && <Reposts item={item} />}
      </div>
      <div className="side">
        <TranscriptBadge item={item} />
        {showHot ? (
          <span className="score" title="Độ hot: tương tác so với các bài cùng nguồn, giảm dần theo thời gian">
            🔥 {item.hot.toFixed(1)}
          </span>
        ) : (
          <span className="score" title="Điểm tổng hợp">
            {item.score.toFixed(1)}
          </span>
        )}
        {item.sentiment && <span className={`sent ${item.sentiment}`}>{SENTIMENT[item.sentiment]}</span>}
        {!compact && onDismiss && email && (
          <button type="button" className="btn" onClick={() => onDismiss(item)}>
            Không liên quan
          </button>
        )}
      </div>
    </div>
  );
}

export function AffectsSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select className="field" value={value} onChange={(e) => onChange(e.target.value)} aria-label="Ảnh hưởng tới">
      <option value="">Ảnh hưởng tới mọi bên</option>
      {Object.entries(AUDIENCE).map(([k, v]) => (
        <option key={k} value={k} title={v.hint}>
          Ảnh hưởng tới {v.label}
        </option>
      ))}
    </select>
  );
}
