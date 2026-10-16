import { useEffect, useState } from "react";
import { Box, CircularProgress, Stack, Typography } from "@mui/material";
import { getSimilarApplications } from "../api";
import type { SimilarApplication, SimilarApplicationsResponse } from "../types";
import { ROUND_LABELS } from "../types";
import { google } from "../theme";

interface Props {
  source: string;
  jobId: string;
}

function outcomeColor(status: string): string | undefined {
  if (status === "rejected") return google.red;
  if (status === "offer" || status === "accepted") return google.green;
  return undefined;
}

// A sign prefix makes it visible at a glance that this is a deviation from
// average (a z-score), not a 0-1 similarity fraction like the raw cosine
// values these replaced.
function formatScore(score: number): string {
  return (score >= 0 ? "+" : "") + score.toFixed(2);
}

function MatchRow({ match, rank }: { match: SimilarApplication; rank: number }) {
  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: "baseline", py: 0.25 }}>
      <Typography variant="body2" sx={{ width: 20, color: google.textSecondary, flexShrink: 0 }}>
        {rank}.
      </Typography>
      <Typography variant="body2" sx={{ width: 56, flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>
        {formatScore(match.score)}
      </Typography>
      <Typography variant="body2" sx={{ flexGrow: 1 }}>
        {match.company} / {match.title}
      </Typography>
      <Typography
        variant="body2"
        sx={{ color: outcomeColor(match.status) ?? google.textSecondary, whiteSpace: "nowrap" }}
      >
        {match.highest_round ? ROUND_LABELS[match.highest_round] ?? match.highest_round : match.status}
      </Typography>
    </Stack>
  );
}

function MatchList({ title, matches }: { title: string; matches: SimilarApplication[] }) {
  return (
    <Box sx={{ flex: 1, minWidth: 280 }}>
      <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
        {title}
      </Typography>
      {matches.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No comparable past applications yet.
        </Typography>
      ) : (
        matches.map((match, i) => <MatchRow key={i} match={match} rank={i + 1} />)
      )}
    </Box>
  );
}

/** Only fetches once mounted — the parent's ExpandableTable unmounts this on
 * collapse, so it never runs for a row that has not actually been opened. */
export default function SimilarApplicationsPanel({ source, jobId }: Props) {
  const [data, setData] = useState<SimilarApplicationsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSimilarApplications(source, jobId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load");
      });
    return () => {
      cancelled = true;
    };
  }, [source, jobId]);

  if (error) {
    return (
      <Typography variant="body2" color="error">
        {error}
      </Typography>
    );
  }

  if (!data) {
    return <CircularProgress size={16} />;
  }

  return (
    <Box>
      <Stack direction="row" spacing={4} sx={{ flexWrap: "wrap" }}>
        <MatchList title="Overall" matches={data.overall} />
        <MatchList title="Similar by Responsibilities" matches={data.responsibilities} />
        <MatchList title="Similar by Qualifications" matches={data.qualifications} />
      </Stack>
      {data.thin_categories.length > 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          Limited history for {data.thin_categories.join(", ")} — matches in{" "}
          {data.thin_categories.length === 1 ? "that category" : "those categories"} are less reliable.
        </Typography>
      )}
    </Box>
  );
}
