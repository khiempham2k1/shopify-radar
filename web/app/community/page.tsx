import type { Metadata } from "next";
import { CommunityView } from "@/components/views/CommunityView";

export const metadata: Metadata = { title: "Thảo luận cộng đồng" };

export default function Page() {
  return <CommunityView />;
}
