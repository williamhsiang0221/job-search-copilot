import { useRef, useState } from "react";
import { Alert, Box, Button, CircularProgress, Paper, Stack, TextField, Typography } from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { uploadJobPdf } from "../api";
import { google } from "../theme";

export default function PdfCaptureView() {
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canSubmit = !!company.trim() && !!title.trim() && !!file && !uploading;

  async function handleSubmit() {
    if (!file) return;
    setUploading(true);
    setError(null);
    setNote(null);
    try {
      const report = await uploadJobPdf(company.trim(), title.trim(), file, url.trim() || undefined);
      if (report.counts.normalized > 0) {
        setNote(`Stored and normalized — it's in the Normalized tab now.`);
      } else if (report.counts.stored > 0) {
        const reason = Object.values(report.normalize_failures)[0];
        setNote(`Stored, but normalization failed${reason ? `: ${reason}` : ""}. It's in Raw and can be retried later.`);
      }
      setCompany("");
      setTitle("");
      setUrl("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        PDF Upload
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        For postings with no ATS behind them — save the job page as a PDF and upload it here. The text
        is extracted and normalized the same way as every other source, then follows the rest of the
        workflow from the Normalized tab.
      </Typography>

      <Paper variant="outlined" sx={{ p: 3, maxWidth: 480, borderColor: google.border, borderRadius: 2 }}>
        <Stack spacing={2}>
          <TextField
            label="Company"
            size="small"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            disabled={uploading}
            fullWidth
          />
          <TextField
            label="Title"
            size="small"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={uploading}
            fullWidth
          />
          <TextField
            label="URL (optional)"
            size="small"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={uploading}
            fullWidth
          />

          <Button
            component="label"
            variant="outlined"
            startIcon={<UploadFileIcon />}
            disabled={uploading}
            sx={{ justifyContent: "flex-start" }}
          >
            {file ? file.name : "Choose PDF"}
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf"
              hidden
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Button>

          {error && (
            <Alert severity="error" sx={{ borderRadius: 2 }}>
              {error}
            </Alert>
          )}
          {note && (
            <Alert severity="success" sx={{ borderRadius: 2 }}>
              {note}
            </Alert>
          )}

          <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
            <Button
              variant="contained"
              disabled={!canSubmit}
              startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : undefined}
              onClick={() => void handleSubmit()}
            >
              {uploading ? "Uploading…" : "Upload"}
            </Button>
          </Box>
        </Stack>
      </Paper>
    </Box>
  );
}
