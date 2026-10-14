import type { Metadata } from "next";
import { ReportView } from "@/components/views/ReportView";

export const metadata: Metadata = { title: "Báo cáo tuần" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReportView id={id} />;
}
