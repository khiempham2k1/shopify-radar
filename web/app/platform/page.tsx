import type { Metadata } from "next";
import { PlatformView } from "@/components/views/PlatformView";

export const metadata: Metadata = { title: "Thay đổi nền tảng" };

export default function Page() {
  return <PlatformView />;
}
