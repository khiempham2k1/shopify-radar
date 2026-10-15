import { NextResponse, type NextRequest } from "next/server";
import { getToken } from "next-auth/jwt";
import { authDisabled, canSeePhase2, emailAllowed, isPhase2Page } from "@/lib/access";

/** Phase 1 pages are open; Phase 2 pages need an account in PHASE2_EMAILS. API calls are checked in the proxy. */
export async function middleware(req: NextRequest) {
  if (authDisabled() || !isPhase2Page(req.nextUrl.pathname)) return NextResponse.next();

  const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
  const email = token && emailAllowed(token.email) ? (token.email as string) : null;
  if (email && canSeePhase2(email)) return NextResponse.next();

  // Behind a reverse proxy req.url carries the internal host (e.g. localhost:3000), so build the
  // redirect from the public URL: NEXTAUTH_URL, else the forwarded/Host headers.
  const host = req.headers.get("x-forwarded-host") || req.headers.get("host");
  const proto = req.headers.get("x-forwarded-proto") || req.nextUrl.protocol.replace(/:$/, "");
  const base = process.env.NEXTAUTH_URL || (host ? `${proto}://${host}` : req.url);
  if (email) {
    // Signed in but not on the Phase 2 list.
    const home = new URL("/", base);
    home.searchParams.set("denied", "phase2");
    return NextResponse.redirect(home);
  }
  const login = new URL("/login", base);
  login.searchParams.set("callbackUrl", req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/reports/:path*", "/settings/:path*", "/usage/:path*"],
};
