"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";
import { fmtDate, fmtNumber, fmtUsd, TASK } from "@/lib/format";
import type { Usage } from "@/lib/types";
import { BarChart, type BarSeries } from "../BarChart";
import { Empty, ErrorBox, Loading } from "../States";

const RANGES = [7, 30, 90];
const SERIES: BarSeries[] = [{ key: "cost", label: "Chi phí", color: "var(--accent)" }];

export function UsageView() {
  const [days, setDays] = useState(30);
  const { data, error, loading, reload } = useApi<Usage>(`usage?days=${days}`);
  const calls = data?.by_task.reduce((s, t) => s + t.calls, 0) ?? 0;
  const sum = (k: "input_tokens" | "output_tokens" | "cache_read_tokens") => data?.by_task.reduce((s, t) => s + t[k], 0) ?? 0;
  const rows = (data?.daily ?? []).map((d) => ({ label: d.date.slice(8, 10), title: fmtDate(d.date, false), values: { cost: d.cost } }));

  return (
    <>
      <div className="top">
        <div>
          <h1>Chi phí AI</h1>
          <p>Token Claude theo tác vụ và theo ngày, tính theo bảng giá trong sources.yaml. Groq Whisper tính riêng theo phút audio.</p>
        </div>
        <div className="filters" role="group" aria-label="Khoảng thời gian">
          {RANGES.map((r) => (
            <button key={r} type="button" className="chip" aria-pressed={days === r} onClick={() => setDays(r)}>
              {r} ngày
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorBox error={error} onRetry={() => reload()} />}
      {loading && !data && <Loading />}

      {data && (
        <>
          <div className="kpis three">
            <div className="kpi">
              <span className="k">Tổng chi phí Claude · {data.days} ngày</span>
              <span className="v">{fmtUsd(data.total_cost)}</span>
              <span className="d">
                trung bình <b>{fmtUsd(data.total_cost / Math.max(1, data.days))}</b> mỗi ngày
              </span>
            </div>
            <div className="kpi">
              <span className="k">Lượt gọi Claude</span>
              <span className="v">{fmtNumber(calls)}</span>
              <span className="d">
                {data.by_model.length > 0 ? data.by_model.map((m) => `${m.model}: ${fmtUsd(m.cost)}`).join(" · ") : "chưa có lượt gọi nào"}
              </span>
            </div>
            <div className="kpi">
              <span className="k">Video qua Groq Whisper</span>
              <span className="v">{fmtNumber(data.groq.videos)}</span>
              <span className="d">
                <b>{fmtNumber(data.groq.audio_minutes)}</b> phút audio
              </span>
            </div>
          </div>

          <div className="panel">
            <h2>Chi phí theo ngày</h2>
            <p className="sub">USD, theo giờ Việt Nam</p>
            {data.total_cost === 0 ? (
              <Empty>Chưa có chi phí nào trong {data.days} ngày qua.</Empty>
            ) : (
              <div className="chart-wrap">
                <BarChart rows={rows} series={SERIES} integer={false} format={(v) => fmtUsd(v)} ariaLabel={`Biểu đồ cột chi phí Claude theo ngày, ${data.days} ngày gần nhất`} />
              </div>
            )}
          </div>

          <div className="panel">
            <h2>Theo tác vụ</h2>
            <p className="sub">Cache read là phần input đọc lại từ prompt cache, giá thấp hơn nhiều so với input thường.</p>
            {data.by_task.length === 0 ? (
              <Empty>Chưa có lượt gọi nào.</Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Tác vụ</th>
                      <th className="num">Lượt gọi</th>
                      <th className="num">Token vào</th>
                      <th className="num">Token ra</th>
                      <th className="num">Cache read</th>
                      <th className="num">Chi phí</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_task.map((t) => (
                      <tr key={t.task}>
                        <td>{TASK[t.task] ?? t.task}</td>
                        <td className="num">{fmtNumber(t.calls)}</td>
                        <td className="num">{fmtNumber(t.input_tokens)}</td>
                        <td className="num">{fmtNumber(t.output_tokens)}</td>
                        <td className="num">{fmtNumber(t.cache_read_tokens)}</td>
                        <td className="num">{fmtUsd(t.cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td>Tổng</td>
                      <td className="num">{fmtNumber(calls)}</td>
                      <td className="num">{fmtNumber(sum("input_tokens"))}</td>
                      <td className="num">{fmtNumber(sum("output_tokens"))}</td>
                      <td className="num">{fmtNumber(sum("cache_read_tokens"))}</td>
                      <td className="num">{fmtUsd(data.total_cost)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
