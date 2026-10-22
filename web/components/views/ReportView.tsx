"use client";

import Link from "next/link";
import { useApi } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtNumber, IMPACT, pctChange, signed } from "@/lib/format";
import type { ReportDetail, ReportPoint } from "@/lib/types";
import { Empty, ErrorBox, Loading } from "../States";
import { reportPeriod, reportTitle } from "./ReportsView";

function Points({ points, items }: { points: ReportPoint[]; items: ReportDetail["items"] }) {
  if (points.length === 0) return <p className="muted">Không có mục nào.</p>;
  return (
    <ul>
      {points.map((p, i) => {
        const refs = (p.item_ids ?? []).map((id) => items[String(id)]).filter(Boolean);
        return (
          <li key={i}>
            {p.text}
            {refs.length > 0 && (
              <span className="refs">
                {refs.map((r) => (
                  <a key={r.id} href={r.url} target="_blank" rel="noopener noreferrer">
                    ↗ {r.title}
                  </a>
                ))}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function ReportView({ id }: { id: string }) {
  const valid = /^\d+$/.test(id);
  const { data, error, loading, reload } = useApi<ReportDetail>(valid ? `reports/${id}` : null);
  const c = data?.content;
  const tagCounts = c?.tag_counts ?? [];
  const coverage = c?.coverage ?? [];
  const gaps = coverage.filter((s) => s.runs === 0 || s.errors > 0 || s.new_items === 0);
  const deadlines = c?.deadlines ?? [];

  return (
    <>
      <Link href="/reports" className="back">
        ← Tất cả báo cáo
      </Link>
      {!valid && <ErrorBox error="Mã báo cáo không hợp lệ." />}
      {error && <ErrorBox error={error} onRetry={() => reload()} />}
      {loading && !data && <Loading />}
      {data && c && (
        <>
          <div className="top">
            <div>
              <h1>{reportTitle(data)}</h1>
              <p>
                {reportPeriod(data)} · AI viết từ{" "}
                {c.items_shown != null && c.items_total != null && c.items_shown < c.items_total
                  ? `${fmtNumber(c.items_shown)}/${fmtNumber(c.items_total)}`
                  : fmtNumber(data.items_considered)}{" "}
                item đã lọc
                {c.community_digests ? ` và ${fmtNumber(c.community_digests)} bản tóm tắt cộng đồng` : ""}.
                {c.unclassified ? ` Còn ${fmtNumber(c.unclassified)} item chưa được AI phân loại.` : ""}
              </p>
            </div>
            <div className="stamp mono">
              Tạo lúc {fmtDateTime(data.created_at)} · {data.model}
            </div>
          </div>

          {c.summary && (
            <div className="panel">
              <h2>Tóm tắt</h2>
              <p className="summary">{c.summary}</p>
            </div>
          )}

          <div className="panel report">
            <div>
              <h3 className="h-risk">Rủi ro</h3>
              <Points points={c.risks ?? []} items={data.items} />
            </div>
            <div>
              <h3 className="h-opp">Cơ hội</h3>
              <Points points={c.opportunities ?? []} items={data.items} />
            </div>
            <div>
              <h3 className="h-todo">Việc cần làm</h3>
              {(c.actions ?? []).length === 0 ? (
                <p className="muted">Không có mục nào.</p>
              ) : (
                <ul>
                  {(c.actions ?? []).map((a, i) => (
                    <li key={i}>
                      {a.text}
                      {a.owner && <span className="refs muted">Phụ trách: {a.owner}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {deadlines.length > 0 && (
            <div className="panel">
              <h2>Hạn chót</h2>
              <p className="sub">Từ thay đổi nền tảng, lấy từ kết quả phân loại (không do AI viết lại)</p>
              <div className="table-wrap">
                <table className="narrow">
                  <thead>
                    <tr>
                      <th>Hạn</th>
                      <th>Thay đổi</th>
                      <th>Mức</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deadlines.map((d) => (
                      <tr key={d.item_id}>
                        <td className="mono">{fmtDate(d.deadline)}</td>
                        <td>
                          <a href={d.url} target="_blank" rel="noopener noreferrer">
                            {d.title}
                          </a>
                        </td>
                        <td>{d.impact ? IMPACT[d.impact] : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {coverage.length > 0 && (
            <div className="panel">
              <h2>Độ phủ dữ liệu</h2>
              <p className="sub">
                {gaps.length === 0
                  ? "Mọi nguồn đều chạy bình thường trong tuần."
                  : `${fmtNumber(gaps.length)} nguồn lỗi hoặc không có item mới: kết luận có thể thiếu phần này.`}
              </p>
              <div className="table-wrap">
                <table className="narrow">
                  <thead>
                    <tr>
                      <th>Nguồn</th>
                      <th className="num">Lần chạy</th>
                      <th className="num">Lỗi</th>
                      <th className="num">Item mới</th>
                    </tr>
                  </thead>
                  <tbody>
                    {coverage.map((s) => (
                      <tr key={s.source}>
                        <td>{s.name}</td>
                        <td className="num">{fmtNumber(s.runs)}</td>
                        <td className="num">{s.errors ? fmtNumber(s.errors) : "—"}</td>
                        <td className="num">{fmtNumber(s.new_items)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="panel">
            <h2>Số item theo tag</h2>
            <p className="sub">So với tuần liền trước</p>
            {tagCounts.length === 0 ? (
              <Empty>Báo cáo này chưa có thống kê theo tag.</Empty>
            ) : (
              <div className="table-wrap">
                <table className="narrow">
                  <thead>
                    <tr>
                      <th>Tag</th>
                      <th className="num">Tuần này</th>
                      <th className="num">Tuần trước</th>
                      <th className="num">Thay đổi</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tagCounts.map((t) => {
                      const pct = pctChange(t.count, t.previous);
                      return (
                        <tr key={t.tag}>
                          <td>{t.tag}</td>
                          <td className="num">{fmtNumber(t.count)}</td>
                          <td className="num">{fmtNumber(t.previous)}</td>
                          <td className="num">{pct == null ? "mới" : signed(pct, "%")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
