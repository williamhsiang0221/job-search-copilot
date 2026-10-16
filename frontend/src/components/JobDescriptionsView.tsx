import { useCallback, useEffect, useId, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  InputLabel,
  LinearProgress,
  ListItemText,
  MenuItem,
  OutlinedInput,
  Select,
  type SelectChangeEvent,
  Tooltip,
  Link,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import SendIcon from "@mui/icons-material/Send";
import AssignmentIndIcon from "@mui/icons-material/AssignmentInd";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import ExpandableTable, { type ColumnDef } from "./ExpandableTable";
import VerdictChip from "./VerdictChip";
import EvaluationDetail from "./EvaluationDetail";
import MaskedText from "./MaskedText";
import SimilarApplicationsPanel from "./SimilarApplicationsPanel";
import PromptTab from "./PromptTab";
import {
  applyToJobs,
  generateIcpResume,
  startAssembly,
  getApplications,
  getEvaluateProgress,
  getEvaluations,
  getNormalizedJobs,
  getStoredJobs,
  startEvaluateJob,
} from "../api";
import { VERDICTS } from "../types";
import type {
  Evaluation,
  EvaluateReport,
  NormalizedJob,
  RangePreset,
  StoredJob,
} from "../types";
import { google } from "../theme";
import { parseIsoDate, resolveRangePreset, toIsoDate, todayIso } from "../dates";

// Same options as LinkedIn Job Alerts' date range — kept as a separate local
// copy rather than a shared export, since it is five lines and the two
// pickers are not otherwise coupled.
const NORMALIZED_RANGE_PRESETS: { value: RangePreset; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "past3", label: "Past 3 days" },
  { value: "past7", label: "Past 7 days" },
  { value: "custom", label: "Custom range" },
];

const EVALUATED_OPTIONS = [
  { value: "yes", label: "Evaluated" },
  { value: "no", label: "Not evaluated" },
];

const APPLIED_OPTIONS = [
  { value: "yes", label: "Applied" },
  { value: "no", label: "Not applied" },
];

const VERDICT_OPTIONS = [
  ...VERDICTS.map((v) => ({ value: v as string, label: v })),
  { value: "none", label: "Not evaluated" },
];

