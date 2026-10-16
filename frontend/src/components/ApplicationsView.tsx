import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  Paper,
  Stack,
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
import EditIcon from "@mui/icons-material/EditOutlined";
import CheckIcon from "@mui/icons-material/Check";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowRightIcon from "@mui/icons-material/KeyboardArrowRight";
import {
  ROLE_CATEGORIES,
  ROUND_LABELS,
  ROUND_LADDER,
  needsBackfill,
  type Application,
  type ResumeForApplication,
  type Round,
} from "../types";
import { google } from "../theme";
import { ROLE_COLORS } from "../colors";
import { parseIsoDate } from "../dates";
import { useApplicationsData, type EditableField } from "../applicationsContext";
import { getResumeForApplication } from "../api";
import ChipSelect, { type ChipOption } from "./ChipSelect";
import MaskedText from "./MaskedText";
import { useSlotLabels } from "../slots";
import CopyButton, { showCopyOnHover } from "./CopyButton";

// Ordinal ramp — one hue (blue), light to dark, more progress reads darker.
// Steps 250/300/400/500/600/700 from the dataviz skill's documented blue
// sequential ramp; an ordinal mark must clear a 2:1 floor at its lightest
// step, which is exactly step 250 — nothing lighter is used.
const ROUND_COLORS: Record<Round, { color: string; textColor?: string }> = {
  // Applied is the starting rung, not progress yet — no fill, just the label.
  applied: { color: "transparent", textColor: google.textPrimary },
  phone_screen: { color: "#6da7ec", textColor: google.textPrimary },
  interview: { color: "#3987e5" },
  final_round: { color: "#256abf" },
  offer: { color: "#184f95" },
  accepted: { color: "#0d366b" },
};

const ROUND_OPTIONS: ChipOption[] = ROUND_LADDER.map((r) => ({
  value: r,
  label: ROUND_LABELS[r],
  color: ROUND_COLORS[r].color,
  textColor: ROUND_COLORS[r].textColor,
}));

const ROLE_OPTIONS: ChipOption[] = ROLE_CATEGORIES.map((r) => ({
  value: r,
  label: r,
  color: ROLE_COLORS[r].color,
  textColor: ROLE_COLORS[r].textColor,
}));

// Mirrors STATUS_FROM_PROGRESS in applications_service.py — the values the
// backend actually writes. Not enforced server-side, unlike highest_round and
// role, since status has no invalid-value risk from free text like referral.
const STATUS_OPTIONS = ["not_started", "applied", "rejected", "withdrawn", "offer", "accepted"];

// applied/rejected use Tableau 10's blue and red.
const STATUS_COLORS: Record<string, { color: string; textColor?: string }> = {
  not_started: { color: google.border, textColor: google.textPrimary },
  applied: { color: "#4e79a7" },
  rejected: { color: "#e15759" },
  withdrawn: { color: google.textSecondary },
  offer: { color: "#188038" },
  accepted: { color: "#188038" },
};

const STATUS_CHIP_OPTIONS: ChipOption[] = STATUS_OPTIONS.map((s) => ({
  value: s,
  label: s.replace(/_/g, " "),
  color: STATUS_COLORS[s]?.color ?? google.border,
  textColor: STATUS_COLORS[s]?.textColor,
}));

/** A legacy value outside the enum (e.g. role "Strategist") still renders as
 * its own option so it is not silently blanked, same guard the old plain
 * Selects had. */
