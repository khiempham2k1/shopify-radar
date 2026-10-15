import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { LoginCard } from "@/components/views/LoginCard";
import { authDisabled, currentUserEmail, loginMethods } from "@/lib/auth";

export const metadata: Metadata = { title: "Đăng nhập" };

function safeCallback(value: string | string[] | undefined): string {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.startsWith("/") && !v.startsWith("//") && !v.startsWith("/login") ? v : "/";
}

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const callbackUrl = safeCallback(params.callbackUrl);
  if (authDisabled() || (await currentUserEmail())) redirect(callbackUrl);
  const error = Array.isArray(params.error) ? params.error[0] : params.error;
  return <LoginCard callbackUrl={callbackUrl} error={error ?? null} methods={loginMethods()} />;
}
