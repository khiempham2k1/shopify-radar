import type { Metadata } from "next";
import { UsageView } from "@/components/views/UsageView";

export const metadata: Metadata = { title: "Chi phí AI" };

export default function Page() {
  return <UsageView />;
}
