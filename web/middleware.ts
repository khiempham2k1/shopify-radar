import { NextResponse, type NextRequest } from "next/server";
import { getToken } from "next-auth/jwt";

function allowed(email: unknown): boolean {
  if (typeof email !== "string" || !email.includes("@")) return false;
  const domains = (process.env.ALLOWED_EMAIL_DOMAINS ?? "")
    .split(",")
    .map((d) => d.trim().toLowerCase().replace(/^@/, ""))
    .filter(Boolean);
  return domains.includes(email.trim().toLowerCase().split("@").pop() ?? "");
}

export async function middleware(req: NextRequest) {
  if ((process.env.AUTH_DISABLED ?? "").trim().toLowerCase() === "true") return NextResponse.next();

  const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
  if (token && allowed(token.email)) return NextResponse.next();

  if (req.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "Chưa đăng nhập hoặc phiên đã hết hạn" }, { status: 401 });
  }
  // Behind a reverse proxy req.url carries the internal host (e.g. localhost:3000), so build the
  // redirect from the public URL: NEXTAUTH_URL, else the forwarded/Host headers.
  const host = req.headers.get("x-forwarded-host") || req.headers.get("host");
  const proto = req.headers.get("x-forwarded-proto") || req.nextUrl.protocol.replace(/:$/, "");
  const base = process.env.NEXTAUTH_URL || (host ? `${proto}://${host}` : req.url);
  const login = new URL("/login", base);
  login.searchParams.set("callbackUrl", req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  // Everything except next-auth's own routes, the login page and static assets.
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
