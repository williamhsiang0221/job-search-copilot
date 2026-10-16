import { useCallback, useEffect, useState } from "react";
import { Alert, Box, Button, Chip, CircularProgress, Stack, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import StickyNote2OutlinedIcon from "@mui/icons-material/StickyNote2Outlined";
import ExpandableTable, { type ColumnDef } from "./ExpandableTable";
import VerdictChip from "./VerdictChip";
import EvaluationDetail, { GATE_LABELS, score } from "./EvaluationDetail";
import EvaluationNote from "./EvaluationNote";
import PromptTab from "./PromptTab";
import { getEvaluations } from "../api";
import type { Evaluation } from "../types";
import { google } from "../theme";
import { parseIsoDate } from "../dates";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const date = parseIsoDate(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// The run-level facts a history of runs needs: which one is still current,
// what it cost, and which model produced it.
const historyColumns = (currentIds: Set<number>): ColumnDef<Evaluation>[] => [
  {
    id: "current",
    label: "Run",
    width: 92,
    nowrap: true,
    render: (e) =>
      currentIds.has(e.id) ? (
        <Chip size="small" variant="outlined" label="current" sx={{ height: 20, fontSize: "0.7rem" }} />
      ) : (
        <Typography variant="caption" sx={{ color: google.border }}>
          superseded
        </Typography>
      ),
  },
  {
    id: "verdict",
    label: "Verdict",
    width: 100,
    nowrap: true,
    render: (e) => <VerdictChip verdict={e.verdict} />,
  },
  {
    id: "note",
    label: "Note",
    width: 56,
    render: (e) =>
      e.note ? (
        <StickyNote2OutlinedIcon fontSize="small" titleAccess={e.note} sx={{ color: google.textSecondary }} />
      ) : null,
  },
  { id: "company", label: "Company", render: (e) => e.company },
  { id: "title", label: "Title", render: (e) => e.title },
  { id: "score_1", label: "Score 1", render: (e) => score(e.score_1), nowrap: true },
  { id: "score_2", label: "Score 2", render: (e) => score(e.score_2), nowrap: true },
  {
    id: "disqualifier",
    label: "Gate",
    render: (e) =>
      e.disqualifier ? (
        <Typography variant="caption" sx={{ color: google.red }}>
          {GATE_LABELS[e.disqualifier] ?? e.disqualifier}
        </Typography>
      ) : (
        <Box component="span" sx={{ color: google.border }}>
          —
        </Box>
      ),
  },
  { id: "rubric_version", label: "Rubric", render: (e) => e.rubric_version, nowrap: true },
  { id: "created_at", label: "Evaluated", render: (e) => formatDate(e.created_at), nowrap: true },
  { id: "model", label: "Model", render: (e) => e.model || "—", nowrap: true },
  {
    id: "cost_usd",
    label: "Cost",
    nowrap: true,
    render: (e) =>
      e.cost_usd === null ? (
        <Box component="span" sx={{ color: google.border }}>
          —
        </Box>
      ) : (
        `$${e.cost_usd.toFixed(4)}`
      ),
  },
];

const HEADINGS: Record<string, { title: string; blurb: string }> = {
  history: {
    title: "History",
    blurb:
      "Every run ever made, including superseded ones. Sub-scores move between runs, so this is where you check whether a verdict is stable before trusting it.",
  },
  prompt: {
    title: "Prompt",
    blurb: "The rubric verbatim. When a verdict looks wrong, this is what settles it.",
  },
};

interface Props {
  sub: "history" | "prompt";
}

/** Latest run per job — what a verdict "is" right now, for the Run column. */
function latestPerJob(rows: Evaluation[]): Evaluation[] {
  const seen = new Set<string>();
  // rows arrive newest-first, so the first sighting of a job is its latest run.
  return rows.filter((e) => {
    const key = `${e.source}:${e.job_id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export default function EvaluationsView({ sub }: Props) {
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEvaluations(await getEvaluations());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load evaluations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const currentIds = new Set(latestPerJob(evaluations).map((e) => e.id));

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        {HEADINGS[sub]?.title ?? "Evaluations"}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {HEADINGS[sub]?.blurb ?? ""}
      </Typography>

      {sub !== "prompt" && (
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 2, flexWrap: "wrap" }}>
        <Button
          size="small"
          startIcon={loading ? <CircularProgress size={14} /> : <RefreshIcon />}
          onClick={() => void load()}
          disabled={loading}
        >
          Refresh
        </Button>
        <Chip
          size="small"
          variant="outlined"
          label={`${evaluations.length} runs on ${currentIds.size} roles`}
        />
      </Stack>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {sub === "prompt" ? (
        <PromptTab kind="evaluator" />
      ) : evaluations.length === 0 && !loading ? (
        <Alert severity="info" sx={{ borderRadius: 2 }}>
          Nothing evaluated yet. Fetch some job descriptions first, then run the evaluator.
        </Alert>
      ) : (
        <ExpandableTable
          rows={evaluations}
          columns={historyColumns(currentIds)}
          rowKey={(e) => String(e.id)}
          minWidth={1100}
          expanded={(evaluation) => (
            <>
              <EvaluationDetail evaluation={evaluation} />
              <EvaluationNote
                evaluation={evaluation}
                onSaved={(saved) =>
                  setEvaluations((rows) => rows.map((row) => (row.id === saved.id ? { ...row, ...saved } : row)))
                }
              />
            </>
          )}
        />
      )}
    </Box>
  );
}
