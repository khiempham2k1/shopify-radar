"use client";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="error-box" role="alert">
      <span>
        <b>Trang gặp lỗi.</b> {error.message || "Đã có lỗi không mong muốn."}
      </span>
      <button type="button" className="btn" onClick={reset}>
        Thử lại
      </button>
    </div>
  );
}
