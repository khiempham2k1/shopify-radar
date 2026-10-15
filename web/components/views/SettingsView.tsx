"use client";

import { useEffect, useState } from "react";
import { api, errorText, useApi } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { SettingFile } from "@/lib/types";
import { useToast } from "../Providers";
import { ErrorBox, Loading } from "../States";

function Help({ name }: { name: string }) {
  switch (name) {
    case "keywords.txt":
      return (
        <div className="help">
          <span>
            Lọc thô trước khi gửi AI. Cú pháp theo TrendRadar: <code>[nhóm]</code> mở một nhóm (dòng trống kết thúc nhóm), <code>/regex/</code>,{" "}
            <code>+bắt buộc</code>, <code>!loại trừ</code>, <code>@20</code> giới hạn số item, <code>từ =&gt; tên</code> đặt tên hiển thị.
          </span>
          <span>
            Nhóm <code>[GLOBAL_FILTER]</code> loại item ở mọi nơi. File trống = không lọc, mọi item đều chuyển sang AI.
          </span>
        </div>
      );
    case "priorities.txt":
      return (
        <div className="help">
          <span>
            Chủ đề cần theo sát, ví dụ <code>Shopify Canvas</code>. Mỗi dòng một chủ đề; từ đầu tiên là tên và được tìm thêm trên Reddit, X, YouTube,
            web search, Hacker News. Cách viết khác ngăn bằng <code>|</code>, regex đặt trong <code>/.../</code>.
          </span>
          <span>Item nhắc tới chủ đề luôn hiển thị, được cộng điểm, có nhãn ★ và đứng đầu trang Tổng quan. Áp dụng từ lần chạy tiếp theo.</span>
        </div>
      );
    case "interests.txt":
      return (
        <div className="help">
          <span>Viết bằng lời thường. AI đọc file này để tạo tag phân loại. Đổi nhiều thì AI sẽ phân loại lại các item gần đây.</span>
        </div>
      );
    case "sources.yaml":
      return (
        <div className="help">
          <span>
            Nguồn thu thập, lịch chạy (<code>schedule</code>), tham số AI, video và trọng số chấm điểm. Mỗi nguồn cần <code>id</code> riêng; sai cú
            pháp YAML sẽ không lưu được.
          </span>
          <span>
            <code>freshness.max_age_days</code> (mặc định 30): bỏ bài/video đăng trước số ngày này; từng nguồn đặt <code>max_age_days</code> riêng được.
          </span>
        </div>
      );
    case "terms.txt":
      return (
        <div className="help">
          <span>Thuật ngữ Shopify gửi kèm cho Groq Whisper để nghe đúng từ chuyên ngành trong video, cách nhau bằng dấu phẩy.</span>
        </div>
      );
    default:
      return null;
  }
}

