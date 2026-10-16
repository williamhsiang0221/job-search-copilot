import { useMemo, useState } from "react";
import {
  Box,
  Checkbox,
  Chip,
  Link,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Tooltip,
} from "@mui/material";
import type { Role } from "../types";
import { google } from "../theme";

type SortableId = "job_id" | "title" | "company" | "location" | "match_count" | "received_at";
type Direction = "asc" | "desc";

interface Column {
  id: SortableId | "fetched";
  label: string;
  sortable: boolean;
  align?: "center";
  width?: number;
  /** Ghost columns have no data behind them yet. */
  ghost?: boolean;
  tooltip?: string;
}

const COLUMNS: Column[] = [
  { id: "job_id", label: "Job ID", sortable: true, width: 110 },
  { id: "title", label: "Role", sortable: true },
  { id: "company", label: "Company", sortable: true },
  { id: "location", label: "Location", sortable: true },
  {
    id: "match_count",
    label: "Alerts",
    sortable: true,
    align: "center",
    width: 80,
    tooltip: "How many of your alert emails included this job",
  },
  { id: "received_at", label: "Last seen", sortable: true, width: 150 },
];

// Selection lives in the leftmost column. A checked row is one whose
// description is already stored and normalized, so it is disabled: the check
// reports state and prevents a pointless refetch with the same control.
const FETCHED_WIDTH = 110;

// Job ID and Alerts are numbers stored as strings/ints; dates are UTC ISO, so
// they compare correctly as plain strings. Everything else is locale text —
// without which "10" would sort before "9".
const NUMERIC: SortableId[] = ["job_id", "match_count"];

function compare(a: Role, b: Role, key: SortableId): number {
  if (NUMERIC.includes(key)) {
    return Number(a[key]) - Number(b[key]);
  }
  const left = String(a[key] ?? "");
  const right = String(b[key] ?? "");
  if (key === "received_at") {
    return left.localeCompare(right); // ISO strings sort chronologically
  }
  return left.localeCompare(right, undefined, { sensitivity: "base" });
}

function formatSeen(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

interface Props {
  roles: Role[];
  /** Job ids whose descriptions are stored and normalized. */
  fetched: Set<string>;
  selected: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
}

export default function RolesTable({ roles, fetched, selected, onSelectionChange }: Props) {
  // Newest first: on a daily scan, today's arrivals belong at the top.
  const [orderBy, setOrderBy] = useState<SortableId>("received_at");
  const [direction, setDirection] = useState<Direction>("desc");

  const sorted = useMemo(() => {
    const copy = [...roles];
    copy.sort((a, b) => (direction === "asc" ? 1 : -1) * compare(a, b, orderBy));
    return copy;
  }, [roles, orderBy, direction]);

  const selectable = useMemo(
    () => sorted.filter((r) => !fetched.has(r.job_id)).map((r) => r.job_id),
    [sorted, fetched],
  );
  const allSelected = selectable.length > 0 && selectable.every((id) => selected.has(id));
  const someSelected = selectable.some((id) => selected.has(id));

  function toggleRow(jobId: string) {
    const next = new Set(selected);
    next.has(jobId) ? next.delete(jobId) : next.add(jobId);
    onSelectionChange(next);
  }

  function toggleAll() {
    // Select-all only ever touches rows that can actually be fetched.
    onSelectionChange(allSelected ? new Set() : new Set(selectable));
  }

  function handleSort(id: SortableId) {
    if (id === orderBy) {
      setDirection(direction === "asc" ? "desc" : "asc");
    } else {
      setOrderBy(id);
      // Dates and counts are most useful highest-first; text reads better A-Z.
      setDirection(id === "received_at" || id === "match_count" ? "desc" : "asc");
    }
  }

  return (
    <TableContainer
      component={Paper}
      variant="outlined"
      // Wide content scrolls inside its own container so the page never
      // scrolls sideways.
      sx={{ borderColor: google.border, borderRadius: 2, overflowX: "auto" }}
    >
      <Table size="small" sx={{ minWidth: 1000 }}>
        <TableHead>
          <TableRow>
            <TableCell padding="checkbox" sx={{ width: FETCHED_WIDTH, whiteSpace: "nowrap" }}>
              <Tooltip title="Select roles to fetch descriptions for. Checked rows are already stored.">
                <span>
                  <Checkbox
                    size="small"
                    checked={allSelected}
                    indeterminate={someSelected && !allSelected}
                    onChange={toggleAll}
                    disabled={selectable.length === 0}
                  />
                </span>
              </Tooltip>
              Fetched JD
            </TableCell>
            {COLUMNS.map((column) => {
              const header = column.tooltip ? (
                <Tooltip title={column.tooltip}>
                  <span>{column.label}</span>
                </Tooltip>
              ) : (
                column.label
              );

              return (
                <TableCell
                  key={column.id}
                  align={column.align}
                  sx={{ width: column.width, whiteSpace: "nowrap" }}
                  sortDirection={orderBy === column.id ? direction : false}
                >
                  {column.sortable ? (
                    <TableSortLabel
                      active={orderBy === column.id}
                      direction={orderBy === column.id ? direction : "asc"}
                      onClick={() => handleSort(column.id as SortableId)}
                    >
                      {header}
                    </TableSortLabel>
                  ) : (
                    header
                  )}
                </TableCell>
              );
            })}
          </TableRow>
        </TableHead>

        <TableBody>
          {sorted.map((role) => (
            <TableRow
              key={role.job_id}
              hover
              selected={selected.has(role.job_id)}
              sx={{ "&:last-child td": { border: 0 } }}
            >
              <TableCell padding="checkbox">
                <Checkbox
                  size="small"
                  checked={fetched.has(role.job_id) || selected.has(role.job_id)}
                  // Already stored: the check is status, not a control.
                  disabled={fetched.has(role.job_id)}
                  onChange={() => toggleRow(role.job_id)}
                />
              </TableCell>

              <TableCell sx={{ color: google.textSecondary, fontVariantNumeric: "tabular-nums" }}>
                {role.job_id}
              </TableCell>

              <TableCell sx={{ fontWeight: 500 }}>
                <Link
                  href={role.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  underline="hover"
                  sx={{ color: google.blue }}
                >
                  {role.title}
                </Link>
              </TableCell>

              <TableCell>{role.company}</TableCell>
              <TableCell sx={{ color: google.textSecondary }}>{role.location}</TableCell>

              <TableCell align="center">
                {role.match_count > 1 ? (
                  <Chip
                    size="small"
                    label={`${role.match_count}×`}
                    sx={{
                      height: 20,
                      fontSize: "0.75rem",
                      backgroundColor: google.blueSurface,
                      color: google.blue,
                    }}
                  />
                ) : (
                  <Box component="span" sx={{ color: google.border }}>
                    —
                  </Box>
                )}
              </TableCell>

              <TableCell sx={{ color: google.textSecondary, whiteSpace: "nowrap" }}>
                {formatSeen(role.received_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
