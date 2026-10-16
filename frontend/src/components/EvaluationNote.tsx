import { useState } from "react";
import { Alert, Box, Button, CircularProgress, Stack, TextField, Typography } from "@mui/material";
import { setEvaluationNote } from "../api";
import type { Evaluation } from "../types";
import { parseIsoDate } from "../dates";

/** The user's note on one verdict — why they applied or passed, or where the
 * evaluator got it wrong. Read back when reviewing the rubric, so it is
 * saved on this evaluation, not on the job. */
export default function EvaluationNote({
  evaluation,
  onSaved,
}: {
  evaluation: Evaluation;
  onSaved: (saved: Pick<Evaluation, "id" | "note" | "note_updated_at">) => void;
}) {
  const [text, setText] = useState(evaluation.note ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = text.trim() !== (evaluation.note ?? "");

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const saved = await setEvaluationNote(evaluation.id, text);
      setText(saved.note ?? "");
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the note");
    } finally {
      setSaving(false);
    }
  }

  const savedAt = evaluation.note_updated_at ? parseIsoDate(evaluation.note_updated_at) : null;
  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
        Your note
      </Typography>
      <TextField
        fullWidth
        multiline
        minRows={2}
        size="small"
        placeholder="Why you applied or passed — or where this verdict got it wrong."
        value={text}
        onChange={(e) => setText(e.target.value)}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      />
      <Stack direction="row" spacing={1.5} sx={{ mt: 1, alignItems: "center" }}>
        <Button
          size="small"
          variant="outlined"
          disabled={!changed || saving}
          startIcon={saving ? <CircularProgress size={14} /> : undefined}
          onClick={(e) => {
            e.stopPropagation();
            void save();
          }}
        >
          {text.trim() === "" && evaluation.note ? "Clear note" : "Save note"}
        </Button>
        {savedAt && !changed && (
          <Typography variant="caption" color="text.secondary">
            Saved {savedAt.toLocaleString()}
          </Typography>
        )}
      </Stack>
      {error && (
        <Alert severity="error" sx={{ mt: 1, borderRadius: 2 }}>
          {error}
        </Alert>
      )}
    </Box>
  );
}
