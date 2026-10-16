import { google } from "./theme";

/** Tableau 10, in its original order. Blue and red double as Status's
 * applied/rejected colors elsewhere in the app — a deliberate overlap, kept
 * for consistency rather than reshuffled to avoid it. */
export const TABLEAU10 = {
  blue: "#4e79a7",
  orange: "#f28e2b",
  red: "#e15759",
  teal: "#76b7b2",
  green: "#59a14f",
  yellow: "#edc948",
  purple: "#b07aa1",
  pink: "#ff9da7",
  brown: "#9c755f",
  gray: "#bab0ac",
} as const;

/** Text colour picked per hex by YIQ brightness (>=128 -> dark text).
 *
 * Four categories now, not six: Product Marketing merged into Marketing,
 * Product Strategy & Ops merged into Product Manager, AI Strategy renamed to
 * Strategy. Colors are Tableau 10's first four, in role order — Data
 * Analyst's red doubles as Status's rejected color, the same kind of
 * overlap already accepted for Product Manager's blue. */
export const ROLE_COLORS: Record<string, { color: string; textColor?: string }> = {
  "Product Manager": { color: TABLEAU10.blue },
  Strategy: { color: TABLEAU10.orange, textColor: google.textPrimary },
  "Data Analyst": { color: TABLEAU10.red },
  Marketing: { color: TABLEAU10.teal, textColor: google.textPrimary },
};

/** For applications with no role assigned yet. */
export const UNASSIGNED_COLOR = { color: google.border, textColor: google.textPrimary };
