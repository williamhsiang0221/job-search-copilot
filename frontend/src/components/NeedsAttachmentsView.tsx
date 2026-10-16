import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
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
import DescriptionIcon from "@mui/icons-material/Description";
import AssignmentIndIcon from "@mui/icons-material/AssignmentInd";
import { attachPdfToApplication, attachResumeToApplication, getApplicationsNeedingAttachments } from "../api";
import type { ApplicationNeedingAttachments } from "../types";
import { google } from "../theme";
import { parseIsoDate } from "../dates";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return parseIsoDate(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

interface RowProps {
  row: ApplicationNeedingAttachments;
  onJdAttached: (id: number) => void;
  onResumeAttached: (id: number) => void;
}

function NeedsAttachmentsRow({ row, onJdAttached, onResumeAttached }: RowProps) {
  const [jdUploading, setJdUploading] = useState(false);
  const [jdError, setJdError] = useState<string | null>(null);
  const [resumeUploading, setResumeUploading] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);

  async function handleJdFile(file: File | undefined) {
    if (!file) return;
    setJdUploading(true);
    setJdError(null);
    try {
      const report = await attachPdfToApplication(row.id, file);
      if (report.counts.stored > 0) {
        onJdAttached(row.id);
      } else {
        setJdError(Object.values(report.failures)[0] ?? "could not extract text from this PDF");
      }
    } catch (err) {
      setJdError(err instanceof Error ? err.message : "Attach failed");
    } finally {
      setJdUploading(false);
    }
  }

  async function handleResumeFile(file: File | undefined) {
    if (!file) return;
    setResumeUploading(true);
    setResumeError(null);
    try {
      await attachResumeToApplication(row.id, file);
      onResumeAttached(row.id);
    } catch (err) {
      setResumeError(err instanceof Error ? err.message : "Attach failed");
    } finally {
      setResumeUploading(false);
    }
  }

  return (
    <TableRow hover>
      <TableCell>{row.company}</TableCell>
      <TableCell>{row.title}</TableCell>
      <TableCell sx={{ color: google.textSecondary, whiteSpace: "nowrap" }}>
        {formatDate(row.applied_at) || "—"}
      </TableCell>
      <TableCell align="right">
        <Stack direction="row" spacing={1} sx={{ justifyContent: "flex-end", alignItems: "flex-start" }}>
          {row.needs_jd && (
            <Box>
              {jdError && (
                <Typography variant="caption" color="error" sx={{ display: "block", mb: 0.5 }}>
                  {jdError}
                </Typography>
              )}
              <Button
                component="label"
                size="small"
                variant="outlined"
                disabled={jdUploading}
                startIcon={jdUploading ? <CircularProgress size={14} /> : <DescriptionIcon fontSize="small" />}
              >
                {jdUploading ? "Uploading…" : "Attach JD"}
                <input
                  type="file"
                  accept="application/pdf"
                  hidden
                  onChange={(e) => void handleJdFile(e.target.files?.[0])}
                />
              </Button>
            </Box>
          )}
          {row.needs_resume && (
            <Box>
              {resumeError && (
                <Typography variant="caption" color="error" sx={{ display: "block", mb: 0.5 }}>
                  {resumeError}
                </Typography>
              )}
              <Button
                component="label"
                size="small"
                variant="outlined"
                disabled={resumeUploading}
                startIcon={resumeUploading ? <CircularProgress size={14} /> : <AssignmentIndIcon fontSize="small" />}
              >
                {resumeUploading ? "Uploading…" : "Attach resume"}
                <input
                  type="file"
                  accept="application/pdf"
                  hidden
                  onChange={(e) => void handleResumeFile(e.target.files?.[0])}
                />
              </Button>
            </Box>
          )}
        </Stack>
      </TableCell>
    </TableRow>
  );
}

/** Merged worklist: applications missing a JD, a resume, or both — replaces
 * what used to be two separate tabs (Link legacy JDs, Upload Resumes), since
 * the two gaps overlap on most legacy rows. A row shows only the action(s)
 * it still needs and drops out once both are satisfied. */
export default function NeedsAttachmentsView() {
  const [rows, setRows] = useState<ApplicationNeedingAttachments[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getApplicationsNeedingAttachments()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load"));
  }, []);

  function updateRow(id: number, patch: Partial<ApplicationNeedingAttachments>) {
    setRows((current) =>
      current
        ?.map((r) => (r.id === id ? { ...r, ...patch } : r))
        .filter((r) => r.needs_jd || r.needs_resume) ?? current,
    );
  }

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        Needs JD / Resume
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Applications missing a stored job description, a resume, or both — most predate this app. Attach
        whichever is still missing; a row drops off once both are on file.
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {rows === null && !error && <CircularProgress size={20} />}

      {rows !== null && rows.length === 0 && (
        <Paper variant="outlined" sx={{ p: 6, textAlign: "center", borderColor: google.border, borderRadius: 2 }}>
          <Typography color="text.secondary">Every application has both a JD and a resume on file.</Typography>
        </Paper>
      )}

      {rows !== null && rows.length > 0 && (
        <TableContainer component={Paper} variant="outlined" sx={{ borderColor: google.border, borderRadius: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Company</TableCell>
                <TableCell>Title</TableCell>
                <TableCell>Applied</TableCell>
                <TableCell align="right">{rows.length} remaining</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <NeedsAttachmentsRow
                  key={row.id}
                  row={row}
                  onJdAttached={(id) => updateRow(id, { needs_jd: false })}
                  onResumeAttached={(id) => updateRow(id, { needs_resume: false })}
                />
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
}
