import type { Metadata } from "next";
import { FeedView } from "@/components/views/FeedView";

export const metadata: Metadata = { title: "Feed" };

export default function Page() {
  return <FeedView />;
}
