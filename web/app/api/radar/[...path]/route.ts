import { NextRequest, NextResponse } from "next/server";
import { currentUserEmail } from "@/lib/auth";

export const dynamic = "force-dynamic";
// Weekly reports are written by Claude and can take a few minutes.
export const maxDuration = 300;

type Context = { params: Promise<{ path: string[] }> };

function apiBase(): string {
  return (process.env.RADAR_API_URL || "http://localhost:8000").replace(/\/+$/, "");
}

async function proxy(req: NextRequest, ctx: Context): Promise<NextResponse> {
  const email = await currentUserEmail();
  if (!email) {
    return NextResponse.json({ detail: "Chưa đăng nhập hoặc phiên đã hết hạn" }, { status: 401 });
  }

  const { path = [] } = await ctx.params;
  if (path.length === 0 || path.some((p) => p === "" || p === "." || p === "..")) {
    return NextResponse.json({ detail: "Đường dẫn không hợp lệ" }, { status: 400 });
  }
  const target = `${apiBase()}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers({ Accept: "application/json", "X-Radar-User": email });
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
