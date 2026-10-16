import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import RolesTable from "./RolesTable";
import DownloadIcon from "@mui/icons-material/Download";
import { getJobFetchProgress, getJobsStatus, runCapture, startJobFetch } from "../api";
import type { CaptureMeta, FetchReport, RangePreset, Role } from "../types";
import { google } from "../theme";

const PRESETS: { value: RangePreset; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "past3", label: "Past 3 days" },
  { value: "past7", label: "Past 7 days" },
  { value: "custom", label: "Custom range" },
];

const today = () => new Date().toISOString().slice(0, 10);

export default function CaptureView() {
  const [preset, setPreset] = useState<RangePreset>("today");
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [roles, setRoles] = useState<Role[]>([]);
  const [meta, setMeta] = useState<CaptureMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasRun, setHasRun] = useState(false);

  // Which roles already have a stored, normalized description, and which the
  // user has ticked for fetching.
  const [fetched, setFetched] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [fetching, setFetching] = useState(false);
  const [fetchNote, setFetchNote] = useState<string | null>(null);

  // While a fetch is running: how many of the batch have resolved so far
  // (success or failure), and which specific ids — so their checkboxes can
  // grey out live instead of only at the very end.
  const [fetchDone, setFetchDone] = useState<Set<string>>(new Set());
  const [fetchTotal, setFetchTotal] = useState(0);

  async function refreshFetchedStatus(forRoles: Role[]) {
    try {
      setFetched(await getJobsStatus(forRoles.map((r) => r.job_id)));
    } catch {
      // A failed status check only costs the checkmarks, so leave the table
      // usable rather than failing the whole capture.
      setFetched(new Set());
    }
  }

  async function handleFetchDescriptions() {
    const ids = [...selected];
    if (ids.length === 0) return;

    setFetching(true);
    setFetchNote(null);
    setError(null);
    setFetchDone(new Set());
    setFetchTotal(ids.length);
    try {
      await startJobFetch(ids);

      let report: FetchReport | null = null;
      while (!report) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        const progress = await getJobFetchProgress();
        setFetchDone(new Set(progress.done_ids));
        if (progress.error) throw new Error(progress.error);
        if (!progress.running && progress.report) report = progress.report;
      }

      const { counts } = report;
      const parts = [`${counts.normalized} ready`];
      if (counts.normalize_failed) parts.push(`${counts.normalize_failed} stored but not normalized`);
      if (counts.failed) parts.push(`${counts.failed} failed`);
      if (counts.skipped) parts.push(`${counts.skipped} already had one`);
      setFetchNote(parts.join(" · "));

      // Surface the actual reason rather than a bare count.
      const firstProblem =
        Object.values(report.failures)[0] ?? Object.values(report.normalize_failures)[0];
      if (firstProblem) setError(firstProblem);

      // Leave failed roles checked so a retry is one click, not a re-search.
      setSelected(
        new Set([...Object.keys(report.failures), ...Object.keys(report.normalize_failures)]),
      );
      await refreshFetchedStatus(roles);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
    } finally {
      setFetching(false);
      setFetchDone(new Set());
      setFetchTotal(0);
    }
  }

  async function handleRun() {
    setLoading(true);
    setError(null);
    try {
      const result = await runCapture(preset, start, end);
      setRoles(result.roles);
      setMeta(result.meta);
      setSelected(new Set());
      setFetchNote(null);
      await refreshFetchedStatus(result.roles);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Capture failed");
      setRoles([]);
      setMeta(null);
    } finally {
      setLoading(false);
      setHasRun(true);
    }
  }

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        LinkedIn Job Alerts
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Read LinkedIn job alert emails and list the roles they contain.
      </Typography>

      <Paper
        variant="outlined"
        sx={{ p: 2, mb: 3, borderColor: google.border, borderRadius: 2 }}
      >
        <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
          <TextField
            select
            size="small"
            label="Date range"
            value={preset}
            onChange={(e) => setPreset(e.target.value as RangePreset)}
            sx={{ minWidth: 180 }}
          >
            {PRESETS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>

          {preset === "custom" && (
            <>
              <TextField
                size="small"
                type="date"
                label="From"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                slotProps={{ inputLabel: { shrink: true } }}
              />
              <TextField
                size="small"
                type="date"
                label="To"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                slotProps={{ inputLabel: { shrink: true } }}
              />
            </>
          )}

          <Button
            variant="contained"
            onClick={handleRun}
            disabled={loading}
            startIcon={
              loading ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />
            }
          >
            {loading ? "Capturing…" : "Run capture"}
          </Button>

          {roles.length > 0 && (
            <Button
              variant="outlined"
              onClick={handleFetchDescriptions}
              disabled={selected.size === 0 || fetching}
              startIcon={
                fetching ? <CircularProgress size={16} color="inherit" /> : <DownloadIcon />
              }
            >
              {fetching
                ? `Fetching… (${fetchDone.size}/${fetchTotal})`
                : `Fetch JD${selected.size ? ` (${selected.size})` : ""}`}
            </Button>
          )}

          {fetchNote && !fetching && (
            <Chip size="small" variant="outlined" label={fetchNote} />
          )}

          {meta && !loading && (
            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
              <Chip
                size="small"
                label={`${meta.roles_found} roles from ${meta.emails_scanned} emails`}
                sx={{ backgroundColor: google.blueSurface, color: google.blue }}
              />
              {meta.duplicates_collapsed > 0 && (
                <Tooltip
                  title={`${meta.rows_parsed} listings were found; repeats of the same job were collapsed into one row each.`}
                >
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${meta.duplicates_collapsed} duplicates collapsed`}
                  />
                </Tooltip>
              )}
              {meta.source === "fixtures" && (
                <Chip size="small" variant="outlined" label="Sample data" />
              )}
            </Stack>
          )}
        </Stack>

        {fetching && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress
              variant="determinate"
              value={fetchTotal ? (fetchDone.size / fetchTotal) * 100 : 0}
              sx={{ borderRadius: 1, height: 6 }}
            />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
              {fetchDone.size} of {fetchTotal} resolved
            </Typography>
          </Box>
        )}
      </Paper>

      {error && (
        <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {hasRun && !error && roles.length === 0 && !loading && (
        <Paper
          variant="outlined"
          sx={{ p: 6, textAlign: "center", borderColor: google.border, borderRadius: 2 }}
        >
          <Typography color="text.secondary">
            No roles found in that date range.
          </Typography>
        </Paper>
      )}

      {roles.length > 0 && (
        <RolesTable
          roles={roles}
          // While a batch is in flight, resolved ids grey out immediately
          // rather than waiting for the whole run to finish.
          fetched={fetching ? new Set([...fetched, ...fetchDone]) : fetched}
          selected={selected}
          onSelectionChange={setSelected}
        />
      )}
    </Box>
  );
}
