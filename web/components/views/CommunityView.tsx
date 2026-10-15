"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";
import { fmtDateTime, fmtNumber, timeAgo } from "@/lib/format";
import type { CommunityPage, CommunityRef, CommunityTopic } from "@/lib/types";
import { Empty, ErrorBox, Loading } from "../States";

const TOPIC_KIND: Record<CommunityTopic["kind"], string> = {
  question: "Hỏi đáp",
  problem: "Báo lỗi",
  tip: "Mẹo, cách làm",
  news: "Tin tức",
  discussion: "Bàn luận",
};

function Refs({ items }: { items: CommunityRef[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="c-refs">
      {items.map((r) => (
        <li key={r.id}>
          <a href={r.url} target="_blank" rel="noopener noreferrer">
            {r.place}
          </a>{" "}
          <span className="muted">
            · {r.author || "ẩn danh"} · {r.when ? timeAgo(r.when) : ""}
          </span>
          <div className="c-quote">“{r.summary || r.text || r.title}”</div>
        </li>
      ))}
    </ul>
  );
}

function Digest({ data, onPick }: { data: CommunityPage; onPick: (id: number | null) => void }) {
  const d = data.digest;
  if (!d) {
    return (
      <div className="panel">
        <h2>Tóm tắt 24 giờ qua</h2>
        <Empty>Chưa có bản tóm tắt. Bản đầu tiên được tạo ở lần chạy tới khi có tin từ Discord hoặc Shopify Community.</Empty>
      </div>
    );
  }
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Tóm tắt {data.hours} giờ qua</h2>
        {data.digests.length > 1 && (
          <select className="field" value={d.id} onChange={(e) => onPick(Number(e.target.value))} aria-label="Xem bản tóm tắt">
            {data.digests.map((x, i) => (
              <option key={x.id} value={x.id}>
                {i === 0 ? "Mới nhất · " : ""}
                {x.created_at ? fmtDateTime(x.created_at) : `#${x.id}`} · {fmtNumber(x.items_considered)} tin
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="sub">
        {d.window_start && d.window_end ? `${fmtDateTime(d.window_start)} – ${fmtDateTime(d.window_end)} · ` : ""}
        AI tóm tắt từ {fmtNumber(d.items_considered)} tin
        {d.places?.length ? ` (${d.places.map((p) => `${p.name}: ${fmtNumber(p.count)}`).join(", ")})` : ""}
      </p>
      <p className="c-overview">{d.overview}</p>

      {d.topics.length > 0 && (
        <div className="c-topics">
          {d.topics.map((t, i) => (
            <details key={i} className="c-topic" open={i < 3}>
              <summary>
                <span className="c-kind">{TOPIC_KIND[t.kind] ?? t.kind}</span>
                <b>{t.title}</b>
                <span className="muted"> · {t.sources.join(", ")}</span>
              </summary>
              <p>{t.summary}</p>
              <Refs items={t.items} />
            </details>
          ))}
        </div>
      )}

      {d.open_questions.length > 0 && (
        <>
          <h3 className="sub-head">Câu hỏi chưa ai trả lời</h3>
          <ul className="c-questions">
            {d.open_questions.map((q, i) => (
              <li key={i}>
                {q.text}
                {q.items.map((r) => (
                  <a key={r.id} href={r.url} target="_blank" rel="noopener noreferrer" className="c-link">
                    ↗ {r.place}
                  </a>
                ))}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Threads({ threads }: { threads: CommunityRef[] }) {
  return (
    <div className="panel">
      <h2>Shopify Community</h2>
      <p className="sub">Chủ đề mới, tóm tắt bằng tiếng Việt</p>
      {threads.length === 0 ? (
        <Empty>Chưa có chủ đề mới.</Empty>
      ) : (
        <div className="list">
          {threads.map((t) => (
            <div className="row" key={t.id}>
              <div className="stripe sev-low" />
              <div style={{ minWidth: 0 }}>
                <div className="t">
                  <a href={t.url} target="_blank" rel="noopener noreferrer">
                    {t.title}
                  </a>
                </div>
                <div className="m">
                  <span className="src">{t.place}</span>
                  {t.author && <span>{t.author}</span>}
                  {t.when && <span title={fmtDateTime(t.when)}>{timeAgo(t.when)}</span>}
                  {t.comments > 0 && <span>{fmtNumber(t.comments)} trả lời</span>}
                </div>
                <div className="ai">{t.summary || <span className="muted">Đang chờ tóm tắt…</span>}</div>
              </div>
              <div />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Channels({ channels }: { channels: CommunityPage["channels"] }) {
  return (
    <div className="panel">
      <h2>Discord</h2>
      <p className="sub">Tin nhắn gần đây theo kênh (nguyên văn); phần tóm tắt nằm ở trên</p>
      {channels.length === 0 ? (
        <Empty>Chưa có tin nhắn Discord nào.</Empty>
      ) : (
        channels.map((c) => (
          <details key={c.name} className="c-channel">
            <summary>
              <b>{c.name}</b> <span className="muted">· {fmtNumber(c.count)} tin</span>
            </summary>
            <ul className="c-messages">
              {c.messages.map((m) => (
                <li key={m.id}>
                  <span className="mono muted">{m.when ? fmtDateTime(m.when) : ""}</span> <b>{m.author}</b>
                  {m.is_reply && <span className="muted"> ↪</span>}: {m.text}{" "}
                  <a href={m.url} target="_blank" rel="noopener noreferrer" className="c-link" aria-label="Mở tin trên Discord">
                    ↗
                  </a>
                  {m.reactions > 0 && <span className="muted"> · {fmtNumber(m.reactions)} reaction</span>}
                </li>
              ))}
            </ul>
          </details>
        ))
      )}
    </div>
  );
}

export function CommunityView() {
  const [digestId, setDigestId] = useState<number | null>(null);
  const { data, error, loading, reload } = useApi<CommunityPage>(digestId ? `community?digest=${digestId}` : "community");

  return (
    <>
      <div className="top">
        <div>
          <h1>Thảo luận cộng đồng</h1>
          <p>Mọi người đang bàn gì trên Discord và Shopify Community trong 24 giờ qua, tóm tắt bằng tiếng Việt. Phần này để theo dõi, không chấm điểm.</p>
        </div>
      </div>
      {error && <ErrorBox error={error} onRetry={() => reload()} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <Digest data={data} onPick={setDigestId} />
          <div className="grid-2">
            <Threads threads={data.threads} />
            <Channels channels={data.channels} />
          </div>
        </>
      )}
    </>
  );
}
