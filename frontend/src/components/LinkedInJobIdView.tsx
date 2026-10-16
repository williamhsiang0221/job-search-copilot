import { useState } from "react";
import { Alert, Box, Button, Chip, CircularProgress, Paper, Stack, TextField, Typography } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import { fetchJobDescriptions } from "../api";
import { google } from "../theme";

// A pasted job ID is just digits. A pasted URL carries it as the last long
// digit run — "/jobs/view/4402752794/", a slug before it, or
// "?currentJobId=4402752794" as a query param all end the same way.
function extractJobId(input: string): string | null {
  const matches = input.match(/\d{6,}/g);
  return matches ? matches[matches.length - 1] : null;
}

export default function LinkedInJobIdView() {
  const [input, setInput] = useState("");
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const jobId = extractJobId(input);

  async function handleFetch() {
    if (!jobId) return;
    setFetching(true);
    setError(null);
    setNote(null);
    try {
      const report = await fetchJobDescriptions([jobId]);
      const { counts } = report;

      const parts = [`${counts.normalized} ready`];
      if (counts.normalize_failed) parts.push(`${counts.normalize_failed} stored but not normalized`);
      if (counts.failed) parts.push(`${counts.failed} failed`);
      if (counts.skipped) parts.push(`${counts.skipped} already had one`);
      setNote(parts.join(" · "));

      const firstProblem =
        Object.values(report.failures)[0] ?? Object.values(report.normalize_failures)[0];
      if (firstProblem) setError(firstProblem);
      else setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
    } finally {
      setFetching(false);
    }
  }

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        LinkedIn Job ID
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Found a role outside the alert emails? Paste its job ID or the LinkedIn URL and fetch it
        directly — same fetch-and-normalize pipeline as Job Alerts, just skipping the inbox scan.
      </Typography>

      <Paper variant="outlined" sx={{ p: 3, maxWidth: 480, borderColor: google.border, borderRadius: 2 }}>
        <Stack spacing={2}>
          <TextField
            label="Job ID or LinkedIn URL"
            size="small"
            placeholder="4402752794"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={fetching}
            fullWidth
            helperText={input && !jobId ? "No job id found in that text" : " "}
            error={!!input && !jobId}
          />

          {error && (
            <Alert severity="error" sx={{ borderRadius: 2 }}>
              {error}
            </Alert>
          )}
          {note && !fetching && <Chip size="small" variant="outlined" label={note} sx={{ alignSelf: "flex-start" }} />}

          <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
            <Button
              variant="contained"
              disabled={!jobId || fetching}
              startIcon={fetching ? <CircularProgress size={16} color="inherit" /> : <DownloadIcon />}
              onClick={() => void handleFetch()}
            >
              {fetching ? "Fetching…" : "Fetch"}
            </Button>
          </Box>
        </Stack>
      </Paper>
    </Box>
  );
}
