"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { useEffect } from "react";
import { useApi } from "@/lib/api";
import type { Overview } from "@/lib/types";
import { Logo } from "./Logo";
import { CHANGED_EVENT, useUser } from "./Providers";

const PHASE_1 = [
  { href: "/", label: "Tổng quan" },
  { href: "/platform", label: "Thay đổi nền tảng" },
  { href: "/feed", label: "Feed" },
  { href: "/community", label: "Thảo luận cộng đồng" },
  { href: "/health", label: "Sức khỏe nguồn" },
];
const PHASE_2 = [
  { href: "/reports", label: "Báo cáo tuần" },
  { href: "/settings", label: "Cài đặt" },
  { href: "/usage", label: "Chi phí AI" },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");
}

export function Nav() {
  const pathname = usePathname() || "/";
  const { email, authDisabled, phase2 } = useUser();
  const overview = useApi<Overview>("overview");
  const { reload } = overview;
  const todo = overview.data?.kpis.todo;

  useEffect(() => {
    const onChange = () => reload({ silent: true });
    window.addEventListener(CHANGED_EVENT, onChange);
    return () => window.removeEventListener(CHANGED_EVENT, onChange);
  }, [reload]);

  return (
    <aside className="rail">
      <Link href="/" className="brand">
        <Logo />
        Shopify Radar
      </Link>
      <nav className="nav" aria-label="Màn hình">
        <div className="nav-label">Giai đoạn 1</div>
        {PHASE_1.map((l) => (
          <Link key={l.href} href={l.href} aria-current={isActive(pathname, l.href) ? "page" : undefined}>
            {l.label}
            {l.href === "/" && todo ? (
              <span className="count" title={`${todo} việc cần xử lý`}>
                {todo}
              </span>
            ) : null}
          </Link>
        ))}
        {/* Phase 2 is only for accounts listed in PHASE2_EMAILS; the middleware and API proxy enforce it too. */}
        {phase2 && (
          <>
            <div className="nav-label">Giai đoạn 2</div>
            {PHASE_2.map((l) => (
              <Link key={l.href} href={l.href} aria-current={isActive(pathname, l.href) ? "page" : undefined}>
                {l.label} <span className="phase">GĐ 2</span>
              </Link>
            ))}
          </>
        )}
      </nav>
      {/* Visitors read without an account and see no sign-in link; admins open /login directly. */}
      {(authDisabled || email) && (
        <div className="user">
          <span className="email" title={email}>
            {email}
          </span>
          {authDisabled ? (
            <span>Chế độ dev · không đăng nhập</span>
          ) : (
            <button type="button" className="linklike" onClick={() => signOut({ callbackUrl: "/" })}>
              Đăng xuất
            </button>
          )}
        </div>
      )}
    </aside>
  );
}
