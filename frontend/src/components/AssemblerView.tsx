import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import FlagOutlinedIcon from "@mui/icons-material/FlagOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { getAssemblyRun, getAssemblyRuns } from "../api";
import type { AssemblyRun, AssemblyStatus, AssemblyTurn, DraftLine, ScanVerdict } from "../types";
import { google } from "../theme";
import { parseIsoDate } from "../dates";
import { useSlotLabels } from "../slots";
import CopyButton, { showCopyOnHover } from "./CopyButton";

const POLL_MS = 1500;

const STATUS: Record<AssemblyStatus, { label: string; color: string }> = {
  seeded: { label: "Starting", color: google.textSecondary },
  running: { label: "Running", color: google.blue },
  passed: { label: "Passed", color: google.green },
  hit_cap: { label: "Hit cap", color: google.yellow },
  stopped: { label: "Stopped", color: google.textSecondary },
  error: { label: "Error", color: google.red },
};

// Anchor is neutral grey; donors take these in the order they were loaded.
const DONOR_COLORS = ["#1a73e8", "#9334e6", "#12b5cb", "#e8710a", "#d01884", "#188038"];

const isLive = (status: AssemblyStatus) => status === "seeded" || status === "running";

function StatusChip({ status }: { status: AssemblyStatus }) {
  const s = STATUS[status];
  return (
    <Chip
      size="small"
      label={s.label}
      sx={{ backgroundColor: s.color, color: status === "hit_cap" ? google.textPrimary : "#fff", fontWeight: 600 }}
    />
  );
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return parseIsoDate(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

const money = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(4)}`);

// --- run list ---------------------------------------------------------------

function RunList({ onSelect }: { onSelect: (id: number) => void }) {
  const [runs, setRuns] = useState<AssemblyRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = () =>
      getAssemblyRuns()
        .then((data) => {
          if (cancelled) return;
          setRuns(data);
          // Keep the list's statuses fresh only while something is still running.
          if (data.some((r) => isLive(r.status))) timer = window.setTimeout(load, POLL_MS * 2);
        })
        .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not load"));
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (runs === null) return <CircularProgress size={20} />;
  if (runs.length === 0) {
    return (
      <Paper variant="outlined" sx={{ p: 6, textAlign: "center", borderColor: google.border, borderRadius: 2 }}>
        <Typography color="text.secondary">
          No runs yet. Start one with Build My Resume on a role in Job descriptions → Normalized.
        </Typography>
      </Paper>
    );
  }
  return (
    <TableContainer component={Paper} variant="outlined" sx={{ borderColor: google.border, borderRadius: 2 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Started</TableCell>
            <TableCell>Posting</TableCell>
            <TableCell>Status</TableCell>
            <TableCell align="right">Rounds</TableCell>
            <TableCell align="right">Turns</TableCell>
            <TableCell align="right">Cost</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {runs.map((r) => (
            <TableRow key={r.id} hover onClick={() => onSelect(r.id)} sx={{ cursor: "pointer" }}>
              <TableCell sx={{ whiteSpace: "nowrap", color: google.textSecondary }}>{formatTime(r.started_at)}</TableCell>
              <TableCell>
                <Box component="span" sx={{ fontWeight: 500 }}>{r.company}</Box> — {r.title}
              </TableCell>
              <TableCell><StatusChip status={r.status} /></TableCell>
              <TableCell align="right">{r.rounds_used}</TableCell>
              <TableCell align="right">{r.turns_used}</TableCell>
              <TableCell align="right">{money(r.cost_usd)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

// --- sources ----------------------------------------------------------------

interface Source {
  label: string;
  color: string;
}

/** Every resume a run drew on, anchor first, with a label and a color. */
function useSources(run: AssemblyRun | null): Record<string, Source> {
  return useMemo(() => {
    if (!run) return {};
    const sources: Record<string, Source> = {
      [run.anchor_resume_id]: { label: `${run.seed.anchor.company} (anchor)`, color: google.textSecondary },
    };
    let next = 0;
    const add = (id: string, label: string) => {
      if (sources[id]) return;
      sources[id] = { label, color: DONOR_COLORS[next++ % DONOR_COLORS.length] };
    };
    for (const d of run.seed.donors) if (d.resume_id) add(d.resume_id, d.company);
    // Resumes pulled in later by fetch_more_resumes, labeled from the tool's own output.
    for (const t of run.turns ?? []) {
      if (t.tool_name !== "fetch_more_resumes" || !t.result?.resumes) continue;
      for (const m of String(t.result.resumes).matchAll(/### Donor resume (\S+) — originally for (.+?) —/g)) {
        add(m[1], m[2]);
      }
    }
    return sources;
  }, [run]);
}

function SourceDot({ source }: { source: Source | undefined }) {
  return (
    <Box
      component="span"
      title={source?.label}
      sx={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        backgroundColor: source?.color ?? google.border,
        mr: 1,
        flexShrink: 0,
        mt: "6px",
      }}
    />
  );
}

// --- the trace ----------------------------------------------------------------

function toolCallText(name: string, input: Record<string, any>): string {
  const args = Object.values(input ?? {}).map(String);
  return `${name}(${args.join(", ")})`;
}

function TurnRow({ turn, sources }: { turn: AssemblyTurn; sources: Record<string, Source> }) {
  const r = turn.result ?? {};
  const p = turn.payload ?? {};

  if (turn.kind === "model") {
    return (
      <Box sx={{ display: "flex", gap: 1.5, py: 1.25 }}>
        <SmartToyOutlinedIcon fontSize="small" sx={{ color: google.blue, mt: "2px" }} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {p.text && (
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
              {p.text}
            </Typography>
          )}
          {(p.tool_calls ?? []).map((c: { name: string; input: Record<string, any> }, i: number) => (
            <Typography key={i} variant="caption" sx={{ display: "block", fontFamily: "monospace", color: google.textSecondary }}>
              → {toolCallText(c.name, c.input)}
            </Typography>
          ))}
          <Typography variant="caption" color="text.secondary">
            {turn.model} · {turn.input_tokens ?? "?"} in / {turn.output_tokens ?? "?"} out · {money(turn.cost_usd)}
          </Typography>
        </Box>
      </Box>
    );
  }

  if (turn.kind === "tool") {
    let body: React.ReactNode;
    if (r.error) {
      body = <Typography variant="body2" sx={{ color: google.red }}>Rejected: {r.error}</Typography>;
    } else if (turn.tool_name === "swap_bullet" || turn.tool_name === "swap_header") {
      const where = turn.tool_name === "swap_bullet" ? `[${p.slot}.${p.position}]` : `[${p.slot}.header]`;
      body = r.note ? (
        <Typography variant="body2" color="text.secondary">{where} {r.note}</Typography>
      ) : (
        <>
          <Typography variant="body2" sx={{ textDecoration: "line-through", color: google.textSecondary }}>
            {where} {r.replaced}
          </Typography>
          <Typography variant="body2">{where} {r.now}</Typography>
        </>
      );
    } else if (turn.tool_name === "fetch_more_resumes") {
      body = (
        <Typography variant="body2">
          {r.ok ? `Loaded ${(r.loaded ?? []).map((id: string) => sources[id]?.label ?? id).join(", ")}` : r.note}
        </Typography>
      );
    } else if (turn.tool_name === "view_draft") {
      body = <Typography variant="body2" color="text.secondary">Read the current draft.</Typography>;
    } else {
      body = <ScanSummary verdict={r as ScanVerdict} />;
    }
    return (
      <Box sx={{ display: "flex", gap: 1.5, py: 1, pl: 3.5 }}>
        <BuildOutlinedIcon fontSize="small" sx={{ color: google.textSecondary, mt: "2px" }} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="caption" sx={{ fontFamily: "monospace", color: google.textSecondary }}>
            {turn.tool_name}
            {turn.cost_usd ? ` · ${money(turn.cost_usd)}` : ""}
          </Typography>
          {body}
        </Box>
      </Box>
    );
  }

  // system
  let text: React.ReactNode = turn.tool_name;
  if (turn.tool_name === "seed") {
    // Older runs have no reason; every donor then was a similarity pick.
    const donors = (r.donors ?? []).map((d: { company: string; score: number | null; reason?: string }) =>
      d.reason?.startsWith("latest ")
        ? `${d.company} (newest ${d.reason.slice("latest ".length)})`
        : `${d.company} (${d.score?.toFixed(2)})`,
    );
    const skipped = (r.ranked ?? []).filter((c: { resume_id: string | null }) => !c.resume_id).length;
    text = `Seeded — anchor ${r.anchor?.company} (${r.anchor?.score?.toFixed(2)}), donors ${donors.join(", ") || "none"}. Skipped ${skipped} similar role(s) with no resume on file.`;
  } else if (turn.tool_name === "ats_criteria") {
    text = <CriteriaList criteria={r.criteria ?? []} cost={turn.cost_usd} />;
  } else if (turn.tool_name === "stop") {
    text = `Stopped — ${r.reason}`;
  } else if (turn.tool_name === "cutoff") {
    text = `Reply hit the ${r.max_tokens}-token output limit before a move — told the agent to keep notes short and continue.`;
  } else if (turn.tool_name === "error") {
    text = <Box component="span" sx={{ color: google.red }}>{r.error}</Box>;
  }
  return (
    <Box sx={{ display: "flex", gap: 1.5, py: 1 }}>
      <FlagOutlinedIcon fontSize="small" sx={{ color: google.textSecondary, mt: "2px" }} />
      <Typography variant="body2" component="div" color="text.secondary" sx={{ flex: 1 }}>{text}</Typography>
    </Box>
  );
}

function CriteriaList({ criteria, cost }: { criteria: { criterion: string; required: boolean }[]; cost: number | null }) {
  const [open, setOpen] = useState(false);
  return (
    <Box>
      Built {criteria.length} screening criteria ({money(cost)}).{" "}
      <Box component="span" onClick={() => setOpen((o) => !o)} sx={{ color: google.blue, cursor: "pointer" }}>
        {open ? "Hide" : "Show"}
      </Box>
      {open && (
        <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
          {criteria.map((c, i) => (
            <li key={i}>
              <Box component="span" sx={{ fontWeight: c.required ? 600 : 400 }}>
                {c.required ? "Required" : "Preferred"}:
              </Box>{" "}
              {c.criterion}
            </li>
          ))}
        </Box>
      )}
    </Box>
  );
}

function ScanSummary({ verdict }: { verdict: ScanVerdict }) {
  const labels = verdict.labels
    ? `In these reasons, A = ${verdict.labels.A === "candidate" ? "the draft" : "the anchor"}, B = ${verdict.labels.B === "candidate" ? "the draft" : "the anchor"}.`
    : null;
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 0.5 }}>
        <Chip
          size="small"
          label={verdict.passed ? "Pass" : "Fail"}
          sx={{ backgroundColor: verdict.passed ? google.green : google.red, color: "#fff", fontWeight: 600 }}
        />
        {verdict.winner && (
          <Typography variant="body2">
            Winner: {verdict.winner === "candidate" ? "draft" : verdict.winner}
          </Typography>
        )}
      </Stack>
      {verdict.reasons && <Typography variant="body2">{verdict.reasons}</Typography>}
      {verdict.defects && verdict.defects.length === 0 && (
        <Typography variant="body2">Every line is copied verbatim from a real resume, in the same section.</Typography>
      )}
      {labels && <Typography variant="caption" color="text.secondary">{labels}</Typography>}
      {(verdict.defects ?? []).map((d, i) => (
        <Typography key={i} variant="body2" sx={{ color: google.red }}>
          {d.kind} [{d.refs.join(", ")}]: {d.detail}
        </Typography>
      ))}
    </Box>
  );
}

type ScannerKey = "hard_gate" | "ats" | "recruiter";

const SCANNERS: { key: ScannerKey; label: string }[] = [
  { key: "hard_gate", label: "Hard gate" },
  { key: "ats", label: "ATS scanner" },
  { key: "recruiter", label: "Recruiter scanner" },
];

/** The three scanners as a compact row — pass/fail and winner only. Clicking
 * one unfolds its full reasons beneath the row; clicking again folds it. */
function ScannerStrip({ verdicts }: { verdicts: AssemblyRun["verdicts"] }) {
  const [open, setOpen] = useState<ScannerKey | null>(null);
  const openVerdict = open ? verdicts[open] : undefined;
  return (
    <Box>
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 1.5 }}>
        {SCANNERS.map(({ key, label }) => {
          const v = verdicts[key];
          const isOpen = open === key;
          return (
            <Paper
              key={key}
              variant="outlined"
              onClick={() => v && setOpen(isOpen ? null : key)}
              sx={{
                p: 1.5,
                borderRadius: 2,
                borderColor: isOpen ? google.blue : google.border,
                cursor: v ? "pointer" : "default",
                "&:hover": v ? { borderColor: google.blue } : undefined,
              }}
            >
              <Stack direction="row" sx={{ alignItems: "center", justifyContent: "space-between", mb: 0.5 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>{label}</Typography>
                {v && (isOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />)}
              </Stack>
              {v ? (
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Chip
                    size="small"
                    label={v.passed ? "Pass" : "Fail"}
                    sx={{ backgroundColor: v.passed ? google.green : google.red, color: "#fff", fontWeight: 600 }}
                  />
                  {v.winner && (
                    <Typography variant="caption" color="text.secondary">
                      Winner: {v.winner === "candidate" ? "draft" : v.winner}
                    </Typography>
                  )}
                </Stack>
              ) : (
                <Typography variant="caption" color="text.secondary">Not run yet</Typography>
              )}
            </Paper>
          );
        })}
      </Box>
      <Collapse in={!!openVerdict} unmountOnExit>
        {openVerdict && (
          <Paper variant="outlined" sx={{ p: 2, mt: 1.5, borderRadius: 2, borderColor: google.blue }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
              {SCANNERS.find((s) => s.key === open)?.label} — reasons
            </Typography>
            <ScanSummary verdict={openVerdict} />
          </Paper>
        )}
      </Collapse>
    </Box>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderColor: google.border, borderRadius: 2 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>{title}</Typography>
      {children}
    </Paper>
  );
}

function DraftLineRow({ line, anchorId, sources, prefix }: {
  line: DraftLine; anchorId: string; sources: Record<string, Source>; prefix?: string;
}) {
  const swapped = line.source_resume_id !== anchorId;
  return (
    <Box
      sx={{
        display: "flex",
        py: 0.25,
        px: 0.75,
        borderRadius: 1,
        backgroundColor: swapped ? google.blueSurface : "transparent",
      }}
    >
      <SourceDot source={sources[line.source_resume_id]} />
      {/* Bullets only: role headers get no copy button, same as the
          Applications resume panel. */}
      <Typography variant="body2" sx={{ fontWeight: prefix ? 600 : 400, ...(prefix ? {} : showCopyOnHover) }}>
        {line.text}
        {!prefix && <CopyButton text={line.text} />}
      </Typography>
    </Box>
  );
}

function RunTrace({ runId, onBack }: { runId: number; onBack: () => void }) {
  const SLOT_LABELS = useSlotLabels();
  const [run, setRun] = useState<AssemblyRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const sources = useSources(run);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = () =>
      getAssemblyRun(runId)
        .then((data) => {
          if (cancelled) return;
          setRun(data);
          if (isLive(data.status)) timer = window.setTimeout(load, POLL_MS);
        })
        .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not load"));
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [runId]);

  // Follow the newest turn if this run was watched live — including its
  // final update, which is the one that lands after it stops being live. A
  // run opened after it finished starts at the top, to be read in order.
  const watchedLive = useRef(false);
  if (run && isLive(run.status)) watchedLive.current = true;
  const turnCount = run?.turns?.length ?? 0;
  useEffect(() => {
    if (watchedLive.current && timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight;
    }
  }, [turnCount]);

  const provenance = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of run?.draft.sections ?? []) {
      for (const line of [...(s.header ? [s.header] : []), ...s.bullets]) {
        counts[line.source_resume_id] = (counts[line.source_resume_id] ?? 0) + 1;
      }
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [run]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (!run) return <CircularProgress size={20} />;

  return (
    <Box>
      <Button size="small" startIcon={<ArrowBackIcon />} onClick={onBack} sx={{ mb: 1 }}>
        All runs
      </Button>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", mb: 0.5, flexWrap: "wrap" }}>
        <Typography variant="h2" sx={{ fontSize: "1.25rem" }}>
          {run.company} — {run.title}
        </Typography>
        <StatusChip status={run.status} />
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Run #{run.id} · started {formatTime(run.started_at)} · {run.rounds_used} round(s) · {run.turns_used} turn(s) ·{" "}
        {money(run.cost_usd)}
        {run.finished_at ? ` · finished ${formatTime(run.finished_at)}` : ""}
      </Typography>
      {isLive(run.status) && <LinearProgress sx={{ mb: 2, borderRadius: 1 }} />}
      {run.error && <Alert severity="error" sx={{ mb: 2 }}>{run.error}</Alert>}

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 5fr) minmax(0, 6fr)" }, gap: 2 }}>
        <Stack spacing={2}>
          <ScannerStrip verdicts={run.verdicts} />
          <Panel title="Trace">
            <Box ref={timelineRef} sx={{ maxHeight: "70vh", overflowY: "auto", pr: 1 }}>
              {(run.turns ?? []).map((t) => (
                <Box key={t.seq} sx={{ borderBottom: `1px solid ${google.border}`, "&:last-child": { borderBottom: 0 } }}>
                  <TurnRow turn={t} sources={sources} />
                </Box>
              ))}
            </Box>
          </Panel>
        </Stack>

        <Stack spacing={2}>
          <Panel title="Where the lines came from">
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
              {provenance.map(([id, count]) => (
                <Chip
                  key={id}
                  size="small"
                  variant="outlined"
                  label={`${sources[id]?.label ?? id}: ${count}`}
                  icon={<SourceDot source={sources[id]} />}
                  sx={{ pl: 0.75 }}
                />
              ))}
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
              Highlighted lines below were swapped in from a donor; the rest are the anchor's own.
            </Typography>
          </Panel>

          <Panel title="Draft">
            {run.draft.headline && (
              <Typography variant="body2" sx={{ fontStyle: "italic", color: google.textSecondary, mb: 1.5 }}>
                {run.draft.headline}
              </Typography>
            )}
            <Stack spacing={1.5}>
              {run.draft.sections.map((s) => (
                <Box key={s.slot}>
                  <Typography variant="caption" color="text.secondary">{SLOT_LABELS[s.slot] ?? s.slot}</Typography>
                  {s.header && <DraftLineRow line={s.header} anchorId={run.anchor_resume_id} sources={sources} prefix="header" />}
                  {s.bullets.map((b, i) => (
                    <DraftLineRow key={i} line={b} anchorId={run.anchor_resume_id} sources={sources} />
                  ))}
                </Box>
              ))}
            </Stack>
          </Panel>
        </Stack>
      </Box>
    </Box>
  );
}

interface Props {
  runId: number | null;
  onSelectRun: (id: number | null) => void;
}

/** Resume Builder → Assembler: every run, and a live trace of one. A run's
 * trace is polled while it's going — each model call and tool call appears
 * as the backend logs it. */
export default function AssemblerView({ runId, onSelectRun }: Props) {
  return runId == null ? (
    <RunList onSelect={onSelectRun} />
  ) : (
    <RunTrace runId={runId} onBack={() => onSelectRun(null)} />
  );
}