function withLegacy(options: ChipOption[], value: string | null): ChipOption[] {
  if (!value || options.some((o) => o.value === value)) return options;
  return [...options, { value, label: value.replace(/_/g, " "), color: google.border, textColor: google.textPrimary }];
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = parseIsoDate(iso);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

interface Props {
  sub: "needs" | "all";
}

export default function ApplicationsView({ sub }: Props) {
  const { applications: rows, summary, loading, error, saving, refresh, setField, setReferral } =
    useApplicationsData();
  // Which rows the Needs Backfill queue is showing, only ever narrowed by an
  // explicit Submit — not re-derived from needsBackfill() on every render, or
  // a row would vanish the instant its last field was picked, mid-edit,
  // before Referral or a final check.
  const [queueIds, setQueueIds] = useState<Set<number>>(new Set());

  // This view unmounts when you navigate away, so this runs fresh every time
  // you arrive at either Needs Backfill or All Applications.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Grows the queue with any row that newly needs backfill (a fresh Apply, a
  // background poll finding one from another tab) without ever evicting one
  // already in it — that only happens via an explicit Submit.
  useEffect(() => {
    setQueueIds((ids) => {
      const next = new Set(ids);
      for (const row of rows) {
        if (needsBackfill(row)) next.add(row.id);
      }
      return next;
    });
  }, [rows]);

  const needsRows = useMemo(() => rows.filter((r) => queueIds.has(r.id)), [rows, queueIds]);

  function submitRow(rowId: number) {
    setQueueIds((ids) => {
      const next = new Set(ids);
      next.delete(rowId);
      return next;
    });
  }

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        {sub === "needs" ? "Needs Backfill" : "All Applications"}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {sub === "needs"
          ? "New applications land here first — pick a Role, add a referral if there was one, and give the rest a quick check. Press Submit (or Enter in Referral) when it is ready."
          : "Imported from Notion. This is now the system of record — edits here do not write back."}
      </Typography>

      {summary && (
        <Paper variant="outlined" sx={{ p: 2, mb: 3, borderColor: google.border, borderRadius: 2 }}>
          <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
            <Chip size="small" label={`${summary.total} applications`} />
            <Chip
              size="small"
              label={`${summary.known} with a known outcome`}
              sx={{ backgroundColor: google.blueSurface, color: google.blue }}
            />
            {summary.needs_backfill > 0 && (
              <Chip size="small" variant="outlined" label={`${summary.needs_backfill} unknown`} />
            )}
            {summary.response_rate_of_known !== null && (
              <Tooltip title="Share of applications with a KNOWN outcome that got past the application stage. Not a rate over all applications — the unknowns are excluded, not counted as failures.">
                <Chip
                  size="small"
                  variant="outlined"
                  label={`${summary.response_rate_of_known}% got past applied (of known)`}
                />
              </Tooltip>
            )}
          </Stack>
        </Paper>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {loading && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
          <CircularProgress size={20} />
        </Box>
      )}

      {!loading && sub === "needs" && (
        <NeedsBackfillQueue
          rows={needsRows}
          saving={saving}
          setField={setField}
          setReferral={setReferral}
          onSubmit={submitRow}
        />
      )}

      {!loading && sub === "all" && (
        <AllApplicationsTable rows={rows} saving={saving} setField={setField} setReferral={setReferral} />
      )}
    </Box>
  );
}

// ------------------------------------------------------------- Needs Backfill

interface NeedsBackfillQueueProps {
  rows: Application[];
  saving: number | null;
  setField: <K extends EditableField>(row: Application, key: K, value: Application[K]) => Promise<void>;
  setReferral: (row: Application, referral: string) => Promise<void>;
  onSubmit: (rowId: number) => void;
}

function NeedsBackfillQueue({ rows, saving, setField, setReferral, onSubmit }: NeedsBackfillQueueProps) {
  const referralRefs = useRef(new Map<number, HTMLInputElement>());

  function focusNextAfter(rowId: number) {
    const index = rows.findIndex((r) => r.id === rowId);
    const next = rows[index + 1];
    if (next) referralRefs.current.get(next.id)?.focus();
  }

  if (rows.length === 0) {
    return (
      <Paper variant="outlined" sx={{ p: 6, textAlign: "center", borderColor: google.border, borderRadius: 2 }}>
        <Typography color="text.secondary">Nothing to backfill — every application has a Role and a known outcome.</Typography>
      </Paper>
    );
  }

  return (
    <Stack spacing={2}>
      {rows.map((row) => (
        <NeedsBackfillCard
          key={row.id}
          row={row}
          saving={saving}
          setField={setField}
          setReferral={setReferral}
          registerReferralRef={(el) => {
            if (el) referralRefs.current.set(row.id, el);
            else referralRefs.current.delete(row.id);
          }}
          onSubmit={() => {
            onSubmit(row.id);
            focusNextAfter(row.id);
          }}
        />
      ))}
    </Stack>
  );
}

interface NeedsBackfillCardProps {
  row: Application;
  saving: number | null;
  setField: NeedsBackfillQueueProps["setField"];
  setReferral: NeedsBackfillQueueProps["setReferral"];
  registerReferralRef: (el: HTMLInputElement | null) => void;
  /** Commits the row and advances the queue — only once Role is set. */
  onSubmit: () => void;
}

function NeedsBackfillCard({
  row,
  saving,
  setField,
  setReferral,
  registerReferralRef,
  onSubmit,
}: NeedsBackfillCardProps) {
  // Local until blur/Enter, same as the old table did — a full reload on
  // failure is simpler than tracking a pre-edit snapshot for this field.
  // Seeded once: reference changes on this row from other fields saving
  // (setField replaces the row object) must not clobber what is being typed.
  const [referral, setReferralText] = useState(row.referral ?? "");
  const canSubmit = !!row.role && saving !== row.id;

  function trySubmit(latestReferral: string) {
    void setReferral(row, latestReferral);
    // Referral is genuinely optional, but Role is not — Enter or Submit
    // without a Role picked just commits the referral text and stays put.
    if (canSubmit) onSubmit();
  }

  return (
    <Paper variant="outlined" sx={{ p: 2.5, borderColor: google.border, borderRadius: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "baseline", mb: 2, flexWrap: "wrap" }}>
        <Typography sx={{ fontWeight: 500 }}>{row.company}</Typography>
        <Typography color="text.secondary">{row.title}</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ ml: "auto !important" }}>
          Applied {formatDate(row.applied_at)}
        </Typography>
      </Stack>

      <Stack direction="row" spacing={2} sx={{ mb: 2, flexWrap: "wrap" }}>
        <Box sx={{ minWidth: 220 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            Role
          </Typography>
          <ChipSelect
            value={row.role ?? ""}
            options={withLegacy(ROLE_OPTIONS, row.role)}
            disabled={saving === row.id}
            emptyLabel="Pick a role"
            onChange={(v) => void setField(row, "role", (v || null) as Application["role"])}
          />
        </Box>
        <Box sx={{ minWidth: 220 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            Referral (optional)
          </Typography>
          <TextField
            size="small"
            fullWidth
            placeholder="—"
            value={referral}
            disabled={saving === row.id}
            inputRef={registerReferralRef}
            onChange={(e) => setReferralText(e.target.value)}
            onBlur={(e) => void setReferral(row, e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              e.preventDefault();
              trySubmit((e.target as HTMLInputElement).value);
            }}
          />
        </Box>
      </Stack>

      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Final check
      </Typography>
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
        <Box sx={{ minWidth: 160 }}>
          <ChipSelect
            value={row.status}
            options={withLegacy(STATUS_CHIP_OPTIONS, row.status)}
            disabled={saving === row.id}
            onChange={(v) => void setField(row, "status", v)}
          />
        </Box>
        <Box sx={{ minWidth: 160 }}>
          <ChipSelect
            value={row.highest_round ?? ""}
            options={ROUND_OPTIONS}
            disabled={saving === row.id}
            emptyLabel="Unknown"
            onChange={(v) => void setField(row, "highest_round", (v || null) as Round | null)}
          />
        </Box>
        <TextField
          type="date"
          size="small"
          value={row.applied_at ?? ""}
          disabled={saving === row.id}
          onChange={(e) => void setField(row, "applied_at", e.target.value || null)}
        />
      </Stack>

      <Box sx={{ display: "flex", justifyContent: "flex-end", mt: 2 }}>
        <Tooltip title={row.role ? "" : "Pick a Role first"}>
          <span>
            <Button variant="contained" size="small" disabled={!canSubmit} onClick={() => trySubmit(referral)}>
              Submit
            </Button>
          </span>
        </Tooltip>
      </Box>
    </Paper>
  );
}

// ----------------------------------------------------------- All Applications

interface AllApplicationsTableProps {
  rows: Application[];
  saving: number | null;
  setField: <K extends EditableField>(row: Application, key: K, value: Application[K]) => Promise<void>;
  setReferral: (row: Application, referral: string) => Promise<void>;
}

/** Read-only equivalent of ChipSelect's closed state — every row pays for
 * this; only the one row being edited pays for a real Select. */
function StaticChip({ value, options, emptyLabel }: { value: string; options: ChipOption[]; emptyLabel?: string }) {
  const opt = options.find((o) => o.value === value);
  if (!opt) {
    return emptyLabel ? (
      <Chip
        size="small"
        label={emptyLabel}
        sx={{ backgroundColor: google.background, color: google.textSecondary, fontWeight: 600 }}
      />
    ) : (
      <Box component="span" sx={{ color: google.border }}>—</Box>
    );
  }
  return (
    <Chip
      size="small"
      label={opt.label}
      sx={{ backgroundColor: opt.color, color: opt.textColor ?? "#fff", fontWeight: 600 }}
    />
  );
}

/** Mounts fresh (and so re-seeds its local value) each time a row enters
 * edit mode, since it only exists in the tree while editing is true. */
function EditableTextCell({
  initial,
  onCommit,
  disabled,
}: {
  initial: string;
  onCommit: (value: string) => void;
  disabled?: boolean;
}) {
  const [value, setValue] = useState(initial);
  return (
    <TextField
      size="small"
      fullWidth
      value={value}
      disabled={disabled}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => onCommit(value)}
    />
  );
}

function ResumePanel({ entry }: { entry: ResumeForApplication | null | "loading" | undefined }) {
  // Before the early returns below: hooks must run on every render.
  const SLOT_LABELS = useSlotLabels();
  if (entry === undefined || entry === "loading") {
    return <CircularProgress size={18} />;
  }
  if (entry === null) {
    return (
      <Typography color="text.secondary" variant="body2">
        No resume on file yet — attach one from Applications → Upload Resumes.
      </Typography>
    );
  }
  return (
    <Stack spacing={1.5} sx={{ maxWidth: 760 }}>
      {entry.headline && (
        <Typography variant="body2" sx={{ fontStyle: "italic", color: google.textSecondary }}>
          {entry.headline}
        </Typography>
      )}
      {entry.sections.map((section) => (
        <Box key={section.slot}>
          {section.header && (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
              {SLOT_LABELS[section.slot] ?? section.slot}
            </Typography>
          )}
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {section.header ?? SLOT_LABELS[section.slot] ?? section.slot}
          </Typography>
          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
            {section.bullets.map((bullet, i) => (
              <Typography key={i} component="li" variant="body2" sx={showCopyOnHover}>
                {bullet}
                <CopyButton text={bullet} />
              </Typography>
            ))}
          </Box>
        </Box>
      ))}
    </Stack>
  );
}

function AllApplicationsTable({ rows, saving, setField, setReferral }: AllApplicationsTableProps) {
  // Only this row, if any, renders real editable controls — every other row
  // stays plain text/static chips, which is what actually keeps the table
  // fast at this row count.
  const [editingId, setEditingId] = useState<number | null>(null);

  // Click a row to see its resume below it. Fetched once per row and kept
  // around rather than refetched on every re-open — a row's resume doesn't
  // change while you're browsing the table.
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [resumeCache, setResumeCache] = useState<Record<number, ResumeForApplication | null | "loading">>({});

  function toggleExpanded(row: Application) {
    if (editingId === row.id) return; // mid-edit: row clicks shouldn't fight the edit fields
    if (expandedId === row.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(row.id);
    if (resumeCache[row.id] === undefined) {
      setResumeCache((current) => ({ ...current, [row.id]: "loading" }));
      getResumeForApplication(row.id)
        .then((resume) => setResumeCache((current) => ({ ...current, [row.id]: resume })))
        .catch(() => setResumeCache((current) => ({ ...current, [row.id]: null })));
    }
  }

  return (
    <TableContainer component={Paper} variant="outlined" sx={{ borderColor: google.border, borderRadius: 2, overflowX: "auto" }}>
      <Table size="small" sx={{ minWidth: 1120 }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: 40, px: 0.5 }} />
            <TableCell sx={{ width: 40, px: 0.5 }} />
            <TableCell sx={{ width: 130, whiteSpace: "nowrap" }}>Applied</TableCell>
            <TableCell sx={{ width: 160 }}>Company</TableCell>
            <TableCell>Title</TableCell>
            <TableCell sx={{ width: 190 }}>Role</TableCell>
            <TableCell sx={{ width: 150 }}>Status</TableCell>
            <TableCell sx={{ width: 175 }}>
              <Tooltip title="How far this actually got — not where it ended up">
                <span>Highest round</span>
              </Tooltip>
            </TableCell>
            <TableCell sx={{ width: 150 }}>Referral</TableCell>
          </TableRow>
        </TableHead>

        <TableBody>
          {rows.map((row) => {
            const editing = editingId === row.id;
            const isSaving = saving === row.id;
            const isExpanded = expandedId === row.id;
            return (
              <Fragment key={row.id}>
              <TableRow
                hover
                onClick={() => toggleExpanded(row)}
                sx={{
                  cursor: "pointer",
                  "&:last-child td": { border: isExpanded ? undefined : 0 },
                  "&:hover .row-edit-icon": { opacity: 1 },
                }}
              >
                <TableCell sx={{ width: 40, px: 0.5 }}>
                  <IconButton size="small" aria-label={isExpanded ? "Collapse" : "Expand"}>
                    {isExpanded ? (
                      <KeyboardArrowDownIcon fontSize="small" />
                    ) : (
                      <KeyboardArrowRightIcon fontSize="small" />
                    )}
                  </IconButton>
                </TableCell>
                <TableCell sx={{ width: 40, px: 0.5 }}>
                  <IconButton
                    size="small"
                    className="row-edit-icon"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditingId(editing ? null : row.id);
                    }}
                    sx={{ opacity: editing ? 1 : 0, transition: "opacity 0.15s" }}
                  >
                    {editing ? <CheckIcon fontSize="small" /> : <EditIcon fontSize="small" />}
                  </IconButton>
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap", color: google.textSecondary }}>
                  {editing ? (
                    <TextField
                      type="date"
                      size="small"
                      value={row.applied_at ?? ""}
                      disabled={isSaving}
                      onChange={(e) => void setField(row, "applied_at", e.target.value || null)}
                    />
                  ) : (
                    formatDate(row.applied_at)
                  )}
                </TableCell>
                <TableCell sx={{ fontWeight: 500 }}>
                  {editing ? (
                    <EditableTextCell
                      initial={row.company}
                      disabled={isSaving}
                      onCommit={(v) => void setField(row, "company", v)}
                    />
                  ) : (
                    <MaskedText>{row.company}</MaskedText>
                  )}
                </TableCell>
                <TableCell>
                  {editing ? (
                    <EditableTextCell
                      initial={row.title}
                      disabled={isSaving}
                      onCommit={(v) => void setField(row, "title", v)}
                    />
                  ) : (
                    <MaskedText>{row.title}</MaskedText>
                  )}
                </TableCell>
                <TableCell>
                  {editing ? (
                    <ChipSelect
                      value={row.role ?? ""}
                      options={withLegacy(ROLE_OPTIONS, row.role)}
                      disabled={isSaving}
                      emptyLabel="Pick a role"
                      onChange={(v) => void setField(row, "role", (v || null) as Application["role"])}
                    />
                  ) : row.role ? (
                    <Chip
                      size="small"
                      label={<MaskedText>{row.role}</MaskedText>}
                      sx={{
                        backgroundColor: ROLE_COLORS[row.role]?.color ?? google.border,
                        color: ROLE_COLORS[row.role]?.textColor ?? "#fff",
                        fontWeight: 600,
                      }}
                    />
                  ) : (
                    <Box component="span" sx={{ color: google.border }}>—</Box>
                  )}
                </TableCell>
                <TableCell>
                  {editing ? (
                    <ChipSelect
                      value={row.status}
                      options={withLegacy(STATUS_CHIP_OPTIONS, row.status)}
                      disabled={isSaving}
                      onChange={(v) => void setField(row, "status", v)}
                    />
                  ) : (
                    <StaticChip value={row.status} options={withLegacy(STATUS_CHIP_OPTIONS, row.status)} />
                  )}
                </TableCell>
                <TableCell>
                  {editing ? (
                    <ChipSelect
                      value={row.highest_round ?? ""}
                      options={ROUND_OPTIONS}
                      disabled={isSaving}
                      emptyLabel="Unknown"
                      onChange={(v) => void setField(row, "highest_round", (v || null) as Round | null)}
                    />
                  ) : (
                    <StaticChip value={row.highest_round ?? ""} options={ROUND_OPTIONS} emptyLabel="Unknown" />
                  )}
                </TableCell>
                <TableCell sx={{ color: google.textSecondary }}>
                  {editing ? (
                    <EditableTextCell
                      initial={row.referral ?? ""}
                      disabled={isSaving}
                      onCommit={(v) => void setReferral(row, v)}
                    />
                  ) : row.referral ? (
                    <MaskedText>{row.referral}</MaskedText>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>

              <TableRow>
                <TableCell colSpan={9} sx={{ py: 0, borderBottom: isExpanded ? undefined : 0 }}>
                  <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                    <Box sx={{ py: 2, px: 2, backgroundColor: google.background }}>
                      <ResumePanel entry={resumeCache[row.id]} />
                    </Box>
                  </Collapse>
                </TableCell>
              </TableRow>
              </Fragment>
            );
          })}
        </TableBody>
      </Table>

      {rows.length === 0 && (
        <Box sx={{ p: 6, textAlign: "center" }}>
          <Typography color="text.secondary">No applications imported yet.</Typography>
        </Box>
      )}
    </TableContainer>
  );
}
