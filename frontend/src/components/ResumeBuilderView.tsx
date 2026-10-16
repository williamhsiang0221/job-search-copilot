import { useState } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import PromptTab from "./PromptTab";
import IcpResumeView from "./IcpResumeView";
import AssemblerView from "./AssemblerView";
import BulletBankView from "./BulletBankView";
import type { PromptKind } from "../types";

interface Props {
  sub: "icp" | "assembler" | "bullets" | "prompt";
  assemblyRunId: number | null;
  onSelectAssemblyRun: (id: number | null) => void;
}

const HEADINGS: Record<string, { title: string; blurb: string }> = {
  icp: {
    title: "ICP Resume",
    blurb:
      "An illustrative resume for a role, built from a condensed version of your real background — a benchmark to compare your own resume against, not a replacement for it.",
  },
  assembler: {
    title: "Assembler",
    blurb:
      "Assembles a resume for a role from your past resumes — swapping lines only, never writing new ones — until it beats the anchor on the ATS and recruiter scans. Every step is traced live.",
  },
  bullets: {
    title: "Bullet Bank",
    blurb:
      "Every distinct bullet across your uploaded resumes — how many resumes used it and when it was last used. Search by keywords, filter and tag by theme.",
  },
  prompt: {
    title: "Prompt",
    blurb:
      "Every prompt behind Resume Builder, verbatim and versioned — pick one, then a version, to see exactly what ran.",
  },
};

// Every prompted step Resume Builder runs, in the order a run uses them.
const PROMPTS: { kind: PromptKind; label: string }[] = [
  { kind: "resume", label: "ICP Resume" },
  { kind: "assembler", label: "Assembler" },
  { kind: "ats_criteria", label: "ATS Criteria" },
  { kind: "ats_scanner", label: "ATS Scanner" },
  { kind: "recruiter_scanner", label: "Recruiter Scanner" },
  { kind: "bullet_tagger", label: "Bullet Tagger" },
];

/** Version control existed before the first real generation (see
 * resume_service.py) rather than being retrofitted once the feature was
 * real, the way the normalizer's had to be. */
export default function ResumeBuilderView({ sub, assemblyRunId, onSelectAssemblyRun }: Props) {
  const [promptKind, setPromptKind] = useState<PromptKind>("resume");

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        {HEADINGS[sub].title}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {HEADINGS[sub].blurb}
      </Typography>

      {sub === "prompt" ? (
        <>
          <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: "wrap", rowGap: 1 }}>
            {PROMPTS.map((p) => (
              <Chip
                key={p.kind}
                label={p.label}
                clickable
                color={p.kind === promptKind ? "primary" : "default"}
                variant={p.kind === promptKind ? "filled" : "outlined"}
                onClick={() => setPromptKind(p.kind)}
              />
            ))}
          </Stack>
          {/* Keyed so switching prompts starts clean rather than briefly
              requesting the previous prompt's selected version. */}
          <PromptTab key={promptKind} kind={promptKind} />
        </>
      ) : sub === "assembler" ? (
        <AssemblerView runId={assemblyRunId} onSelectRun={onSelectAssemblyRun} />
      ) : sub === "bullets" ? (
        <BulletBankView />
      ) : (
        <IcpResumeView />
      )}
    </Box>
  );
}
