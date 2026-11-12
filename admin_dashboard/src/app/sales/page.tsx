import { AppShell } from "@/components/AppShell";
import { SalesView } from "@/components/SalesView";

export default function SalesPage() {
  return (
    <AppShell active="sales">
      <SalesView />
    </AppShell>
  );
}
