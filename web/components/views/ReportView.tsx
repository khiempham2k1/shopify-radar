"use client";

import Link from "next/link";
import { useApi } from "@/lib/api";
import { fmtDateTime, fmtNumber, pctChange, signed } from "@/lib/format";
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
                {reportPeriod(data)} · AI viết từ {fmtNumber(data.items_considered)} item đã lọc.
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
