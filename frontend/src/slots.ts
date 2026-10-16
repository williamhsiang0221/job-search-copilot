import { useEffect, useState } from "react";

/** Human labels for resume section slots, from the profile's resume layout
 * (GET /api/resume-layout) rather than hardcoded here — the sections are the
 * candidate's own employers and schools. Fetched once and shared. */
let cache: Promise<Record<string, string>> | null = null;

function loadSlotLabels(): Promise<Record<string, string>> {
  cache ??= fetch("/api/resume-layout")
    .then((r) => (r.ok ? r.json() : { slots: [] }))
    .then((data: { slots: { slot: string; label: string }[] }) =>
      Object.fromEntries(data.slots.map((s) => [s.slot, s.label])),
    )
    .catch(() => {
      cache = null; // retry on the next mount
      return {};
    });
  return cache;
}

/** Slot -> label. Empty until loaded; callers fall back to the slot key. */
export function useSlotLabels(): Record<string, string> {
  const [labels, setLabels] = useState<Record<string, string>>({});
  useEffect(() => {
    let alive = true;
    void loadSlotLabels().then((l) => alive && setLabels(l));
    return () => {
      alive = false;
    };
  }, []);
  return labels;
}
