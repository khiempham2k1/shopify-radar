"use client";

import { useEffect, useState } from "react";
import { useApi } from "@/lib/api";
import { describeCron, dueClass, fmtDate, fmtDateTime, fmtNumber, ownText, pctChange, signed, timeAgo } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { BarChart, Legend, type BarSeries } from "../BarChart";
import { FeedRow, PlatformRow } from "../ItemRows";
import { Empty, ErrorBox, Loading } from "../States";

const SERIES: BarSeries[] = [
  { key: "platform", label: "Nền tảng", color: "var(--c-plat)" },
  { key: "social", label: "Social", color: "var(--c-social)" },
  { key: "web", label: "Web search", color: "var(--c-web)" },
];

function Kpis({ k }: { k: Overview["kpis"] }) {
  const pct = pctChange(k.new_7d, k.new_prev_7d);
  const ratio = k.negative_ratio;
  const delta = ratio != null && k.negative_ratio_prev != null ? Math.round((ratio - k.negative_ratio_prev) * 100) : null;
  return (
    <div className="kpis">
      <div className="kpi">
        <span className="k">Item mới · 7 ngày</span>
        <span className="v">{fmtNumber(k.new_7d)}</span>
        <span className="d">
          {pct != null ? (
            <>
              <b className={pct >= 0 ? "up-good" : "up-bad"}>{signed(pct, "%")}</b> so với 7 ngày trước
            </>
          ) : (
            <>7 ngày trước: <b>{fmtNumber(k.new_prev_7d)}</b></>
          )}
        </span>
      </div>
      <div className="kpi">
        <span className="k">Cần xử lý</span>
        <span className="v">{fmtNumber(k.todo)}</span>
        <span className="d">thay đổi đã phát hành ở changelog, Editions</span>
      </div>
      <div className="kpi">
        <span className="k">Hạn chót trong 90 ngày</span>
        <span className="v">{fmtNumber(k.deadlines_90d)}</span>
        <span className="d">
          {k.nearest_deadline_days != null ? (
            <>
              gần nhất:{" "}
              <b className={{ soon: "up-bad", mid: "up-warn", far: undefined }[dueClass(k.nearest_deadline_days)]}>
                {k.nearest_deadline_days < 0 ? `quá hạn ${-k.nearest_deadline_days} ngày` : `${k.nearest_deadline_days} ngày`}
              </b>
            </>
          ) : (
            "không có hạn chót gần"
          )}
        </span>
      </div>
      <div className="kpi">
        <span className="k">Tỉ lệ tiêu cực · social</span>
        <span className="v">{ratio != null ? `${Math.round(ratio * 100)}%` : "–"}</span>
        <span className="d">
          <b className={delta == null || delta === 0 ? undefined : delta > 0 ? "up-bad" : "up-good"}>{delta != null ? signed(delta, " điểm") : "–"}</b> so với tuần trước
        </span>
      </div>
    </div>
  );
}

