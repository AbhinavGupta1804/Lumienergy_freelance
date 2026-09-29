import Link from "next/link";

type Props = {
  active: "messages" | "calls";
};

export function AppShell({ active, children }: Props & { children: React.ReactNode }) {
  return (
    <div className="flex h-[100dvh] flex-col bg-lumi-bg text-gray-900 safe-pt safe-px">
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-lumi-border bg-white px-3 py-2.5 sm:px-6 sm:py-3">
        <div className="min-w-0 flex items-baseline gap-2 sm:gap-3">
          <span className="truncate text-base font-bold sm:text-lg">Lumi Energy</span>
          <span className="hidden text-sm text-lumi-muted sm:inline">CRM</span>
        </div>
        <nav className="flex shrink-0 gap-1 rounded-lg bg-lumi-bg p-1">
          <NavLink href="/calls" active={active === "calls"}>
            Leads
          </NavLink>
          <NavLink href="/messages" active={active === "messages"}>
            Inbox
          </NavLink>
        </nav>
      </header>
      <main className="min-h-0 flex-1">{children}</main>
    </div>
  );
}

function NavLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`rounded-md px-3 py-2 text-sm font-medium transition sm:px-4 ${
        active
          ? "bg-white text-lumi-blue shadow-sm"
          : "text-lumi-muted hover:text-gray-900"
      }`}
    >
      {children}
    </Link>
  );
}
