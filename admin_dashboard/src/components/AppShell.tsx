"use client";

import Link from "next/link";
import { CompanyProvider, useCompany, type CrmCompany } from "@/lib/company";
import { useIsMobile } from "@/lib/useIsMobile";

type Props = {
  active: "messages" | "calls" | "sales";
};

export function AppShell({ active, children }: Props & { children: React.ReactNode }) {
  return (
    <CompanyProvider>
      <AppShellFrame active={active}>{children}</AppShellFrame>
    </CompanyProvider>
  );
}

function AppShellFrame({ active, children }: Props & { children: React.ReactNode }) {
  const isMobile = useIsMobile(640);
  const { company, setCompany } = useCompany();

  return (
    <div className="flex h-[100dvh] flex-col bg-lumi-bg text-gray-900 safe-pt safe-px">
      <header className="z-20 flex shrink-0 items-center gap-2 border-b border-lumi-border bg-white/95 px-3 py-2.5 backdrop-blur sm:justify-between sm:px-6 sm:py-3">
        <div className="flex min-w-0 items-center gap-2">
          <CompanySwitch company={company} onChange={setCompany} />
          {!isMobile ? (
            <span data-crm-label className="text-sm text-lumi-muted">
              CRM
            </span>
          ) : null}
        </div>
        <nav className="flex min-w-0 flex-1 gap-1 rounded-xl bg-lumi-bg p-1 sm:max-w-none sm:flex-none">
          <NavLink href="/calls" active={active === "calls"} mobile={isMobile}>
            Leads
          </NavLink>
          <NavLink href="/messages" active={active === "messages"} mobile={isMobile}>
            Inbox
          </NavLink>
          <NavLink href="/sales" active={active === "sales"} mobile={isMobile}>
            Sales
          </NavLink>
        </nav>
      </header>
      <main className="min-h-0 flex-1">{children}</main>
    </div>
  );
}

function CompanySwitch({
  company,
  onChange,
}: {
  company: CrmCompany;
  onChange: (company: CrmCompany) => void;
}) {
  return (
    <div className="flex shrink-0 rounded-lg bg-lumi-bg p-0.5">
      <CompanyButton
        label="Energy"
        selected={company === "energy"}
        onClick={() => onChange("energy")}
      />
      <CompanyButton
        label="Lights"
        selected={company === "lights"}
        onClick={() => onChange("lights")}
      />
    </div>
  );
}

function CompanyButton({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-2.5 py-1.5 text-sm font-semibold sm:px-3 ${
        selected ? "bg-white text-lumi-blue shadow-sm" : "text-lumi-muted"
      }`}
    >
      {label}
    </button>
  );
}

function NavLink({
  href,
  active,
  mobile,
  children,
}: {
  href: string;
  active: boolean;
  mobile?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`${
        mobile ? "flex-1 text-center" : "shrink-0"
      } rounded-lg px-3 py-2 text-sm font-medium transition sm:px-4 ${
        active
          ? "bg-white text-lumi-blue shadow-sm"
          : "text-lumi-muted hover:text-gray-900"
      }`}
    >
      {children}
    </Link>
  );
}
