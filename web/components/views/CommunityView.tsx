"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";
import { fmtDateTime, fmtNumber, ownText, timeAgo } from "@/lib/format";
import type { CommunityPage, CommunityRef, CommunityTopic } from "@/lib/types";
import { Empty, ErrorBox, Loading } from "../States";

const TOPIC_KIND: Record<CommunityTopic["kind"], string> = {
  question: "Hỏi đáp",
  problem: "Báo lỗi",
  tip: "Mẹo, cách làm",
  news: "Tin tức",
  discussion: "Bàn luận",
};

const IMAGE_EXT = /\.(png|jpe?g|gif|webp)$/i;


/** Attachments, link previews and the message replied to, under a Discord message. */
function MessageDetails({ m }: { m: CommunityRef }) {
  const attachments = m.attachments ?? [];
  const images = attachments.filter((a) => a.type.startsWith("image/") || IMAGE_EXT.test(a.name));
  const files = attachments.filter((a) => !images.includes(a));
  const embeds = m.embeds ?? [];
  if (!m.reply_text && !attachments.length && !embeds.length && !m.image_note) return null;
  return (
    <div className="c-details">
      {m.reply_text && (
        <div className="c-reply">
          ↪ trả lời <b>{m.reply_author || "ai đó"}</b>: {m.reply_text}
        </div>
      )}
      {images.length > 0 && (
        <div className="c-images">
          {images.map((a) => (
            <a key={a.url} href={a.url} target="_blank" rel="noopener noreferrer" title={a.name}>
              {/* Discord's signed links expire after about a day; then only the name is left. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={a.url}
                alt={a.name}
                loading="lazy"
                onError={(e) => {
                  e.currentTarget.replaceWith(document.createTextNode(`🖼 ${a.name}`));
                }}
              />
            </a>
          ))}
        </div>
      )}
      {m.image_note && <div className="c-note">🖼 {m.image_note}</div>}
      {files.map((a) => (
        <div key={a.url} className="c-file">
          📎{" "}
          <a href={a.url} target="_blank" rel="noopener noreferrer">
            {a.name}
          </a>
        </div>
      ))}
      {embeds.map((e, i) => (
        <div key={i} className="c-embed">
          {e.site && <div className="muted">{e.site}</div>}
          {e.url ? (
            <a href={e.url} target="_blank" rel="noopener noreferrer">
              <b>{e.title || e.url}</b>
            </a>
          ) : (
            <b>{e.title}</b>
          )}
          {e.description && <div>{e.description}</div>}
        </div>
      ))}
    </div>
  );
}

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
        <h2>Tóm tắt thảo luận</h2>
        <Empty>Chưa có bản tóm tắt. Bản đầu tiên được tạo ở lần chạy tới khi có tin từ Discord hoặc Shopify Community.</Empty>
      </div>
    );
  }
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{data.digests[0]?.id === d.id ? "Tóm tắt mới nhất" : "Tóm tắt"}</h2>
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
        AI tóm tắt {fmtNumber(d.items_considered)} tin mới so với bản trước
        {d.places?.length ? ` (${d.places.map((p) => `${p.name}: ${fmtNumber(p.count)}`).join(", ")})` : ""}
        {data.pending > 0 ? ` · ${fmtNumber(data.pending)} tin đến sau, sẽ vào bản tóm tắt tới` : ""}
      </p>
      <p className="c-overview">{d.overview}</p>

      {d.topics.length > 0 && (
        <div className="c-topics">
          {d.topics.map((t, i) => (
            <details key={i} className="c-topic" open={i < 3}>
              <summary>
                <span className="c-kind">{TOPIC_KIND[t.kind] ?? t.kind}</span>
                <b>{t.title}</b>
                <span className="muted">
                  {t.mentions ? ` · ${fmtNumber(t.mentions)} tin` : ""}
                  {t.people ? ` · ${fmtNumber(t.people)} người` : ""} · {t.sources.join(", ")}
                </span>
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
      <p className="sub">Chủ đề trong bản tóm tắt đang xem, tóm tắt bằng tiếng Việt</p>
      {threads.length === 0 ? (
        <Empty>Chưa có chủ đề mới.</Empty>
      ) : (
        <div className="list">
          {threads.map((t) => (
            <div className="row" key={t.id}>
              <div className="stripe sev-low" />
              <div style={{ minWidth: 0 }}>
                <div className="t">
                  {t.pending && <span className="c-new">mới</span>}
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

function Message({ m }: { m: CommunityRef }) {
  return (
    <>
      {m.pending && <span className="c-new">mới</span>}
      <span className="mono muted">{m.when ? fmtDateTime(m.when) : ""}</span> <b>{m.author}</b>
      {m.is_reply && <span className="muted"> ↪</span>}: {m.summary || ownText(m.text)}{" "}
      <a href={m.url} target="_blank" rel="noopener noreferrer" className="c-link" aria-label="Mở tin trên Discord">
        ↗
      </a>
      {((m.thread ?? 0) > 0 || m.reactions > 0) && (
        <span className="c-stats">
          {(m.thread ?? 0) > 0 && <span title="Số phản hồi, tính cả trả lời lồng nhau">💬 {fmtNumber(m.thread ?? 0)}</span>}
          {m.reactions > 0 && <span title="Reaction">👍 {fmtNumber(m.reactions)}</span>}
        </span>
      )}
      <MessageDetails m={m} />
      {m.summary && m.summary !== ownText(m.text) && (
        <details className="c-orig">
          <summary>Bản gốc</summary>
          {ownText(m.text)}
        </details>
      )}
    </>
  );
}

function Channels({ channels, sort, onSort }: { channels: CommunityPage["channels"]; sort: CommunityPage["sort"]; onSort: (s: CommunityPage["sort"]) => void }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Discord</h2>
        <div className="chips" role="group" aria-label="Sắp xếp tin Discord">
          <button type="button" className="chip" aria-pressed={sort === "hot"} onClick={() => onSort("hot")}>
            Nhiều phản hồi nhất
          </button>
          <button type="button" className="chip" aria-pressed={sort === "new"} onClick={() => onSort("new")}>
            Mới nhất
          </button>
        </div>
      </div>
      <p className="sub">
        {sort === "hot"
          ? "Cuộc trao đổi được trả lời và thả reaction nhiều nhất lên đầu, phản hồi gom dưới tin gốc. "
          : "Mọi tin, mới nhất trước. "}
        Dịch sang tiếng Việt (bấm “Bản gốc” để xem nguyên văn). Nhãn “mới”: đến sau bản tóm tắt.
      </p>
      {channels.length === 0 ? (
        <Empty>Chưa có tin nhắn Discord nào.</Empty>
      ) : (
        channels.map((c) => {
          const head = (
            <>
              <b>{c.name}</b> <span className="muted">· {fmtNumber(c.count)} tin</span>
            </>
          );
          const list = (
            <ul className="c-messages">
              {c.messages.map((m) => (
                <li key={m.id}>
                  <Message m={m} />
                  {(m.thread_replies?.length ?? 0) > 0 && (
                    <details className="c-thread">
                      <summary>Xem {fmtNumber(m.thread_replies!.length)} phản hồi</summary>
                      <ul className="c-messages">
                        {m.thread_replies!.map((r) => (
                          <li key={r.id}>
                            <Message m={r} />
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          );
          // Collapsible only when there are many channels; one or two are shown in full.
          return channels.length > 2 ? (
            <details key={c.name} className="c-channel">
              <summary>{head}</summary>
              {list}
            </details>
          ) : (
            <div key={c.name} className="c-channel">
              <div>{head}</div>
              {list}
            </div>
          );
        })
      )}
    </div>
  );
}

export function CommunityView() {
  const [digestId, setDigestId] = useState<number | null>(null);
  const [sort, setSort] = useState<CommunityPage["sort"]>("hot");
  const params = new URLSearchParams({ sort });
  if (digestId) params.set("digest", String(digestId));
  const { data, error, loading, reload } = useApi<CommunityPage>(`community?${params}`);

  return (
    <>
      <div className="top">
        <div>
          <h1>Thảo luận cộng đồng</h1>
          <p>Mọi người đang bàn gì trên Discord và Shopify Community, tóm tắt bằng tiếng Việt. Mỗi bản tóm tắt chỉ gồm tin mới so với bản trước; chọn bản cũ ở ô bên phải. Phần này để theo dõi, không chấm điểm.</p>
        </div>
      </div>
      {error && <ErrorBox error={error} onRetry={() => reload()} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <Digest data={data} onPick={setDigestId} />
          <div className="grid-2">
            <Threads threads={data.threads} />
            <Channels channels={data.channels} sort={sort} onSort={setSort} />
          </div>
        </>
      )}
    </>
  );
}
