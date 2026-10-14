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
  const login = new URL("/login", req.url);
  login.searchParams.set("callbackUrl", req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  // Everything except next-auth's own routes, the login page and static assets.
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
