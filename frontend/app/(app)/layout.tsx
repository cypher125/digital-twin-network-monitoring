import { AuthGate } from "@/components/AppShell";

export default function DashboardLayout({ children }: LayoutProps<"/">) {
  return <AuthGate>{children}</AuthGate>;
}
