"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
} from "react";

export type CrmCompany = "energy" | "lights";

const STORAGE_KEY = "lumi-crm-company";

type CompanyContextValue = {
  company: CrmCompany;
  ready: boolean;
  setCompany: (company: CrmCompany) => void;
};

const CompanyContext = createContext<CompanyContextValue>({
  company: "energy",
  ready: false,
  setCompany: () => {},
});

export function CompanyProvider({ children }: { children: React.ReactNode }) {
  const [company, setCompanyState] = useState<CrmCompany>("energy");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "lights" || saved === "energy") {
      setCompanyState(saved);
    }
    setReady(true);
  }, []);

  const setCompany = (next: CrmCompany) => {
    setCompanyState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  };

  return (
    <CompanyContext.Provider value={{ company, ready, setCompany }}>
      {children}
    </CompanyContext.Provider>
  );
}

export function useCompany() {
  return useContext(CompanyContext);
}
