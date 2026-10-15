import { NextRequest, NextResponse } from "next/server";
import { canSeePhase2, currentUserEmail } from "@/lib/auth";
import { isPhase2Api } from "@/lib/access";

export const dynamic = "force-dynamic";
// Weekly reports are written by Claude and can take a few minutes.
export const maxDuration = 300;

type Context = { params: Promise<{ path: string[] }> };

function apiBase(): string {
  return (process.env.RADAR_API_URL || "http://localhost:8000").replace(/\/+$/, "");
}

async function proxy(req: NextRequest, ctx: Context): Promise<NextResponse> {
  const email = await currentUserEmail();
  const { path = [] } = await ctx.params;
  if (path.length === 0 || path.some((p) => p === "" || p === "." || p === "..")) {
    return NextResponse.json({ detail: "Đường dẫn không hợp lệ" }, { status: 400 });
  }
  // Phase 1 is readable without signing in; changes and Phase 2 need an account.
  if (isPhase2Api(path) && !canSeePhase2(email)) {
    return email
      ? NextResponse.json({ detail: "Tài khoản này không được xem Giai đoạn 2" }, { status: 403 })
      : NextResponse.json({ detail: "Cần đăng nhập để xem Giai đoạn 2" }, { status: 401 });
  }
  if (!email && req.method !== "GET" && req.method !== "HEAD") {
    return NextResponse.json({ detail: "Cần đăng nhập để thay đổi dữ liệu" }, { status: 401 });
  }
  const target = `${apiBase()}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers({ Accept: "application/json", "X-Radar-User": email ?? "anonymous" });
  const token = process.env.RADAR_API_TOKEN;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let body: string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.text();
    if (body) headers.set("Content-Type", req.headers.get("content-type") || "application/json");
    else body = undefined;
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(maxDuration * 1000),
    });
  } catch (err) {
    const reason = err instanceof Error && err.name === "TimeoutError" ? "API phản hồi quá lâu" : "Không kết nối được tới API";
    console.error(`[radar-proxy] ${req.method} ${target}:`, err);
    return NextResponse.json({ detail: reason }, { status: 502 });
  }

  const text = await upstream.text();
  const contentType = upstream.headers.get("content-type") || "application/json";
  if (!upstream.ok && !contentType.includes("json")) {
    return NextResponse.json({ detail: `API lỗi ${upstream.status}: ${text.slice(0, 300)}` }, { status: upstream.status });
  }
  return new NextResponse(text || null, {
    status: upstream.status,
    headers: { "Content-Type": contentType, "Cache-Control": "no-store" },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
