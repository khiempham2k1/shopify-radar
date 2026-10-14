import type { Metadata } from "next";
import { SettingsView } from "@/components/views/SettingsView";

export const metadata: Metadata = { title: "Cài đặt" };

export default function Page() {
  return <SettingsView />;
}
