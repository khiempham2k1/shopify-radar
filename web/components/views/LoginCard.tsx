"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";
import { Logo } from "../Logo";

const ERRORS: Record<string, string> = {
  AccessDenied: "Tài khoản này không thuộc domain công ty và không có trong danh sách PHASE2_EMAILS.",
  OAuthSignin: "Không mở được trang đăng nhập Google. Thử lại sau.",
  OAuthCallback: "Google trả về lỗi khi đăng nhập. Thử lại sau.",
  Configuration: "Máy chủ chưa cấu hình đăng nhập Google. Báo cho người quản trị.",
  SessionRequired: "Cần đăng nhập để xem trang này.",
};

export function LoginCard({ callbackUrl, error, domains }: { callbackUrl: string; error: string | null; domains: string[] }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <div className="panel">
        <div className="brand">
          <Logo />
          Shopify Radar
        </div>
        <h1>Đăng nhập</h1>
        <p>
          Dashboard nội bộ. Dùng tài khoản Google công ty
          {domains.length > 0 && (
            <>
              {" "}
              (<span className="mono">{domains.map((d) => "@" + d).join(", ")}</span>)
            </>
          )}
          .
        </p>
        {error && (
          <div className="error-box" role="alert">
            <span>{ERRORS[error] ?? "Đăng nhập không thành công. Thử lại."}</span>
          </div>
        )}
        <button
          type="button"
          className="btn primary lg"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            signIn("google", { callbackUrl });
          }}
        >
          {busy ? "Đang chuyển tới Google…" : "Đăng nhập bằng Google"}
        </button>
      </div>
    </div>
  );
}
