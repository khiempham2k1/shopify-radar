import { createHash, timingSafeEqual } from "node:crypto";
import type { NextAuthOptions } from "next-auth";
import { getServerSession } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";

import { authDisabled, emailAllowed } from "./access";

export { authDisabled, canSeePhase2, emailAllowed, phase2Emails } from "./access";

export const DEV_USER = "dev@local";

/** Sign-in methods the server offers: Google when a client is configured, a password when ADMIN_PASSWORD is set. */
export function loginMethods(): { google: boolean; password: boolean } {
  return {
    google: Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET),
    password: Boolean(process.env.ADMIN_PASSWORD),
  };
}

function digest(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest();
}

// Failed password attempts per email: after MAX_FAILS within LOCK_MS, refuse for the rest of the window.
const MAX_FAILS = 10;
const LOCK_MS = 15 * 60 * 1000;
const failures = new Map<string, { count: number; since: number }>();

function locked(email: string): boolean {
  const entry = failures.get(email);
  if (!entry) return false;
  if (Date.now() - entry.since > LOCK_MS) {
    failures.delete(email);
    return false;
  }
  return entry.count >= MAX_FAILS;
}

function recordFailure(email: string): void {
  const entry = failures.get(email);
  if (!entry || Date.now() - entry.since > LOCK_MS) failures.set(email, { count: 1, since: Date.now() });
  else entry.count += 1;
}

/** Admin email + ADMIN_PASSWORD. For servers reached by IP, where Google sign-in cannot redirect back. */
async function checkPassword(credentials: Record<string, string> | undefined) {
  const expected = process.env.ADMIN_PASSWORD ?? "";
  const email = (credentials?.email ?? "").trim().toLowerCase();
  const password = credentials?.password ?? "";
  if (!expected || !emailAllowed(email)) return null;
  if (locked(email)) throw new Error("Locked");
  if (timingSafeEqual(digest(password), digest(expected))) {
    failures.delete(email);
    return { id: email, email, name: email };
  }
  recordFailure(email);
  await new Promise((resolve) => setTimeout(resolve, 1500));
  return null;
}

const providers: NextAuthOptions["providers"] = [];
if (loginMethods().google) {
  providers.push(
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
    }),
  );
}
if (loginMethods().password) {
  providers.push(
    CredentialsProvider({
      id: "password",
      name: "Mật khẩu",
      credentials: { email: { type: "email" }, password: { type: "password" } },
      authorize: (credentials) => checkPassword(credentials),
    }),
  );
}

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  session: { strategy: "jwt", maxAge: 30 * 24 * 60 * 60 },
  providers,
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async signIn({ user, account, profile }) {
      if (account?.provider === "password") return emailAllowed(user.email);
      if (account?.provider !== "google") return false;
      const verified = (profile as { email_verified?: boolean } | undefined)?.email_verified;
      if (verified === false) return false;
      return emailAllowed(user.email ?? profile?.email);
    },
  },
};

/** Email of the signed-in person, `dev@local` when AUTH_DISABLED=true, otherwise null (not signed in). */
export async function currentUserEmail(): Promise<string | null> {
  if (authDisabled()) return DEV_USER;
  const session = await getServerSession(authOptions);
  const email = session?.user?.email ?? null;
  // A session minted before the domain list changed must not keep working.
  return email && emailAllowed(email) ? email : null;
}
