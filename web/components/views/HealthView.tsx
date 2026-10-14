"use client";

import { useApi } from "@/lib/api";
import { fmtDateTime, fmtNumber, fmtShortDateTime, KIND, timeAgo } from "@/lib/format";
import type { HealthResponse, SourceHealth } from "@/lib/types";
import { Empty, ErrorBox, Loading } from "../States";

const STATUS_LABEL: Record<string, string> = {
  ok: "Ổn",
  warn: "Cảnh báo",
  error: "Lỗi",
  never: "Chưa chạy",
  off: "Đang tắt",
};

function dotClass(status: string) {
  return ["ok", "warn", "error", "never", "off"].includes(status) ? status : "never";
}

function Backends({ s }: { s: SourceHealth }) {
  const order = s.configured_backends;
  return (
    <>
      <span className={s.backend ? undefined : "muted"}>{s.backend || "–"}</span>
      {order.length > 1 && (
        <div className="backends" title="Thứ tự ưu tiên trong sources.yaml">
          <span>Thứ tự:</span>
          {order.map((b, i) => (
            <span key={b}>
              <span className={b === s.backend ? "cur" : undefined}>{b}</span>
              {i < order.length - 1 ? " →" : ""}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

function Logins({ logins }: { logins: NonNullable<HealthResponse["logins"]> }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Đăng nhập công cụ</h2>
        {logins.checked_at && (
          <span className="stamp mono" title={timeAgo(logins.checked_at)}>
            Kiểm tra lúc {fmtDateTime(logins.checked_at)}
          </span>
        )}
      </div>
      <p className="sub">Cookie của các tài khoản riêng cho radar. Hết hạn thì collector chuyển sang công cụ dự phòng hoặc không lấy được dữ liệu.</p>
      {logins.checks.length === 0 ? (
        <Empty>Chưa có lần kiểm tra nào.</Empty>
      ) : (
        <ul className="checks">
          {logins.checks.map((c) => (
            <li key={c.name}>
              <span className={`dot ${dotClass(c.status)}`} aria-hidden="true" />
              <span>
                <b>{c.name}</b> <span className="kind">· {STATUS_LABEL[c.status] ?? c.status}</span>
                {c.message && <span className="err-msg"> · {c.message}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function HealthView() {
  const { data, error, loading, reload } = useApi<HealthResponse>("health/sources");
  const counts = (data?.sources ?? []).reduce<Record<string, number>>((acc, s) => {
    acc[s.status] = (acc[s.status] || 0) + 1;
    return acc;
  }, {});
  const v = data?.videos;

  return (
    <>
      <div className="top">
        <div>
          <h1>Sức khỏe nguồn</h1>
          <p>Lần chạy gần nhất của từng collector và công cụ đang dùng. Nguồn lỗi sẽ không có item mới cho tới khi được sửa.</p>
        </div>
        {data && (
          <div className="stamp">
            {counts.error ? <b className="up-bad">{counts.error} nguồn lỗi</b> : <span>Không có nguồn lỗi</span>}
            {counts.warn ? (
              <>
                {" · "}
                <b className="up-warn">{counts.warn} cảnh báo</b>
              </>
            ) : null}
            {" · "}
            {fmtNumber(counts.ok || 0)} ổn
          </div>
        )}
      </div>

      {error && <ErrorBox error={error} onRetry={() => reload()} />}
      {loading && !data && <Loading />}

      {data && (
        <>
          <Logins logins={data.logins ?? { checked_at: null, checks: [] }} />

          <div className="panel">
            {data.sources.length === 0 ? (
              <Empty>Chưa có nguồn nào trong sources.yaml.</Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Nguồn</th>
                      <th>Công cụ đang dùng</th>
                      <th>Lần chạy cuối</th>
                      <th>Trạng thái</th>
                      <th className="num">Item lần chạy cuối</th>
                      <th className="num">Item mới · 24h</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sources.map((s) => (
                      <tr key={s.id}>
                        <td>
                          <b>{s.name}</b> <span className="kind">· {KIND[s.kind] ?? s.kind}</span>
                          {s.message && <div className="err-msg">{s.message}</div>}
                        </td>
                        <td>
                          <Backends s={s} />
                        </td>
                        <td className="mono" style={{ whiteSpace: "nowrap" }} title={s.last_run ? `${fmtDateTime(s.last_run)} · ${timeAgo(s.last_run)}` : undefined}>
                          {s.last_run ? fmtShortDateTime(s.last_run) : "–"}
                          {s.last_run && s.duration_ms > 0 && <div className="err-msg">{(s.duration_ms / 1000).toFixed(1)} giây</div>}
                        </td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <span className={`dot ${dotClass(s.status)}`} aria-hidden="true" />
                          {STATUS_LABEL[s.status] ?? s.status}
                        </td>
                        <td className="num">{fmtNumber(s.items_last_run)}</td>
                        <td className="num">{fmtNumber(s.new_24h)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {v && (
            <div className="panel">
              <h2>Nội dung video</h2>
              <p className="sub">Hàng đợi nghe video YouTube trong 24 giờ qua: phụ đề trước, Groq Whisper khi không có phụ đề.</p>
              <div className="stats">
                <div>
                  <b>{fmtNumber(v.subtitle_24h)}</b>
                  <span>video lấy từ phụ đề</span>
                </div>
                <div>
                  <b>{fmtNumber(v.groq_24h)}</b>
                  <span>video qua Groq</span>
                </div>
                <div>
                  <b>{fmtNumber(v.audio_minutes_24h)}</b>
                  <span>phút audio gửi Groq</span>
                </div>
                <div>
                  <b className={v.failed_24h ? "up-bad" : undefined}>{fmtNumber(v.failed_24h)}</b>
                  <span>video lỗi</span>
                </div>
                <div>
                  <b>{fmtNumber(v.processing)}</b>
                  <span>đang xử lý</span>
                </div>
                <div>
                  <b>{fmtNumber(v.skipped_24h)}</b>
                  <span>bỏ qua (quá dài)</span>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}
