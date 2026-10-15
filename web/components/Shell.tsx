"use client";

import { usePathname } from "next/navigation";
import { Nav } from "./Nav";

/** Sidebar layout everywhere except the login page, which stands alone. */
export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  if (pathname.startsWith("/login")) return <>{children}</>;
  return (
    <div className="shell">
      <Nav />
      <main id="main">{children}</main>
    </div>
  );
}