// Multi-select in place of a single "All" option: nothing checked means no
// filter on that column, same meaning "All" used to carry.
function MultiSelectFilter({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: string; label: string }[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const labelId = useId();

  function handleChange(event: SelectChangeEvent<string[]>) {
    const next = event.target.value;
    onChange(typeof next === "string" ? next.split(",") : next);
  }

  return (
    <FormControl size="small" sx={{ minWidth: 160 }}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select
        labelId={labelId}
        multiple
        value={value}
        onChange={handleChange}
        input={<OutlinedInput label={label} />}
        renderValue={(selected) => (selected.length === 0 ? "All" : selected.join(", "))}
      >
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            <Checkbox size="small" checked={value.includes(option.value)} />
            <ListItemText primary={option.label} />
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

const dash = (value: unknown) =>
  value === null || value === undefined || value === "" ? (
    <Box component="span" sx={{ color: google.border }}>
      —
    </Box>
  ) : (
    String(value)
  );

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const date = parseIsoDate(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatComp(min: number | null, max: number | null) {
  // A dash means the posting did not state a range — deliberately distinct
  // from a zero, which would imply it did.
  if (min === null && max === null) return dash(null);
  const money = (n: number) => `$${n.toLocaleString()}`;
  if (min !== null && max !== null) return min === max ? money(min) : `${money(min)} – ${money(max)}`;
  return money((min ?? max) as number);
}

const RAW_COLUMNS: ColumnDef<StoredJob>[] = [
  { id: "job_id", label: "Job ID", render: (j) => j.job_id, width: 110, nowrap: true },
  {
    id: "title",
    label: "Title",
    render: (j) => (
      <Link
        href={j.url}
        target="_blank"
        rel="noopener noreferrer"
        underline="hover"
        onClick={(e) => e.stopPropagation()}
        sx={{ color: google.blue, fontWeight: 500 }}
      >
        {j.title}
      </Link>
    ),
  },
  { id: "company", label: "Company", render: (j) => j.company },
  { id: "location", label: "Location", render: (j) => dash(j.location) },
  {
    id: "posted_at",
    label: "Posted",
    render: (j) => (
      <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
        <span>{formatDate(j.posted_at) || dash(null)}</span>
        {j.posted_at_is_approximate && j.posted_at && (
          <Chip size="small" variant="outlined" label="~" sx={{ height: 18, fontSize: "0.7rem" }} />
        )}
      </Stack>
    ),
    nowrap: true,
  },
  { id: "level_raw", label: "Seniority", render: (j) => dash(j.level_raw) },
  { id: "employment_type_raw", label: "Employment", render: (j) => dash(j.employment_type_raw) },
  { id: "job_function", label: "Function", render: (j) => dash(j.job_function) },
  {
    id: "description_chars",
    label: "Description",
    render: (j) => `${j.description_chars.toLocaleString()} chars`,
    nowrap: true,
  },
  { id: "fetched_at", label: "Fetched", render: (j) => formatDate(j.fetched_at), nowrap: true },
];

const jobKey = (j: { source: string; job_id: string }) => `${j.source}:${j.job_id}`;

// Splits source:job_id keys back apart and groups by source, since
// /api/evaluate and /api/applications/apply each take one source per request
// (same convention as /api/jobs/fetch) rather than mixed-source batches.
function groupBySource(keys: Set<string>): Map<string, string[]> {
  const bySource = new Map<string, string[]>();
  for (const key of keys) {
    const i = key.indexOf(":");
    const source = key.slice(0, i);
    const jobId = key.slice(i + 1);
    bySource.set(source, [...(bySource.get(source) ?? []), jobId]);
  }
  return bySource;
}

// Selection and status in one column, the way Capture's Fetch JD column works:
// a checked row is already done, so it is disabled and cannot be run again.
//
// Keyed by source:job_id, not job_id alone: Normalized holds LinkedIn,
// Greenhouse, Ashby and Lever rows together, and a job id is only unique
// within its own source.
const evaluateColumn = (
  evaluated: Set<string>,
  selected: Set<string>,
  onToggle: (key: string) => void,
): ColumnDef<NormalizedJob> => ({
  id: "evaluate",
  label: "Evaluated",
  width: 96,
  nowrap: true,
  render: (j) => (
    <Checkbox
      size="small"
      checked={evaluated.has(j.job_id) || selected.has(jobKey(j))}
      disabled={evaluated.has(j.job_id)}
      onChange={() => onToggle(jobKey(j))}
      // The row expands on click, so a tick would also open it.
      onClick={(e) => e.stopPropagation()}
    />
  ),
});

// Same pattern as evaluateColumn, but feeds Apply instead of Evaluate. Role is
// deliberately not set here — it's picked later in Applications' Needs
// Backfill tab, same as highest_round for legacy rows.
//
// Keyed by source:job_id for the same reason evaluateColumn is: a job id is
// only unique within its own source.
const appliedColumn = (
  applied: Set<string>,
  selected: Set<string>,
  onToggle: (key: string) => void,
): ColumnDef<NormalizedJob> => ({
  id: "applied",
  label: "Applied",
  width: 88,
  nowrap: true,
  render: (j) => (
    <Checkbox
      size="small"
      checked={applied.has(j.job_id) || selected.has(jobKey(j))}
      disabled={applied.has(j.job_id)}
      onChange={() => onToggle(jobKey(j))}
      onClick={(e) => e.stopPropagation()}
    />
  ),
});

// Latest run per job, same "newest-first, first sighting wins" rule
// EvaluationsView uses to decide what a verdict "is" right now. Keeps the
// full evaluation, not just its verdict, so the expanded row can show the
// same detail Evaluations does.
function latestEvaluationByJob(evaluations: Evaluation[]): Map<string, Evaluation> {
  const map = new Map<string, Evaluation>();
  for (const e of evaluations) {
    const key = jobKey(e);
    if (!map.has(key)) map.set(key, e);
  }
  return map;
}

// A rough triage aid, not a restatement of the verdict — the real verdict
// logic is thresholds plus hard gates, not a weighted average, so this can
// disagree with it (a gate-fired SKIP can still average out high). Meant to
// be sorted within a verdict, not across the whole table in place of it.
// Weighted 0.4 role/company fit (score_1) + 0.6 candidate fit (score_2) —
// candidate fit weighted higher by choice, not a rubric-derived figure.
function weightedScore(evaluation: Evaluation | undefined): number | null {
  if (!evaluation || evaluation.score_1 == null || evaluation.score_2 == null) return null;
  return Math.round((0.4 * evaluation.score_1 + 0.6 * evaluation.score_2) * 10) / 10;
}

// Responsibilities, qualifications, compensation, and workplace are
// deliberately not columns. Responsibilities/qualifications only ever showed
// a count; compensation/workplace are secondary detail that don't need to
// compete with the action checkboxes for width. All four live in the
// expanded row instead.
const normalizedColumns = (
  urlByJob: Map<string, string>,
  evaluationByJob: Map<string, Evaluation>,
): ColumnDef<NormalizedJob>[] => [
  {
    id: "verdict",
    label: "Verdict",
    width: 100,
    nowrap: true,
    render: (j) => {
      const evaluation = evaluationByJob.get(jobKey(j));
      return evaluation ? <VerdictChip verdict={evaluation.verdict} /> : dash(null);
    },
  },
  {
    id: "weighted_score",
    label: "Score",
    width: 80,
    nowrap: true,
    render: (j) => {
      const score = weightedScore(evaluationByJob.get(jobKey(j)));
      return score == null ? dash(null) : score.toFixed(1);
    },
    sortValue: (j) => weightedScore(evaluationByJob.get(jobKey(j))),
    defaultSortDirection: "desc",
  },
  { id: "job_id", label: "Job ID", render: (j) => j.job_id, width: 110, nowrap: true },
  {
    id: "title",
    label: "Title",
    render: (j) => {
      const url = urlByJob.get(jobKey(j));
      return url ? (
        <Link
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          underline="hover"
          onClick={(e) => e.stopPropagation()}
          sx={{ color: google.blue, fontWeight: 500 }}
        >
          <MaskedText>{j.title}</MaskedText>
        </Link>
      ) : (
        <MaskedText>{j.title}</MaskedText>
      );
    },
  },
  { id: "company", label: "Company", render: (j) => <MaskedText>{j.company}</MaskedText> },
  { id: "posted_at", label: "Posted", render: (j) => formatDate(j.posted_at) || dash(null), nowrap: true },
  {
    id: "normalized_at",
    label: "Normalized",
    render: (j) => formatDate(j.normalized_at),
    nowrap: true,
  },
];

function Bullets({ heading, items }: { heading: string; items: string[] }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
        {heading}
      </Typography>
      {items.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          None extracted.
        </Typography>
      ) : (
        <Box component="ul" sx={{ m: 0, pl: 3 }}>
          {items.map((item, i) => (
            <Typography component="li" variant="body2" key={i} sx={{ mb: 0.25 }}>
              {item}
            </Typography>
          ))}
        </Box>
      )}
    </Box>
  );
}

interface Props {
  sub: "normalized" | "raw" | "prompt";
  /** Opens a Resume Assembler run's live trace. */
  onOpenAssemblyRun: (runId: number) => void;
}

export default function JobDescriptionsView({ sub, onOpenAssemblyRun }: Props) {
  const [raw, setRaw] = useState<StoredJob[]>([]);
  const [normalized, setNormalized] = useState<NormalizedJob[]>([]);
  const [evaluated, setEvaluated] = useState<Set<string>>(new Set());
  const [evaluationByJob, setEvaluationByJob] = useState<Map<string, Evaluation>>(new Map());
  const [applied, setApplied] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedApply, setSelectedApply] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Per-row, since generation is a single on-demand action, not a batch —
  // several rows could each be generating independently.
  const [generatingIcp, setGeneratingIcp] = useState<Set<string>>(new Set());
  // Only the seeding step is awaited here; the run itself goes on in the
  // background and is watched in its tracer.
  const [startingAssembly, setStartingAssembly] = useState<Set<string>>(new Set());

  // While an evaluation is running: how many of the batch have resolved so
  // far (flattened across every source in the selection), and how many total
  // — so checkboxes can grey out live instead of only at the very end.
  const [evaluateDone, setEvaluateDone] = useState<Set<string>>(new Set());
  const [evaluateTotal, setEvaluateTotal] = useState(0);

  // Normalized-tab filters. The date range starts at "past7" fresh every
  // mount rather than being persisted, so the table never quietly opens
  // showing a range you picked in a previous session. Evaluated/Applied/
  // Verdict are multi-select: an empty array means no filter, same meaning
  // an "All" option used to carry.
  const [evaluatedFilter, setEvaluatedFilter] = useState<string[]>([]);
  const [appliedFilter, setAppliedFilter] = useState<string[]>([]);
  const [verdictFilter, setVerdictFilter] = useState<string[]>([]);
  const [normalizedRangePreset, setNormalizedRangePreset] = useState<RangePreset>("past7");
  const [normalizedRangeStart, setNormalizedRangeStart] = useState(todayIso());
  const [normalizedRangeEnd, setNormalizedRangeEnd] = useState(todayIso());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [jobs, norm, evaluations, applications] = await Promise.all([
        getStoredJobs(),
        getNormalizedJobs(),
        getEvaluations(),
        getApplications(),
      ]);
      setRaw(jobs);
      setNormalized(norm);
      setEvaluated(new Set(evaluations.map((e) => e.job_id)));
      setEvaluationByJob(latestEvaluationByJob(evaluations));
      setApplied(
        new Set(applications.applications.flatMap((a) => (a.job_id ? [a.job_id] : []))),
      );
      setSelected(new Set());
      setSelectedApply(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load stored jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const empty = !loading && raw.length === 0;

  // Normalized rows don't carry their own url; every one has a corresponding
  // raw row, which does.
  const urlByJob = useMemo(() => new Map(raw.map((j) => [jobKey(j), j.url])), [raw]);

  const filteredNormalized = useMemo(() => {
    const { start, end } = resolveRangePreset(normalizedRangePreset, normalizedRangeStart, normalizedRangeEnd);

    return normalized.filter((job) => {
      if (evaluatedFilter.length > 0) {
        const key = evaluated.has(job.job_id) ? "yes" : "no";
        if (!evaluatedFilter.includes(key)) return false;
      }

      if (appliedFilter.length > 0) {
        const key = applied.has(job.job_id) ? "yes" : "no";
        if (!appliedFilter.includes(key)) return false;
      }

      if (verdictFilter.length > 0) {
        const verdict = evaluationByJob.get(jobKey(job))?.verdict ?? "none";
        if (!verdictFilter.includes(verdict)) return false;
      }

      // normalized_at is a full UTC timestamp with no offset marker; slicing
      // the string directly compared a UTC calendar date against a range
      // computed from the local clock, so anything normalized in the evening
      // (UTC already "tomorrow") silently dropped out of every preset. Must
      // convert to a local calendar date first, same as start/end below.
      const day = job.normalized_at ? toIsoDate(parseIsoDate(job.normalized_at)) : null;
      if (!day || day < start || day > end) return false;

      return true;
    });
  }, [
    normalized,
    evaluated,
    applied,
    evaluationByJob,
    evaluatedFilter,
    appliedFilter,
    verdictFilter,
    normalizedRangePreset,
    normalizedRangeStart,
    normalizedRangeEnd,
  ]);

  function toggle(key: string) {
    const next = new Set(selected);
    next.has(key) ? next.delete(key) : next.add(key);
    setSelected(next);
  }

  function toggleApply(key: string) {
    const next = new Set(selectedApply);
    next.has(key) ? next.delete(key) : next.add(key);
    setSelectedApply(next);
  }

  const evaluate = async () => {
    setRunning(true);
    setError(null);
    setNotice(null);
    setEvaluateDone(new Set());
    setEvaluateTotal(selected.size);
    try {
      const bySource = groupBySource(selected);
      const sources = [...bySource.keys()];
      await Promise.all(sources.map((source) => startEvaluateJob(bySource.get(source)!, source)));

      let reports: EvaluateReport[] | null = null;
      while (!reports) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        const progresses = await Promise.all(sources.map((source) => getEvaluateProgress(source)));

        // Flattened across sources: evaluateColumn's disabled state already
        // keys off bare job_id the same way the persisted `evaluated` set does.
        const done = new Set<string>();
        for (const p of progresses) {
          for (const jobId of p.done_ids) done.add(jobId);
        }
        setEvaluateDone(done);

        const failed = progresses.find((p) => p.error);
        if (failed?.error) throw new Error(failed.error);

        if (progresses.every((p) => !p.running && p.report)) {
          reports = progresses.map((p) => p.report!);
        }
      }

      const evaluated = reports.flatMap((r) => r.evaluated);
      const failures = Object.assign({}, ...reports.map((r) => r.failures));
      const failed = Object.keys(failures).length;
      setNotice(
        `Evaluated ${evaluated.length}` + (failed ? `, ${failed} failed` : "") +
          ". See Evaluations for the verdicts.",
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation failed");
    } finally {
      setRunning(false);
      setEvaluateDone(new Set());
      setEvaluateTotal(0);
    }
  };

  const apply = async () => {
    setApplying(true);
    setError(null);
    setNotice(null);
    try {
      const bySource = groupBySource(selectedApply);
      const reports = await Promise.all(
        [...bySource.entries()].map(([source, ids]) => applyToJobs(ids, source)),
      );
      const applied = reports.flatMap((r) => r.applied);
      setNotice(
        `Applied to ${applied.length}. Pick a role category for ${
          applied.length === 1 ? "it" : "them"
        } in Applications → Needs backfill.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Apply failed");
    } finally {
      setApplying(false);
    }
  };

  const buildMyResume = async (job: NormalizedJob) => {
    const key = jobKey(job);
    setStartingAssembly((prev) => new Set(prev).add(key));
    setError(null);
    setNotice(null);
    try {
      onOpenAssemblyRun(await startAssembly(job.source, job.job_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the assembler");
      setStartingAssembly((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const generateIcp = async (job: NormalizedJob) => {
    const key = jobKey(job);
    setGeneratingIcp((prev) => new Set(prev).add(key));
    setError(null);
    setNotice(null);
    try {
      await generateIcpResume(job.source, job.job_id);
      setNotice(
        `Generated an ICP resume for ${job.title} at ${job.company} — see Resume Builder → ICP Resume.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "ICP resume generation failed");
    } finally {
      setGeneratingIcp((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  if (sub === "prompt") {
    return (
      <Box>
        <Typography variant="h1" sx={{ mb: 0.5 }}>
          Prompt
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          The extraction prompt verbatim. When a normalized field looks wrong, this is what
          settles it.
        </Typography>
        <PromptTab kind="normalizer" />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        {sub === "raw" ? "Raw" : "Normalized"}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {sub === "raw"
          ? "Descriptions exactly as published. This is the ground truth that settles a bad extraction."
          : "Model-extracted fields — what the evaluator reads."}
      </Typography>

      <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 2, flexWrap: "wrap" }}>
        {sub === "normalized" && (
          <Tooltip title="Scores the ticked roles against the rubric. Checked rows are already evaluated.">
            <span>
              <Button
                size="small"
                variant="contained"
                startIcon={
                  running ? <CircularProgress size={14} color="inherit" /> : <PlayArrowIcon />
                }
                onClick={() => void evaluate()}
                disabled={running || loading || selected.size === 0}
              >
                {running
                  ? `Evaluating… (${evaluateDone.size}/${evaluateTotal})`
                  : selected.size
                    ? `Evaluate ${selected.size}`
                    : "Evaluate"}
              </Button>
            </span>
          </Tooltip>
        )}
        {sub === "normalized" && (
          <Tooltip title="Creates an application for each ticked role. Checked rows are already applied to.">
            <span>
              <Button
                size="small"
                variant="contained"
                startIcon={
                  applying ? <CircularProgress size={14} color="inherit" /> : <SendIcon />
                }
                onClick={() => void apply()}
                disabled={applying || loading || selectedApply.size === 0}
              >
                {selectedApply.size ? `Apply ${selectedApply.size}` : "Apply"}
              </Button>
            </span>
          </Tooltip>
        )}
        <Button
          size="small"
          startIcon={loading ? <CircularProgress size={14} /> : <RefreshIcon />}
          onClick={() => void load()}
          disabled={loading || running}
        >
          Refresh
        </Button>
        <Chip size="small" variant="outlined" label={`${raw.length} stored`} />
        <Chip size="small" variant="outlined" label={`${normalized.length} normalized`} />
        {sub === "normalized" && (
          <Chip
            size="small"
            variant="outlined"
            label={`${normalized.filter((j) => !evaluated.has(j.job_id)).length} unevaluated`}
          />
        )}
        {sub === "normalized" && (
          <Chip
            size="small"
            variant="outlined"
            label={`${normalized.filter((j) => !applied.has(j.job_id)).length} not applied`}
          />
        )}
      </Stack>

      {running && (
        <Box sx={{ mb: 2 }}>
          <LinearProgress
            variant="determinate"
            value={evaluateTotal ? (evaluateDone.size / evaluateTotal) * 100 : 0}
            sx={{ borderRadius: 1, height: 6 }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
            {evaluateDone.size} of {evaluateTotal} resolved
          </Typography>
        </Box>
      )}

      {sub === "normalized" && (
        <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 2, flexWrap: "wrap" }}>
          <MultiSelectFilter
            label="Evaluated"
            options={EVALUATED_OPTIONS}
            value={evaluatedFilter}
            onChange={setEvaluatedFilter}
          />

          <MultiSelectFilter
            label="Applied"
            options={APPLIED_OPTIONS}
            value={appliedFilter}
            onChange={setAppliedFilter}
          />

          <MultiSelectFilter
            label="Verdict"
            options={VERDICT_OPTIONS}
            value={verdictFilter}
            onChange={setVerdictFilter}
          />

          <TextField
            select
            size="small"
            label="Normalized"
            value={normalizedRangePreset}
            onChange={(e) => setNormalizedRangePreset(e.target.value as RangePreset)}
            sx={{ minWidth: 160 }}
          >
            {NORMALIZED_RANGE_PRESETS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>

          {normalizedRangePreset === "custom" && (
            <>
              <TextField
                size="small"
                type="date"
                label="From"
                value={normalizedRangeStart}
                onChange={(e) => setNormalizedRangeStart(e.target.value)}
                slotProps={{ inputLabel: { shrink: true } }}
              />
              <TextField
                size="small"
                type="date"
                label="To"
                value={normalizedRangeEnd}
                onChange={(e) => setNormalizedRangeEnd(e.target.value)}
                slotProps={{ inputLabel: { shrink: true } }}
              />
            </>
          )}
        </Stack>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {notice && (
        <Alert severity="success" sx={{ mb: 2, borderRadius: 2 }} onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}

      {empty && !error && (
        <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
          No job descriptions stored yet. Go to Capture, tick some roles, and use Fetch JD.
        </Alert>
      )}

      {sub === "raw" && (
        <ExpandableTable
          rows={raw}
          columns={RAW_COLUMNS}
          rowKey={(j) => `${j.source}:${j.job_id}`}
          minWidth={1250}
          expanded={(job) => (
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>
                Raw description — {job.description_chars.toLocaleString()} chars, exactly as stored
              </Typography>
              <Box
                component="pre"
                sx={{
                  m: 0,
                  p: 2,
                  maxHeight: 460,
                  overflow: "auto",
                  fontSize: "0.8125rem",
                  lineHeight: 1.6,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  backgroundColor: google.surface,
                  border: `1px solid ${google.border}`,
                  borderRadius: 1,
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                }}
              >
                {job.description_raw || "(empty)"}
              </Box>
              <Stack direction="row" spacing={2} sx={{ mt: 1.5, flexWrap: "wrap" }}>
                <Typography variant="caption" color="text.secondary">
                  Industries: {job.industries ?? "—"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Department: {job.department ?? "—"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Workplace (source): {job.workplace_raw ?? "—"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Apply URL: {job.apply_url ?? "— (LinkedIn withholds it from guests)"}
                </Typography>
              </Stack>
            </Box>
          )}
        />
      )}

      {sub === "normalized" && (
        <ExpandableTable
          rows={filteredNormalized}
          columns={[
            evaluateColumn(
              // While running: resolved ids grey out immediately rather than
              // waiting for the whole batch to finish.
              running ? new Set([...evaluated, ...evaluateDone]) : evaluated,
              selected,
              toggle,
            ),
            appliedColumn(applied, selectedApply, toggleApply),
            ...normalizedColumns(urlByJob, evaluationByJob),
          ]}
          rowKey={(j) => `${j.source}:${j.job_id}`}
          // Narrower than Raw: three columns came out to leave room for the
          // action checkboxes without forcing a sideways scroll.
          minWidth={1070}
          expanded={(job) => {
            const evaluation = evaluationByJob.get(jobKey(job));
            return (
              <Box>
                <Stack direction="row" spacing={3} sx={{ mb: 2, alignItems: "center" }}>
                  <Typography variant="body2">
                    <Box component="span" sx={{ fontWeight: 500 }}>
                      Compensation:{" "}
                    </Box>
                    <MaskedText>{formatComp(job.comp_min, job.comp_max)}</MaskedText>
                  </Typography>
                  <Typography variant="body2">
                    <Box component="span" sx={{ fontWeight: 500 }}>
                      Workplace:{" "}
                    </Box>
                    {dash(job.workplace)}
                  </Typography>
                  <Tooltip title="Generates a benchmark resume for this role — see Resume Builder → ICP Resume. Takes a few seconds.">
                    <span>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={
                          generatingIcp.has(jobKey(job)) ? (
                            <CircularProgress size={14} />
                          ) : (
                            <AssignmentIndIcon fontSize="small" />
                          )
                        }
                        onClick={() => void generateIcp(job)}
                        disabled={generatingIcp.has(jobKey(job))}
                      >
                        {generatingIcp.has(jobKey(job)) ? "Generating…" : "Generate ICP Resume"}
                      </Button>
                    </span>
                  </Tooltip>
                  <Tooltip title="Assembles a resume for this role from your past resumes, then opens its live trace in Resume Builder → Assembler.">
                    <span>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={
                          startingAssembly.has(jobKey(job)) ? (
                            <CircularProgress size={14} />
                          ) : (
                            <AutoAwesomeOutlinedIcon fontSize="small" />
                          )
                        }
                        onClick={() => void buildMyResume(job)}
                        disabled={startingAssembly.has(jobKey(job))}
                      >
                        {startingAssembly.has(jobKey(job)) ? "Starting…" : "Build My Resume"}
                      </Button>
                    </span>
                  </Tooltip>
                </Stack>
                {job.role_summary === null ? (
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
                      About the role
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Not extracted — normalized with {job.normalizer_version}, before this field existed.
                    </Typography>
                  </Box>
                ) : (
                  <Bullets heading="About the role" items={job.role_summary} />
                )}
                <Bullets heading="Responsibilities" items={job.responsibilities} />
                <Bullets heading="Qualifications" items={job.qualifications} />
                <Typography variant="caption" color="text.secondary">
                  Extracted by {job.model || "unknown"}. Compensation and workplace are null when the
                  posting did not state them.
                </Typography>
                {evaluation && (
                  <>
                    <Divider sx={{ my: 2 }} />
                    <Typography variant="body2" sx={{ fontWeight: 500, mb: 1.5 }}>
                      Evaluation
                    </Typography>
                    <EvaluationDetail evaluation={evaluation} />
                  </>
                )}
                <Divider sx={{ my: 2 }} />
                <Typography variant="body2" sx={{ fontWeight: 500, mb: 1.5 }}>
                  Similar past applications
                </Typography>
                <SimilarApplicationsPanel source={job.source} jobId={job.job_id} />
              </Box>
            );
          }}
        />
      )}
    </Box>
  );
}
