"use client";

import { useApi } from "@/lib/api";
import { describeCron, dueClass, fmtDate, fmtDateTime, fmtNumber, pctChange, signed } from "@/lib/format";
import type { Item, Overview } from "@/lib/types";
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
        <span className="d">
          chưa có người nhận: <b className={k.todo_unassigned ? "up-bad" : undefined}>{fmtNumber(k.todo_unassigned)}</b>
        </span>
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

function Priority({ data, onChange }: { data: Overview["priority"]; onChange: (updated: Item) => void }) {
  if (data.topics.length === 0) return null;
  return (
    <div className="panel">
      <h2>Chủ đề ưu tiên</h2>
      <p className="sub">Cập nhật mới nhất về các chủ đề trong priorities.txt (sửa ở trang Cài đặt), 30 ngày qua</p>
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
              <PlatformRow key={item.id} item={item} compact onChange={onChange} />
            ) : (
              <FeedRow key={item.id} item={item} compact />
            ),
          )}
        </div>
      )}
    </div>
  );
}

export function OverviewView() {
  const { data, error, loading, reload, setData } = useApi<Overview>("overview");

  const replaceTodo = (updated: Item) => {
    const swap = (list: Item[]) => list.map((i) => (i.id === updated.id ? updated : i));
    setData((d) => (d ? { ...d, todo: swap(d.todo), priority: { ...d.priority, items: swap(d.priority.items) } } : d));
    reload({ silent: true });
  };

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

      {error && <ErrorBox error={error} onRetry={() => reload()} />}
      {loading && !data && <Loading />}

      {data && (
        <>
          <Kpis k={data.kpis} />
          {data.priority && <Priority data={data.priority} onChange={replaceTodo} />}
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
          <div className="panel">
            <h2>Cần xử lý</h2>
            <p className="sub">Thay đổi nền tảng mức cao chưa xong và thảo luận điểm cao, xếp theo hạn chót rồi điểm</p>
            {data.todo.length === 0 ? (
              <Empty>Không còn việc nào cần xử lý.</Empty>
            ) : (
              <div className="list">
                {data.todo.map((item) =>
                  item.source.kind === "platform" ? (
                    <PlatformRow key={item.id} item={item} compact onChange={replaceTodo} />
                  ) : (
                    <FeedRow key={item.id} item={item} compact />
                  ),
                )}
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
