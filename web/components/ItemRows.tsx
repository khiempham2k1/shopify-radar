"use client";

import { useState } from "react";
import { api, errorText } from "@/lib/api";
import { AUDIENCE, dueClass, fmtClock, fmtDate, fmtDateTime, fmtDayMonth, fmtMetrics, IMPACT, SENTIMENT, STATUS, timeAgo, videoAt } from "@/lib/format";
import type { Item, ItemStatus } from "@/lib/types";
import { notifyChanged, useToast, useUser } from "./Providers";

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

function shortTitle(title: string) {
  return title.length > 52 ? title.slice(0, 50) + "…" : title;
}

/** PATCH /items/{id}; reports errors with a toast and returns the updated item or null. */
function usePatchItem() {
  const toast = useToast();
  return async (item: Item, body: { status?: ItemStatus; owner?: string }): Promise<Item | null> => {
    try {
      const updated = await api<Item>(`items/${item.id}`, "PATCH", body);
      notifyChanged();
      return updated;
    } catch (err) {
      toast(`Không lưu được: ${errorText(err)}`, { tone: "error" });
      return null;
    }
  };
}

export function PriorityTags({ item }: { item: Item }) {
  return (
    <>
      {item.priority.map((p) => (
        <span key={p} className="tag prio" title="Chủ đề ưu tiên (priorities.txt)">
          ★ {p}
        </span>
      ))}
    </>
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

export function PlatformRow({ item, compact = false, onChange }: { item: Item; compact?: boolean; onChange?: (updated: Item) => void }) {
  const toast = useToast();
  const { email } = useUser();
  const patch = usePatchItem();
  const [busy, setBusy] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<ItemStatus | null>(null);

  async function changeStatus(status: ItemStatus) {
    setBusy(true);
    setPendingStatus(status);
    const updated = await patch(item, { status });
    setPendingStatus(null);
    setBusy(false);
    if (updated) {
      onChange?.(updated);
      toast(`Trạng thái: ${STATUS[status as keyof typeof STATUS] ?? status}`);
    }
  }

  async function claim() {
    setBusy(true);
    const updated = await patch(item, item.status === "new" ? { owner: email, status: "doing" } : { owner: email });
    setBusy(false);
    if (updated) {
      onChange?.(updated);
      toast(`Đã nhận việc: ${shortTitle(item.title)}`);
    }
  }

  const status = pendingStatus ?? item.status;
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
      </div>
      <div className="side">
        {item.impact ? (
          <span className={`pill ${item.impact}`}>Ảnh hưởng {IMPACT[item.impact].toLowerCase()}</span>
        ) : (
          <span className="pill low">{item.analyzed ? "Chưa rõ ảnh hưởng" : "Chưa phân tích"}</span>
        )}
        <Due deadline={item.deadline} days={item.days_left} />
        <select
          className="status"
          aria-label={`Trạng thái: ${item.title}`}
          value={status === "dismissed" ? "new" : status}
          disabled={busy}
          onChange={(e) => changeStatus(e.target.value as ItemStatus)}
        >
          {Object.entries(STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <span className="owner">
          {item.owner ? (
            <>Phụ trách: {item.owner === email ? "bạn" : item.owner}</>
          ) : (
            <button type="button" className="btn" disabled={busy} onClick={claim}>
              Nhận việc
            </button>
          )}
        </span>
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
        <div className="tx-label">Tóm tắt từ nội dung video · {tx.via === "subtitle" ? "phụ đề" : "Groq Whisper"}</div>
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

export function FeedRow({ item, compact = false, onDismiss }: { item: Item; compact?: boolean; onDismiss?: (item: Item) => void }) {
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
      </div>
      <div className="side">
        <TranscriptBadge item={item} />
        <span className="score" title="Điểm tổng hợp">
          {item.score.toFixed(1)}
        </span>
        {item.sentiment && <span className={`sent ${item.sentiment}`}>{SENTIMENT[item.sentiment]}</span>}
        {!compact && onDismiss && (
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
