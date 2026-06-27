import { AppShell } from "@/components/AppShell";
import { CallsView } from "@/components/CallsView";

export default function CallsPage() {
  return (
    <AppShell active="calls">
      <CallsView />
    </AppShell>
  );
}
