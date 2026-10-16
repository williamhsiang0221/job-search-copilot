import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  Link,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import SearchIcon from "@mui/icons-material/Search";
import DownloadIcon from "@mui/icons-material/Download";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowRightIcon from "@mui/icons-material/KeyboardArrowRight";
import ExpandableTable, { type ColumnDef } from "./ExpandableTable";
import {
  addTrackedCompany,
  fetchAtsDescriptions,
  getJobsStatus,
  getTrackedCompanies,
  removeTrackedCompany,
  scanAtsCompanies,
  setTrackedCompanyEnabled,
} from "../api";
import { ATS_SOURCES, type AtsCandidate, type AtsSource, type TrackedCompany } from "../types";
import { google } from "../theme";
import { parseIsoDate } from "../dates";

const key = (c: { source: string; job_id: string }) => `${c.source}:${c.job_id}`;

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = parseIsoDate(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function AtsCaptureView() {
  const [companies, setCompanies] = useState<TrackedCompany[]>([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [companiesError, setCompaniesError] = useState<string | null>(null);

  const [newCompany, setNewCompany] = useState("");
  const [newSource, setNewSource] = useState<AtsSource>("greenhouse");
  const [newToken, setNewToken] = useState("");
  const [adding, setAdding] = useState(false);

  const [candidates, setCandidates] = useState<AtsCandidate[]>([]);
  const [scanMeta, setScanMeta] = useState<{
    companies_scanned: number;
    companies_failed: Record<string, string>;
  } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [hasScanned, setHasScanned] = useState(false);

  const [companiesOpen, setCompaniesOpen] = useState(false);

  const [fetched, setFetched] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [fetching, setFetching] = useState(false);
  const [fetchNote, setFetchNote] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);

  const loadCompanies = useCallback(async () => {
    setCompaniesLoading(true);
    setCompaniesError(null);
    try {
      setCompanies(await getTrackedCompanies());
    } catch (err) {
      setCompaniesError(err instanceof Error ? err.message : "Could not load companies");
    } finally {
      setCompaniesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCompanies();
  }, [loadCompanies]);

  async function handleAddCompany() {
    if (!newCompany.trim() || !newToken.trim()) return;
    setAdding(true);
    setCompaniesError(null);
    try {
      await addTrackedCompany(newCompany.trim(), newSource, newToken.trim());
      setNewCompany("");
      setNewToken("");
      await loadCompanies();
    } catch (err) {
      setCompaniesError(err instanceof Error ? err.message : "Could not add company");
    } finally {
      setAdding(false);
    }
  }

  async function handleRemoveCompany(id: number) {
    setCompaniesError(null);
    try {
      await removeTrackedCompany(id);
      await loadCompanies();
    } catch (err) {
      setCompaniesError(err instanceof Error ? err.message : "Could not remove company");
    }
  }

  async function handleToggleCompany(company: TrackedCompany) {
    setCompanies((cs) =>
      cs.map((c) => (c.id === company.id ? { ...c, enabled: !c.enabled } : c)),
    );
    try {
      await setTrackedCompanyEnabled(company.id, !company.enabled);
    } catch (err) {
      setCompanies((cs) =>
        cs.map((c) => (c.id === company.id ? { ...c, enabled: company.enabled } : c)),
      );
      setCompaniesError(err instanceof Error ? err.message : "Could not update company");
    }
  }

  async function refreshFetchedStatus(forCandidates: AtsCandidate[]) {
    const bySource = new Map<AtsSource, string[]>();
    for (const c of forCandidates) {
      bySource.set(c.source, [...(bySource.get(c.source) ?? []), c.job_id]);
    }
    try {
      const sets = await Promise.all(
        [...bySource.entries()].map(async ([source, ids]) => {
          const ready = await getJobsStatus(ids, source);
          return [...ready].map((id) => `${source}:${id}`);
        }),
      );
      setFetched(new Set(sets.flat()));
    } catch {
      setFetched(new Set());
    }
  }

  async function handleScan() {
    setScanning(true);
    setError(null);
    setFetchNote(null);
    try {
      const report = await scanAtsCompanies();
      setCandidates(report.candidates);
      setScanMeta({
        companies_scanned: report.companies_scanned,
        companies_failed: report.companies_failed,
      });
      setSelected(new Set());
      await refreshFetchedStatus(report.candidates);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
      setCandidates([]);
      setScanMeta(null);
    } finally {
      setScanning(false);
      setHasScanned(true);
    }
  }

  function toggleRow(candidate: AtsCandidate) {
    const k = key(candidate);
    const next = new Set(selected);
    next.has(k) ? next.delete(k) : next.add(k);
    setSelected(next);
  }

  async function handleFetch() {
    const chosen = candidates.filter((c) => selected.has(key(c)));
    if (chosen.length === 0) return;

    setFetching(true);
    setFetchNote(null);
    setError(null);
    try {
      const bySource = new Map<AtsSource, { job_id: string; company: string }[]>();
      for (const c of chosen) {
        bySource.set(c.source, [
          ...(bySource.get(c.source) ?? []),
          { job_id: c.job_id, company: c.company },
        ]);
      }

      const reports = await Promise.all(
        [...bySource.entries()].map(([source, items]) => fetchAtsDescriptions(source, items)),
      );

      const totals = reports.reduce(
        (acc, r) => ({
          normalized: acc.normalized + r.counts.normalized,
          normalize_failed: acc.normalize_failed + r.counts.normalize_failed,
          failed: acc.failed + r.counts.failed,
          skipped: acc.skipped + r.counts.skipped,
        }),
        { normalized: 0, normalize_failed: 0, failed: 0, skipped: 0 },
      );
      const parts = [`${totals.normalized} ready`];
      if (totals.normalize_failed) parts.push(`${totals.normalize_failed} stored but not normalized`);
      if (totals.failed) parts.push(`${totals.failed} failed`);
      if (totals.skipped) parts.push(`${totals.skipped} already had one`);
      setFetchNote(parts.join(" · "));

      const firstProblem = reports
        .flatMap((r) => [...Object.values(r.failures), ...Object.values(r.normalize_failures)])
        .find(Boolean);
      if (firstProblem) setError(firstProblem);

      setSelected(new Set());
      await refreshFetchedStatus(candidates);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
    } finally {
      setFetching(false);
    }
  }

  const columns: ColumnDef<AtsCandidate>[] = useMemo(
    () => [
      {
        id: "select",
        label: "Fetch JD",
        width: 96,
        nowrap: true,
        render: (c) => (
          <Checkbox
            size="small"
            checked={fetched.has(key(c)) || selected.has(key(c))}
            disabled={fetched.has(key(c))}
            onChange={() => toggleRow(c)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
      },
      {
        id: "source",
        label: "Source",
        width: 100,
        nowrap: true,
        render: (c) => (
          <Chip size="small" variant="outlined" label={c.source} sx={{ textTransform: "capitalize" }} />
        ),
      },
      {
        id: "title",
        label: "Role",
        render: (c) => (
          <Link
            href={c.url}
            target="_blank"
            rel="noopener noreferrer"
            underline="hover"
            onClick={(e) => e.stopPropagation()}
            sx={{ color: google.blue, fontWeight: 500 }}
          >
            {c.title}
          </Link>
        ),
      },
      { id: "company", label: "Company", render: (c) => c.company },
      { id: "location", label: "Location", render: (c) => c.location || "—" },
      { id: "posted_at", label: "Posted", width: 100, nowrap: true, render: (c) => formatDate(c.posted_at) },
    ],
    [fetched, selected],
  );

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        ATS Boards
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Scan tracked companies' Greenhouse, Ashby, and Lever boards for open roles, independent of
        LinkedIn's mailbox capture.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 3, borderColor: google.border, borderRadius: 2 }}>
        <Stack
          direction="row"
          spacing={0.5}
          onClick={() => setCompaniesOpen((v) => !v)}
          sx={{ alignItems: "center", cursor: "pointer", mb: companiesOpen ? 1.5 : 0 }}
        >
          <IconButton size="small" aria-label={companiesOpen ? "Collapse" : "Expand"}>
            {companiesOpen ? (
              <KeyboardArrowDownIcon fontSize="small" />
            ) : (
              <KeyboardArrowRightIcon fontSize="small" />
            )}
          </IconButton>
          <Typography variant="subtitle2">Tracked companies</Typography>
          {!companiesLoading && (
            <Typography variant="caption" color="text.secondary">
              ({companies.length})
            </Typography>
          )}
        </Stack>

        <Collapse in={companiesOpen} timeout="auto" unmountOnExit>
          {companiesError && (
            <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
              {companiesError}
            </Alert>
          )}

          <Stack direction="row" spacing={1.5} sx={{ mb: 2, flexWrap: "wrap", alignItems: "flex-start" }}>
            <TextField
              size="small"
              label="Company"
              value={newCompany}
              onChange={(e) => setNewCompany(e.target.value)}
              sx={{ minWidth: 160 }}
            />
            <TextField
              select
              size="small"
              label="Source"
              value={newSource}
              onChange={(e) => setNewSource(e.target.value as AtsSource)}
              sx={{ minWidth: 130 }}
            >
              {ATS_SOURCES.map((s) => (
                <MenuItem key={s} value={s} sx={{ textTransform: "capitalize" }}>
                  {s}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              label="Board token"
              value={newToken}
              onChange={(e) => setNewToken(e.target.value)}
              helperText="e.g. duolingo, Profound, spotify"
              sx={{ minWidth: 160 }}
            />
            <Button
              variant="contained"
              size="small"
              startIcon={adding ? <CircularProgress size={14} color="inherit" /> : <AddIcon />}
              onClick={() => void handleAddCompany()}
              disabled={adding || !newCompany.trim() || !newToken.trim()}
            >
              Add
            </Button>
          </Stack>

          {companiesLoading ? (
            <CircularProgress size={20} />
          ) : companies.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No companies tracked yet.
            </Typography>
          ) : (
            <TableContainer sx={{ overflowX: "auto" }}>
              <Table size="small" sx={{ minWidth: 560 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Company</TableCell>
                    <TableCell width={110}>Source</TableCell>
                    <TableCell>Board token</TableCell>
                    <TableCell width={90} align="center">
                      Enabled
                    </TableCell>
                    <TableCell width={60} />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {companies.map((c) => (
                    <TableRow key={c.id} hover>
                      <TableCell sx={{ fontWeight: 500 }}>{c.company}</TableCell>
                      <TableCell sx={{ textTransform: "capitalize" }}>{c.source}</TableCell>
                      <TableCell sx={{ color: google.textSecondary }}>{c.board_token}</TableCell>
                      <TableCell align="center">
                        <Switch
                          size="small"
                          checked={c.enabled}
                          onChange={() => void handleToggleCompany(c)}
                        />
                      </TableCell>
                      <TableCell align="center">
                        <IconButton size="small" onClick={() => void handleRemoveCompany(c.id)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Collapse>
      </Paper>

      <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 2, flexWrap: "wrap" }}>
        <Tooltip title="Sequentially checks every enabled company's board for roles matching the tracked keyword and location list, posted in the last 3 days.">
          <span>
            <Button
              variant="contained"
              onClick={() => void handleScan()}
              disabled={scanning || companies.filter((c) => c.enabled).length === 0}
              startIcon={
                scanning ? <CircularProgress size={16} color="inherit" /> : <SearchIcon />
              }
            >
              {scanning ? "Scanning…" : "Scan now"}
            </Button>
          </span>
        </Tooltip>

        {candidates.length > 0 && (
          <Tooltip title="Fetches the full description for each ticked role and runs it through normalization.">
            <span>
              <Button
                variant="outlined"
                onClick={() => void handleFetch()}
                disabled={selected.size === 0 || fetching}
                startIcon={
                  fetching ? <CircularProgress size={16} color="inherit" /> : <DownloadIcon />
                }
              >
                {fetching ? "Fetching…" : `Fetch JD${selected.size ? ` (${selected.size})` : ""}`}
              </Button>
            </span>
          </Tooltip>
        )}

        {fetchNote && !fetching && <Chip size="small" variant="outlined" label={fetchNote} />}

        {scanMeta && !scanning && (
          <Chip
            size="small"
            label={`${candidates.length} matches from ${scanMeta.companies_scanned} companies`}
            sx={{ backgroundColor: google.blueSurface, color: google.blue }}
          />
        )}
      </Stack>

      {scanMeta && Object.keys(scanMeta.companies_failed).length > 0 && (
        <Alert severity="warning" sx={{ mb: 2, borderRadius: 2 }}>
          Could not scan: {Object.entries(scanMeta.companies_failed).map(([c, e]) => `${c} (${e})`).join(", ")}
        </Alert>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {hasScanned && !error && candidates.length === 0 && !scanning && (
        <Paper
          variant="outlined"
          sx={{ p: 6, textAlign: "center", borderColor: google.border, borderRadius: 2 }}
        >
          <Typography color="text.secondary">
            No matching roles found across the tracked companies right now.
          </Typography>
        </Paper>
      )}

      {candidates.length > 0 && (
        <ExpandableTable
          rows={candidates}
          columns={columns}
          rowKey={key}
          minWidth={950}
          expanded={(c) => (
            <Typography variant="caption" color="text.secondary">
              {c.url}
            </Typography>
          )}
        />
      )}
    </Box>
  );
}