function Topics({ topics }: { topics: Overview["topics"] }) {
  if (topics.length === 0) return <Empty>Tuần này AI chưa gom được chủ đề nào.</Empty>;
  const max = Math.max(...topics.map((t) => t.count), 1);
  return (
    <div className="topics">
      {topics.map((t) => {
        const pct = pctChange(t.count, t.previous);
        const label = pct == null ? "mới" : signed(pct, "%");
        return (
          <div className="topic" key={t.tag}>
            <span className="name">{t.tag}</span>
            <span className="n" title={`Tuần trước: ${t.previous}`}>
              {fmtNumber(t.count)} · <span className={pct == null || pct > 0 ? "up-bad" : undefined}>{label}</span>
            </span>
            <div className="bar">
              <span style={{ width: `${((t.count / max) * 100).toFixed(0)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

type Brief = NonNullable<Overview["brief"]>;

function Highlights({ brief }: { brief: Brief }) {
  return (
    <div className="panel brief">
      <div className="panel-head">
        <h2>Tóm tắt nổi bật</h2>
        {brief.created_at && (
          <span className="stamp mono" title={fmtDateTime(brief.created_at)}>
            AI viết {timeAgo(brief.created_at)}
            {brief.window_days ? ` · ${brief.window_days} ngày qua` : ""}
          </span>
        )}
      </div>
      {brief.headline && <p className="brief-headline">{brief.headline}</p>}
      {brief.summary && <p className="brief-summary">{brief.summary}</p>}
      {brief.highlights.length > 0 && (
        <ul className="brief-points">
          {brief.highlights.map((h, i) => (
            <li key={i}>
              {h.text}
              {h.items.map((it) => (
                <a key={it.id} className="c-link" href={it.url} target="_blank" rel="noopener noreferrer" title={it.title}>
                  ↗ {it.official ? "✓ " : ""}
                  {it.source}
                </a>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MustRead({ brief }: { brief: Brief }) {
  return (
    <div className="panel">
      <h2>Bài nên đọc</h2>
      <p className="sub">AI chọn từ những bài đã lọc, kèm lý do nên đọc</p>
      {brief.must_read.length === 0 ? (
        <Empty>Chưa có bài nào đáng chú ý.</Empty>
      ) : (
        <div className="list">
          {brief.must_read.map((item) =>
            item.source.kind === "platform" ? (
              <PlatformRow key={item.id} item={item} compact note={item.why} />
            ) : (
              <FeedRow key={item.id} item={item} compact note={item.why} />
            ),
          )}
        </div>
      )}
    </div>
  );
}

function Discussions({ brief }: { brief: Brief }) {
  return (
    <div className="panel">
      <h2>Thảo luận nên đọc</h2>
      <p className="sub">
        Từ Discord và Shopify Community · <a href="/community">xem tất cả</a>
      </p>
      {brief.discussions.length === 0 ? (
        <Empty>Chưa có thảo luận nào đáng chú ý.</Empty>
      ) : (
        <div className="list">
          {brief.discussions.map((d) => {
            // A Discord message reads by its (translated) words; a thread by its title, its summary below.
            const said = d.summary || ownText(d.text) || d.title;
            const title = d.is_message ? (said.length > 180 ? `${said.slice(0, 180)}…` : said) : d.title;
            return (
              <div className="row" key={d.id}>
                <div className="stripe sev-low" />
                <div style={{ minWidth: 0 }}>
                  <div className="t">
                    <a href={d.url} target="_blank" rel="noopener noreferrer">
                      {title}
                    </a>
                  </div>
                  <div className="m">
                    <span className="src">{d.place}</span>
                    {d.author && <span>{d.author}</span>}
                    {d.when && <span title={fmtDateTime(d.when)}>{timeAgo(d.when)}</span>}
                    {d.comments > 0 && <span>{fmtNumber(d.comments)} trả lời</span>}
                    {d.reactions > 0 && <span>{fmtNumber(d.reactions)} reaction</span>}
                  </div>
                  {!d.is_message && d.summary && <div className="ai">{d.summary}</div>}
                  {d.why && <div className="ai note">💡 {d.why}</div>}
                </div>
                <div />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Priority({ data }: { data: Overview["priority"] }) {
  if (data.topics.length === 0) return null;
  return (
    <div className="panel">
      <h2>Chủ đề ưu tiên</h2>
      <p className="sub">Cập nhật mới nhất về các chủ đề team đang theo sát, 30 ngày qua</p>
      <div className="prio-topics">
        {data.topics.map((t) => (
          <span key={t} className="tag prio">
            ★ {t}
          </span>
        ))}
      </div>
      {data.items.length === 0 ? (
        <Empty>Chưa có cập nhật nào về các chủ đề này trong 30 ngày qua.</Empty>
      ) : (
        <div className="list">
          {data.items.map((item) =>
            item.source.kind === "platform" ? (
              <PlatformRow key={item.id} item={item} compact />
            ) : (
              <FeedRow key={item.id} item={item} compact />
            ),
          )}
        </div>
      )}
    </div>
  );
}

function TodoPanel({ todo }: { todo: Overview["todo"] }) {
  return (
    <div className="panel">
      <h2>Cần xử lý</h2>
      <p className="sub">Thay đổi đã phát hành ở Shopify dev changelog, Shopify Changelog và Editions, ảnh hưởng tới theme và chưa xong: mức cao, hoặc mức trung bình có hạn chót. Xếp theo hạn chót.</p>
      {todo.length === 0 ? (
        <Empty>Không còn việc nào cần xử lý.</Empty>
      ) : (
        <div className="list">
          {todo.map((item) =>
            item.source.kind === "platform" ? <PlatformRow key={item.id} item={item} compact /> : <FeedRow key={item.id} item={item} compact />,
          )}
        </div>
      )}
    </div>
  );
}

export function OverviewView() {
  const { data, error, loading, reload } = useApi<Overview>("overview");
  const [denied, setDenied] = useState(false);
  useEffect(() => {
    // Set by the middleware when a signed-in account without Phase 2 access opens a Phase 2 page.
    setDenied(new URLSearchParams(window.location.search).get("denied") === "phase2");
  }, []);


  const rows = (data?.daily ?? []).map((d) => ({
    label: d.date.slice(8, 10),
    title: fmtDate(d.date, false),
    values: { platform: d.platform, social: d.social, web: d.web },
  }));
  const first = data?.daily[0]?.date;
  const last = data?.daily.at(-1)?.date;

  return (
    <>
      <div className="top">
        <div>
          <h1>Tổng quan</h1>
          <p>Những gì cần biết trong 7 ngày qua, và những việc đang chờ người xử lý.</p>
        </div>
        {data && (
          <div className="stamp mono">
            {data.last_run ? `Cập nhật ${fmtDateTime(data.last_run)}` : "Chưa có lần chạy nào"}
            {data.schedule ? ` · ${describeCron(data.schedule)}` : ""}
          </div>
        )}
      </div>

      {denied && <div className="notice">Tài khoản này chưa được cấp quyền xem Báo cáo tuần, Cài đặt và Chi phí AI. Nhờ quản trị cấp quyền.</div>}
      {error && <ErrorBox error={error} onRetry={() => reload()} />}
      {loading && !data && <Loading />}

      {data && (
        <>
          <Kpis k={data.kpis} />
          {data.brief ? (
            <>
              <Highlights brief={data.brief} />
              <div className="grid-2">
                <MustRead brief={data.brief} />
                <Discussions brief={data.brief} />
              </div>
            </>
          ) : (
            <div className="panel">
              <h2>Tóm tắt nổi bật</h2>
              <Empty>Chưa có bản tóm tắt. AI viết bản đầu tiên ở lượt chạy tới (hoặc chạy lệnh radar brief).</Empty>
            </div>
          )}
          <TodoPanel todo={data.todo} />
          {data.priority && <Priority data={data.priority} />}
          <div className="grid-2">
            <div className="panel">
              <h2>Item mới theo ngày</h2>
              <p className="sub">{rows.length} ngày gần nhất, sau khi lọc từ khóa và AI</p>
              <Legend series={SERIES} />
              <div className="chart-wrap">
                <BarChart
                  rows={rows}
                  series={SERIES}
                  ariaLabel={`Biểu đồ cột chồng số item mới theo ngày${first && last ? `, từ ${fmtDate(first, false)} đến ${fmtDate(last, false)}` : ""}`}
                />
              </div>
            </div>
            <div className="panel">
              <h2>Chủ đề nổi tuần này</h2>
              <p className="sub">AI gom theo tag, so với tuần trước</p>
              <Topics topics={data.topics} />
            </div>
          </div>
        </>
      )}
    </>
  );
}
