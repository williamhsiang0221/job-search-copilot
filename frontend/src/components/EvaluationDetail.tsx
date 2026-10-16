import { Alert, Box, Typography } from "@mui/material";
import { SUBSCORE_LABELS, type Evaluation, type SubScore } from "../types";
import { google } from "../theme";

export const GATE_LABELS: Record<string, string> = {
  pm_years: "7+ yrs PM title required",
  salary_floor: "Salary upper bound under $140K",
  declining_bu: "Structurally declining business unit",
  pure_ic_research: "Pure IC research, no PM path",
  clearance: "Security clearance required",
};

export const score = (value: number | null) =>
  value === null ? (
    <Box component="span" sx={{ color: google.border }}>
      —
    </Box>
  ) : (
    value.toFixed(1)
  );

function SubScoreRow({ sub }: { sub: SubScore }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "180px 56px 56px 1fr",
        gap: 1,
        py: 0.5,
        alignItems: "baseline",
        borderBottom: `1px solid ${google.border}`,
      }}
    >
      <Typography variant="body2" sx={{ fontWeight: 500 }}>
        {SUBSCORE_LABELS[sub.code] ?? sub.code}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {Math.round(sub.weight * 100)}%
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {sub.abstained ? (
          <Box component="span" sx={{ color: google.border, fontWeight: 400 }}>
            n/a
          </Box>
        ) : (
          `${sub.score?.toFixed(0)}/10`
        )}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {sub.abstained ? "Not stated in the posting — excluded, not scored zero." : sub.rationale}
      </Typography>
    </Box>
  );
}

/** The gate, reasoning, both sub-score groups, and the cost/model footer for
 * one evaluation run. Shared by Evaluations' History tab and Normalized's
 * expanded row, so a change to how a verdict is explained only happens once. */
export default function EvaluationDetail({ evaluation }: { evaluation: Evaluation }) {
  const score1 = evaluation.scores.filter((s) => s.code.startsWith("4"));
  const score2 = evaluation.scores.filter((s) => s.code.startsWith("5"));
  const abstained = evaluation.scores.filter((s) => s.abstained);

  return (
    <Box>
      {evaluation.disqualifier && (
        <Alert severity="warning" sx={{ mb: 2, borderRadius: 2 }}>
          Gate fired: {GATE_LABELS[evaluation.disqualifier] ?? evaluation.disqualifier}. A gate
          forces SKIP regardless of the scores, because it fires on something the posting states.
        </Alert>
      )}

      <Typography variant="body2" sx={{ mb: 2 }}>
        {evaluation.reasoning || "No reasoning recorded."}
      </Typography>

      <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
        Score 1 — career aspiration fit: {score(evaluation.score_1)}
      </Typography>
      <Box sx={{ mb: 2 }}>
        {score1.map((s) => (
          <SubScoreRow key={s.code} sub={s} />
        ))}
      </Box>

      <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
        Score 2 — JD versus background: {score(evaluation.score_2)}
      </Typography>
      <Box sx={{ mb: 2 }}>
        {score2.map((s) => (
          <SubScoreRow key={s.code} sub={s} />
        ))}
      </Box>

      <Typography variant="caption" color="text.secondary">
        Scored by {evaluation.model || "unknown"} under rubric {evaluation.rubric_version}
        {evaluation.cost_usd !== null && ` · $${evaluation.cost_usd.toFixed(4)}`}
        {evaluation.input_tokens !== null &&
          ` · ${evaluation.input_tokens.toLocaleString()} in / ${(
            evaluation.output_tokens ?? 0
          ).toLocaleString()} out`}
        {evaluation.latency_ms !== null && ` · ${(evaluation.latency_ms / 1000).toFixed(1)}s`}.
        {abstained.length > 0 &&
          ` ${abstained.length} dimension${abstained.length > 1 ? "s" : ""} abstained, so the ` +
            "weighted mean is taken over the rest and the verdict cannot be SKIP."}
      </Typography>
    </Box>
  );
}
