import { Chip } from "@mui/material";
import type { Verdict } from "../types";
import { google } from "../theme";

// SKIP is the only verdict the candidate acts on without looking, so it is the
// only one that needs to stand out. MAYBE and APPLY both end with them reading.
const VERDICT_COLOR: Record<string, string> = {
  APPLY: google.green,
  MAYBE: google.yellow,
  SKIP: google.border,
};

// Fixed width so APPLY/MAYBE/SKIP render as the same size chip regardless of
// label length, instead of each hugging its own text.
export default function VerdictChip({ verdict }: { verdict: Verdict | string }) {
  return (
    <Chip
      size="small"
      label={verdict}
      sx={{
        width: 72,
        fontWeight: 600,
        backgroundColor: VERDICT_COLOR[verdict] ?? google.border,
        color: verdict === "SKIP" ? "text.secondary" : "#fff",
      }}
    />
  );
}
