import type { Metadata, Viewport } from "next";
import { Providers } from "@/components/Providers";
import { Shell } from "@/components/Shell";
import { authDisabled, canSeePhase2, currentUserEmail } from "@/lib/auth";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Shopify Radar", template: "%s · Shopify Radar" },
  description: "Dashboard nội bộ theo dõi thay đổi nền tảng Shopify và thảo luận của merchant.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F3F5F9" },
    { media: "(prefers-color-scheme: dark)", color: "#0E131B" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const email = await currentUserEmail();
  return (
    <html lang="vi">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font -- fonts load from Google with system fallbacks; next/font needs network at build time */}
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" />
      </head>
      <body>
        <Providers email={email ?? ""} authDisabled={authDisabled()} phase2={canSeePhase2(email)}>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
