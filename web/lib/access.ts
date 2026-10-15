/**
 * Who may see what. Plain functions with no next-auth imports, so the Edge
 * middleware, the API proxy and server components share one set of rules.
 *
 * - Phase 1 pages (Tổng quan, Thay đổi nền tảng, Feed, Sức khỏe nguồn) are
 *   readable without signing in. Changing anything needs a signed-in account.
 * - Only admins sign in (Google, or ADMIN_PASSWORD): the accounts listed in PHASE2_EMAILS. They open /login
 *   directly (there is no link for visitors) and get Phase 2 (Báo cáo tuần,
 *   Cài đặt, Chi phí AI) and the technical details.
 */

export const PHASE2_PAGES = ["/reports", "/settings", "/usage"];
export const PHASE2_API = ["reports", "settings", "usage"];

function list(value: string | undefined): string[] {
  return (value ?? "")
    .split(",")
    .map((v) => v.trim().toLowerCase())
    .filter(Boolean);
}

export function authDisabled(): boolean {
  return (process.env.AUTH_DISABLED ?? "").trim().toLowerCase() === "true";
}

export function phase2Emails(): string[] {
  return list(process.env.PHASE2_EMAILS);
}

/** May sign in at all: only admins, the accounts named in PHASE2_EMAILS. */
export function emailAllowed(email: unknown): boolean {
  if (typeof email !== "string" || !email.includes("@")) return false;
  return phase2Emails().includes(email.trim().toLowerCase());
}

/** May open Phase 2. With AUTH_DISABLED (local development) everyone may. */
export function canSeePhase2(email: string | null | undefined): boolean {
  if (authDisabled()) return true;
  return Boolean(email) && emailAllowed(email) && phase2Emails().includes((email as string).trim().toLowerCase());
}

export function isPhase2Page(pathname: string): boolean {
  return PHASE2_PAGES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

export function isPhase2Api(path: string[]): boolean {
  return PHASE2_API.includes(path[0] ?? "");
}
