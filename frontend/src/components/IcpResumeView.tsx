import { useCallback, useEffect, useState } from "react";
import { Alert, Box, Button, Chip, CircularProgress, Stack, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import ExpandableTable, { type ColumnDef } from "./ExpandableTable";
import { getIcpResumes } from "../api";
import type { ExperienceEntry, IcpResumeRecord } from "../types";
import { google } from "../theme";
import { parseIsoDate } from "../dates";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const date = parseIsoDate(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function ExperienceBlock({ entry }: { entry: ExperienceEntry }) {
  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.25 }}>
        {entry.context}
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 3 }}>
        {entry.bullets.map((bullet, i) => (
          <Typography component="li" variant="body2" key={i} sx={{ mb: 0.5 }}>
            {bullet}
          </Typography>
        ))}
      </Box>
    </Box>
  );
}

const columns: ColumnDef<IcpResumeRecord>[] = [
  { id: "company", label: "Company", render: (r) => r.company },
  { id: "title", label: "Title", render: (r) => r.title },
  { id: "generated_at", label: "Generated", render: (r) => formatDate(r.generated_at), nowrap: true },
  { id: "model", label: "Model", render: (r) => r.model || "—", nowrap: true },
  {
    id: "prompt_version",
    label: "Prompt",
    nowrap: true,
    render: (r) => <Chip size="small" variant="outlined" label={r.prompt_version} />,
  },
  {
    id: "cost_usd",
    label: "Cost",
    nowrap: true,
    render: (r) =>
      r.cost_usd === null ? (
        <Box component="span" sx={{ color: google.border }}>
          —
        </Box>
      ) : (
        `$${r.cost_usd.toFixed(4)}`
      ),
  },
];

export default function IcpResumeView() {
  const [resumes, setResumes] = useState<IcpResumeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setResumes(await getIcpResumes());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load ICP resumes");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Box>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 2 }}>
        <Button
          size="small"
          startIcon={loading ? <CircularProgress size={14} /> : <RefreshIcon />}
          onClick={() => void load()}
          disabled={loading}
        >
          Refresh
        </Button>
        <Chip size="small" variant="outlined" label={`${resumes.length} generated`} />
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {resumes.length === 0 && !loading ? (
        <Alert severity="info" sx={{ borderRadius: 2 }}>
          Nothing generated yet. Use "Generate ICP Resume" on a role in Job descriptions →
          Normalized.
        </Alert>
      ) : (
        <ExpandableTable
          rows={resumes}
          columns={columns}
          rowKey={(r) => String(r.id)}
          minWidth={900}
          expanded={(r) => (
            <Box>
              {r.experience.map((entry, i) => (
                <ExperienceBlock key={i} entry={entry} />
              ))}
              <Typography variant="caption" color="text.secondary">
                Illustrative only — compare against your real resume for this role, don't copy
                wholesale.
              </Typography>
            </Box>
          )}
        />
      )}
    </Box>
  );
}
