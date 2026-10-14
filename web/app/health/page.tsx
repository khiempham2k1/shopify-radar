import type { Metadata } from "next";
import { HealthView } from "@/components/views/HealthView";

export const metadata: Metadata = { title: "Sức khỏe nguồn" };

export default function Page() {
  return <HealthView />;
}
