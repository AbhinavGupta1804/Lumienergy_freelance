import Link from "next/link";

type Props = {
  active: "messages" | "calls";
};

export function AppShell({ active, children }: Props & { children: React.ReactNode }) {
  return (
    <div className="flex h-screen flex-col bg-lumi-bg text-gray-900">
      <header className="flex shrink-0 items-center justify-between border-b border-lumi-border bg-white px-6 py-3">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-bold">Lumi Energy</span>
          <span className="text-sm text-lumi-muted">Admin</span>
        </div>
        <nav className="flex gap-1 rounded-lg bg-lumi-bg p-1">
          <NavLink href="/messages" active={active === "messages"}>
            Messages
          </NavLink>
          <NavLink href="/calls" active={active === "calls"}>
            Calls
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
      className={`rounded-md px-4 py-2 text-sm font-medium transition ${
        active
          ? "bg-white text-lumi-blue shadow-sm"
          : "text-lumi-muted hover:text-gray-900"
      }`}
    >
      {children}
    </Link>
  );
}
