import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const STORAGE_KEY = "privacy-masked";

interface PrivacyContextValue {
  masked: boolean;
  toggle: () => void;
}

const PrivacyContext = createContext<PrivacyContextValue | null>(null);

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [masked, setMasked] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, masked ? "1" : "0");
    } catch {
      // Best-effort persistence — a private window or blocked storage just
      // means the toggle resets next launch, nothing more.
    }
  }, [masked]);

  return (
    <PrivacyContext.Provider value={{ masked, toggle: () => setMasked((m) => !m) }}>
      {children}
    </PrivacyContext.Provider>
  );
}

export function usePrivacy(): PrivacyContextValue {
  const ctx = useContext(PrivacyContext);
  if (!ctx) throw new Error("usePrivacy must be used within a PrivacyProvider");
  return ctx;
}
