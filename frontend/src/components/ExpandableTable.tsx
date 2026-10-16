import { Fragment, useState, type ReactNode } from "react";
import {
  Box,
  Collapse,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Typography,
} from "@mui/material";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowRightIcon from "@mui/icons-material/KeyboardArrowRight";
import { google } from "../theme";

export interface ColumnDef<T> {
  id: string;
  label: string;
  render: (row: T) => ReactNode;
  width?: number;
  nowrap?: boolean;
  /** Present only on sortable columns. Null sorts to the bottom regardless
   * of direction — a missing value is never more useful to see first. */
  sortValue?: (row: T) => number | string | null;
  /** Which direction a first click on this column's header applies —
   * "desc" for a column where higher reads as better (e.g. a score). */
  defaultSortDirection?: "asc" | "desc";
}

// direction is applied inside here, not by the caller negating the result —
// negating a comparator that returns +-1 for "null goes last" would flip
// null placement along with everything else for a descending sort, which is
// not what "regardless of direction" is supposed to mean.
function compareSortValues(
  a: number | string | null,
  b: number | string | null,
  direction: "asc" | "desc",
): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  const cmp = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
  return direction === "asc" ? cmp : -cmp;
}

interface Props<T> {
  rows: T[];
  columns: ColumnDef<T>[];
  rowKey: (row: T) => string;
  /** Shown beneath a row when expanded. Long text belongs here, not in a cell. */
  expanded: (row: T) => ReactNode;
  minWidth?: number;
}

export default function ExpandableTable<T>({
  rows,
  columns,
  rowKey,
  expanded,
  minWidth = 1000,
}: Props<T>) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [orderBy, setOrderBy] = useState<string | null>(null);
  const [direction, setDirection] = useState<"asc" | "desc">("asc");

  function toggle(key: string) {
    const next = new Set(open);
    next.has(key) ? next.delete(key) : next.add(key);
    setOpen(next);
  }

  function handleSort(column: ColumnDef<T>) {
    if (column.id === orderBy) {
      setDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setOrderBy(column.id);
      setDirection(column.defaultSortDirection ?? "asc");
    }
  }

  const sortColumn = columns.find((c) => c.id === orderBy);
  const sortedRows =
    sortColumn?.sortValue == null
      ? rows
      : [...rows].sort((a, b) =>
          compareSortValues(sortColumn.sortValue!(a), sortColumn.sortValue!(b), direction),
        );

  return (
    <TableContainer
      component={Paper}
      variant="outlined"
      sx={{ borderColor: google.border, borderRadius: 2, overflowX: "auto" }}
    >
      <Table size="small" sx={{ minWidth }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: 44 }} />
            {columns.map((column) => (
              <TableCell
                key={column.id}
                sx={{ width: column.width, whiteSpace: "nowrap" }}
                sortDirection={orderBy === column.id ? direction : false}
              >
                {column.sortValue ? (
                  <TableSortLabel
                    active={orderBy === column.id}
                    direction={orderBy === column.id ? direction : (column.defaultSortDirection ?? "asc")}
                    onClick={() => handleSort(column)}
                  >
                    {column.label}
                  </TableSortLabel>
                ) : (
                  column.label
                )}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>

        <TableBody>
          {sortedRows.map((row) => {
            const key = rowKey(row);
            const isOpen = open.has(key);

            return (
              <Fragment key={key}>
                <TableRow
                  hover
                  onClick={() => toggle(key)}
                  sx={{ cursor: "pointer", "& > td": { borderBottom: isOpen ? 0 : undefined } }}
                >
                  <TableCell sx={{ width: 44 }}>
                    <IconButton size="small" aria-label={isOpen ? "Collapse" : "Expand"}>
                      {isOpen ? (
                        <KeyboardArrowDownIcon fontSize="small" />
                      ) : (
                        <KeyboardArrowRightIcon fontSize="small" />
                      )}
                    </IconButton>
                  </TableCell>

                  {columns.map((column) => (
                    <TableCell
                      key={column.id}
                      sx={{ whiteSpace: column.nowrap ? "nowrap" : undefined }}
                    >
                      {column.render(row)}
                    </TableCell>
                  ))}
                </TableRow>

                <TableRow>
                  <TableCell
                    colSpan={columns.length + 1}
                    sx={{ py: 0, borderBottom: isOpen ? undefined : 0 }}
                  >
                    <Collapse in={isOpen} timeout="auto" unmountOnExit>
                      <Box sx={{ py: 2, px: 1, backgroundColor: google.background }}>
                        {expanded(row)}
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
          <Typography color="text.secondary">Nothing stored yet.</Typography>
        </Box>
      )}
    </TableContainer>
  );
}
