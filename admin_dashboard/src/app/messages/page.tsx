import { AppShell } from "@/components/AppShell";
import { ChatLayout } from "@/components/ChatLayout";

export default function MessagesPage() {
  return (
    <AppShell active="messages">
      <ChatLayout />
    </AppShell>
  );
}
