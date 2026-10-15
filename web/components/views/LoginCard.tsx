"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";
import { Logo } from "../Logo";

const ERRORS: Record<string, string> = {
  AccessDenied: "Tài khoản này không có quyền quản trị.",
  OAuthSignin: "Không mở được trang đăng nhập Google. Thử lại sau.",
  OAuthCallback: "Google trả về lỗi khi đăng nhập. Thử lại sau.",
  Configuration: "Máy chủ chưa cấu hình đăng nhập. Báo cho người quản trị.",
  SessionRequired: "Cần đăng nhập để xem trang này.",
  CredentialsSignin: "Email hoặc mật khẩu không đúng.",
  Locked: "Sai mật khẩu quá nhiều lần. Thử lại sau 15 phút.",
};

type Methods = { google: boolean; password: boolean };

export function LoginCard({ callbackUrl, error, methods }: { callbackUrl: string; error: string | null; methods: Methods }) {
  const [busy, setBusy] = useState<"" | "google" | "password">("");
  const [message, setMessage] = useState<string | null>(error);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  async function submitPassword(event: React.FormEvent) {
    event.preventDefault();
    setBusy("password");
    setMessage(null);
    const result = await signIn("password", { email, password, callbackUrl, redirect: false });
    if (result?.ok && !result.error) {
      window.location.href = result.url ?? callbackUrl;
      return;
    }
    setBusy("");
    setMessage(result?.error ?? "CredentialsSignin");
  }

  return (
    <div className="login">
      <div className="panel">
        <div className="brand">
          <Logo />
          Shopify Radar
        </div>
        <h1>Đăng nhập</h1>
        <p>Chỉ dành cho quản trị Shopify Radar.</p>
        {message && (
          <div className="error-box" role="alert">
            <span>{ERRORS[message] ?? "Đăng nhập không thành công. Thử lại."}</span>
          </div>
        )}
        {methods.password && (
          <form className="login-form" onSubmit={submitPassword}>
            <input
              className="field"
              type="email"
              autoComplete="username"
              placeholder="Email quản trị"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              className="field"
              type="password"
              autoComplete="current-password"
              placeholder="Mật khẩu"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button type="submit" className="btn primary lg" disabled={busy !== ""}>
              {busy === "password" ? "Đang đăng nhập…" : "Đăng nhập"}
            </button>
          </form>
        )}
        {methods.google && (
          <button
            type="button"
            className={methods.password ? "btn lg" : "btn primary lg"}
            disabled={busy !== ""}
            onClick={() => {
              setBusy("google");
              signIn("google", { callbackUrl });
            }}
          >
            {busy === "google" ? "Đang chuyển tới Google…" : "Đăng nhập bằng Google"}
          </button>
        )}
        {!methods.google && !methods.password && (
          <div className="error-box" role="alert">
            <span>{ERRORS.Configuration}</span>
          </div>
        )}
      </div>
    </div>
  );
}
