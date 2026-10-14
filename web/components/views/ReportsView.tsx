"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText, useApi } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtNumber, isoWeek } from "@/lib/format";
import type { ReportDetail, ReportSummary } from "@/lib/types";
import { useToast } from "../Providers";
import { Empty, ErrorBox, Loading } from "../States";

export function reportTitle(r: { period_start: string }) {
  return `Báo cáo tuần ${isoWeek(r.period_start)}`;
}

export function reportPeriod(r: { period_start: string; period_end: string }) {
  return `${fmtDate(r.period_start, false)} – ${fmtDate(r.period_end)}`;
}

function GenerateButton() {
  const router = useRouter();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const t = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(t);
  }, [running]);

  async function run() {
    setRunning(true);
    setElapsed(0);
    setError(null);
    try {
      const report = await api<ReportDetail>("reports/weekly", "POST");
      toast(`Đã viết xong ${reportTitle(report).toLowerCase()}.`);
      router.push(`/reports/${report.id}`);
    } catch (err) {
      setError(errorText(err));
      setRunning(false);
    }
  }

  return (
    <div className="actions" style={{ flexDirection: "column", alignItems: "flex-end" }}>
      <button type="button" className="btn primary lg" onClick={run} disabled={running} aria-describedby="gen-status">
        {running ? "Đang viết báo cáo…" : "Viết báo cáo tuần trước ngay"}
      </button>
      <span id="gen-status" className="stamp" role="status">
        {running ? (
          <>
            <span className="spinner" aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6 }} />
            AI đang đọc item của tuần trước, thường mất 1–2 phút · <span className="mono">{elapsed}s</span>
          </>
        ) : (
          "Báo cáo tự chạy sáng thứ Hai. Viết lại tuần đã có sẽ thay bản cũ."
        )}
      </span>
      {error && <ErrorBox error={error} prefix="Không viết được báo cáo" onRetry={run} />}
    </div>
  );
}

export function ReportsView() {
  const { data, error, loading, reload } = useApi<ReportSummary[]>("reports");
  return (
    <>
      <div className="top">
        <div>
          <h1>Báo cáo tuần</h1>
          <p>AI đọc các item đã lọc trong tuần và viết rủi ro, cơ hội, việc cần làm. Dùng làm đầu vào cho họp sản phẩm.</p>
        </div>
        <GenerateButton />
      </div>
      <div className="panel">
        {error && <ErrorBox error={error} onRetry={() => reload()} />}
        {loading && !data && <Loading />}
        {data &&
          (data.length === 0 ? (
            <Empty>Chưa có báo cáo nào. Bấm “Viết báo cáo tuần trước ngay” để tạo báo cáo đầu tiên.</Empty>
          ) : (
            <div className="report-list">
              {data.map((r) => (
                <Link key={r.id} href={`/reports/${r.id}`} className="rep">
                  <span className="rt">{reportTitle(r)}</span>
                  <span className="rm">
                    {reportPeriod(r)} · AI viết từ {fmtNumber(r.items_considered)} item
                  </span>
                  <span className="rc mono">
                    {fmtDateTime(r.created_at)}
                    <br />
                    {r.model}
                  </span>
                </Link>
              ))}
            </div>
          ))}
      </div>
    </>
  );
}