function Editor({ file, draft, onDraft, onSaved }: { file: SettingFile; draft: string; onDraft: (v: string) => void; onSaved: (f: SettingFile) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dirty = draft !== file.value;

  useEffect(() => setError(null), [file.name]);

  async function save() {
    setBusy("save");
    setError(null);
    try {
      const saved = await api<SettingFile>(`settings/${encodeURIComponent(file.name)}`, "PUT", { value: draft });
      onSaved(saved);
      toast(`Đã lưu ${file.name}. Lần chạy sau sẽ dùng nội dung mới.`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    if (!window.confirm(`Bỏ bản đã sửa trên dashboard và dùng lại ${file.name} trong thư mục config?`)) return;
    setBusy("reset");
    setError(null);
    try {
      const restored = await api<SettingFile>(`settings/${encodeURIComponent(file.name)}`, "DELETE");
      onSaved(restored);
      toast(`${file.name} đã về bản trong file.`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div role="tabpanel" id={`panel-${file.name}`} aria-labelledby={`tab-${file.name}`}>
      <div className="meta-line">
        {file.origin === "db" ? (
          <span className="pill ok">Bản đã sửa trên dashboard</span>
        ) : (
          <span className="pill low">Bản trong file config</span>
        )}
        {file.origin === "db" && (
          <span>
            Sửa bởi {file.updated_by || "không rõ"} lúc <span className="mono">{fmtDateTime(file.updated_at)}</span>
          </span>
        )}
        {dirty && <span className="up-warn">Có thay đổi chưa lưu</span>}
      </div>
      <Help name={file.name} />
      <textarea
        className="code"
        value={draft}
        onChange={(e) => onDraft(e.target.value)}
        spellCheck={false}
        aria-label={`Nội dung ${file.name}`}
        wrap="off"
      />
      {error && (
        <div style={{ marginTop: 10 }}>
          <ErrorBox error={error} prefix="Chưa lưu được" />
        </div>
      )}
      <div className="actions" style={{ marginTop: 12 }}>
        <button type="button" className="btn primary lg" onClick={save} disabled={!dirty || busy !== null}>
          {busy === "save" ? "Đang lưu…" : "Lưu"}
        </button>
        {dirty && (
          <button type="button" className="btn lg" onClick={() => onDraft(file.value)} disabled={busy !== null}>
            Bỏ thay đổi
          </button>
        )}
        {file.origin === "db" && (
          <button type="button" className="btn lg danger" onClick={reset} disabled={busy !== null}>
            {busy === "reset" ? "Đang khôi phục…" : "Về bản trong file"}
          </button>
        )}
      </div>
    </div>
  );
}

export function SettingsView() {
  const { data, error, loading, reload, setData } = useApi<SettingFile[]>("settings");
  const [active, setActive] = useState<string>("keywords.txt");
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const files = data ?? [];
  const current = files.find((f) => f.name === active) ?? files[0];
  const draftOf = (f: SettingFile) => drafts[f.name] ?? f.value;
  const anyDirty = files.some((f) => draftOf(f) !== f.value);

  useEffect(() => {
    if (!anyDirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [anyDirty]);

  function onKeyDown(e: React.KeyboardEvent, index: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = files[(index + (e.key === "ArrowRight" ? 1 : files.length - 1)) % files.length];
    setActive(next.name);
    document.getElementById(`tab-${next.name}`)?.focus();
  }

  return (
    <>
      <div className="top">
        <div>
          <h1>Cài đặt</h1>
          <p>Nguồn, từ khóa, chủ đề quan tâm và thuật ngữ. Bản lưu ở đây nằm trong DB và thay cho file trong thư mục config.</p>
        </div>
      </div>
      <div className="panel">
        {error && <ErrorBox error={error} onRetry={() => reload()} />}
        {loading && !data && <Loading />}
        {current && (
          <>
            <div className="tabs" role="tablist" aria-label="File cấu hình">
              {files.map((f, i) => (
                <button
                  key={f.name}
                  id={`tab-${f.name}`}
                  type="button"
                  role="tab"
                  aria-selected={f.name === current.name}
                  aria-controls={`panel-${f.name}`}
                  tabIndex={f.name === current.name ? 0 : -1}
                  onClick={() => setActive(f.name)}
                  onKeyDown={(e) => onKeyDown(e, i)}
                >
                  {f.name}
                  {draftOf(f) !== f.value && (
                    <span className="dirty" aria-label="chưa lưu">
                      •
                    </span>
                  )}
                </button>
              ))}
            </div>
            <Editor
              file={current}
              draft={draftOf(current)}
              onDraft={(v) => setDrafts((d) => ({ ...d, [current.name]: v }))}
              onSaved={(saved) => {
                setData((list) => list?.map((f) => (f.name === saved.name ? saved : f)));
                setDrafts((d) => {
                  const next = { ...d };
                  delete next[saved.name];
                  return next;
                });
              }}
            />
          </>
        )}
      </div>
    </>
  );
}
