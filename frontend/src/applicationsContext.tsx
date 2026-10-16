import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { getApplications, updateApplication } from "./api";
import { needsBackfill, type Application, type BackfillSummary } from "./types";

// Fallback freshness for "someone else changed it in another tab" — every
// page that actually needs current data also calls refresh() itself on
// mount, so this is a backstop, not the only thing keeping data current.
const POLL_MS = 30_000;

export type EditableField = "role" | "status" | "highest_round" | "applied_at" | "company" | "title";

interface ApplicationsContextValue {
  applications: Application[];
  summary: BackfillSummary | null;
  loading: boolean;
  error: string | null;
  saving: number | null;
  /** Re-fetches from the server. Call on mount from any page that needs current data. */
  refresh: () => Promise<void>;
  setField: <K extends EditableField>(row: Application, key: K, value: Application[K]) => Promise<void>;
  setReferral: (row: Application, referral: string) => Promise<void>;
}

const ApplicationsContext = createContext<ApplicationsContextValue | null>(null);

export function ApplicationsProvider({ children }: { children: ReactNode }) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [summary, setSummary] = useState<BackfillSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);
  // Loading only ever gates the very first fetch. Every later refresh — the
  // background poll, or a page's own on-mount refresh once data already
  // exists — swaps in new data silently, rather than flashing a spinner on
  // whichever page happens to be open every 30 seconds.
  const hasLoadedOnce = useRef(false);

  const refresh = useCallback(async () => {
    if (!hasLoadedOnce.current) setLoading(true);
    setError(null);
    try {
      const data = await getApplications();
      setApplications(data.applications);
      setSummary(data.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load applications");
    } finally {
      hasLoadedOnce.current = true;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  // Shared by every editable field, everywhere: update locally first —
  // waiting on a round trip per field is unusable when backfilling many rows
  // in a row — then persist, rolling back on failure. Only highest_round
  // re-pulls summary: it is the only field the response-rate stats are
  // computed from.
  async function setField<K extends EditableField>(row: Application, key: K, value: Application[K]) {
    setSaving(row.id);
    setError(null);
    const previous = row[key];

    setApplications((rs) => rs.map((r) => (r.id === row.id ? { ...r, [key]: value } : r)));
    try {
      await updateApplication(row.id, { [key]: value });
      if (key === "highest_round") {
        const data = await getApplications();
        setSummary(data.summary);
      }
    } catch (err) {
      setApplications((rs) => rs.map((r) => (r.id === row.id ? { ...r, [key]: previous } : r)));
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSaving(null);
    }
  }

  // Referral is free text, so it commits on blur rather than per keystroke —
  // a full reload on failure is simpler than tracking a pre-edit snapshot for
  // a low-stakes field. Still has to update local state on success, though:
  // Needs Backfill masked this bug because its card shows its own local text
  // state regardless, but All Applications' edit mode unmounts its text
  // field the instant edit mode closes and falls back to reading straight
  // from this array — so a save that never touched local state looked like
  // it silently failed, even though the server had it right the whole time.
  async function setReferral(row: Application, referral: string) {
    setSaving(row.id);
    setError(null);
    const value = referral || null;
    try {
      await updateApplication(row.id, { referral: value });
      setApplications((rs) => rs.map((r) => (r.id === row.id ? { ...r, referral: value } : r)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
      await refresh();
    } finally {
      setSaving(null);
    }
  }

  return (
    <ApplicationsContext.Provider
      value={{ applications, summary, loading, error, saving, refresh, setField, setReferral }}
    >
      {children}
    </ApplicationsContext.Provider>
  );
}

export function useApplicationsData(): ApplicationsContextValue {
  const ctx = useContext(ApplicationsContext);
  if (!ctx) throw new Error("useApplicationsData must be used within an ApplicationsProvider");
  return ctx;
}

/** Derived, not stored — every consumer computes it from the same shared list. */
export function useNeedsBackfillCount(): number {
  const { applications } = useApplicationsData();
  return applications.filter(needsBackfill).length;
}
