import type { NextAuthOptions } from "next-auth";
import { getServerSession } from "next-auth";
import GoogleProvider from "next-auth/providers/google";

export const DEV_USER = "dev@local";

export function authDisabled(): boolean {
  return (process.env.AUTH_DISABLED ?? "").trim().toLowerCase() === "true";
}

export function allowedDomains(): string[] {
  return (process.env.ALLOWED_EMAIL_DOMAINS ?? "")
    .split(",")
    .map((d) => d.trim().toLowerCase().replace(/^@/, ""))
    .filter(Boolean);
}

export function emailAllowed(email: string | null | undefined): boolean {
  if (!email) return false;
  const domain = email.trim().toLowerCase().split("@").pop();
  const allowed = allowedDomains();
  return Boolean(domain) && allowed.includes(domain as string);
}

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  session: { strategy: "jwt", maxAge: 30 * 24 * 60 * 60 },
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
    }),
  ],
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async signIn({ user, account, profile }) {
      if (account?.provider !== "google") return false;
      const verified = (profile as { email_verified?: boolean } | undefined)?.email_verified;
      if (verified === false) return false;
      return emailAllowed(user.email ?? profile?.email);
    },
  },
};

/** Email of the signed-in person, `dev@local` when AUTH_DISABLED=true, otherwise null. */
export async function currentUserEmail(): Promise<string | null> {
  if (authDisabled()) return DEV_USER;
  const session = await getServerSession(authOptions);
  const email = session?.user?.email ?? null;
  // A session minted before the domain list changed must not keep working.
  return email && emailAllowed(email) ? email : null;
}
