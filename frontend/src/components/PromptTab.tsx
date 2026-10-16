import { useEffect, useState } from "react";
import { Alert, Box, Chip, MenuItem, Select, Stack } from "@mui/material";
import { getPromptBody, getPromptVersions } from "../api";
import type { PromptKind } from "../types";
import { google } from "../theme";

interface Props {
  kind: PromptKind;
}

/** A version picker plus the raw prompt text, verbatim — shared by every
 * prompted workflow (evaluator, normalizer, ...) rather than each growing its
 * own copy of the same viewer. */
export default function PromptTab({ kind }: Props) {
  const [versions, setVersions] = useState<string[]>([]);
  const [active, setActive] = useState("");
  const [selected, setSelected] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setVersions([]);
    setActive("");
    setSelected("");
    setBody("");
    void (async () => {
      try {
        const data = await getPromptVersions(kind);
        setVersions(data.versions);
        setActive(data.active);
        setSelected(data.active);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load prompt versions");
      }
    })();
  }, [kind]);

  useEffect(() => {
    if (!selected) return;
    void (async () => {
      try {
        setBody(await getPromptBody(kind, selected));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load the prompt");
      }
    })();
  }, [kind, selected]);

  return (
    <Box>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 2 }}>
        <Select
          size="small"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          sx={{ minWidth: 120 }}
        >
          {versions.map((v) => (
            <MenuItem key={v} value={v}>
              {v}
            </MenuItem>
          ))}
        </Select>
        {selected === active && <Chip size="small" variant="outlined" label="active" />}
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      <Box
        component="pre"
        sx={{
          m: 0,
          p: 2,
          maxHeight: 640,
          overflow: "auto",
          fontSize: "0.8125rem",
          lineHeight: 1.6,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          backgroundColor: google.surface,
          border: `1px solid ${google.border}`,
          borderRadius: 1,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        }}
      >
        {body || "(empty)"}
      </Box>
    </Box>
  );
}
