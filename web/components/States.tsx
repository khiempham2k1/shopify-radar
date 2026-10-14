"use client";

export function Loading({ text = "Đang tải dữ liệu…" }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {text}
    </div>
  );
}

export function ErrorBox({ error, onRetry, prefix = "Không tải được dữ liệu" }: { error: string; onRetry?: () => void; prefix?: string }) {
  return (
    <div className="error-box" role="alert">
      <span>
        <b>{prefix}.</b> {error}
      </span>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}
