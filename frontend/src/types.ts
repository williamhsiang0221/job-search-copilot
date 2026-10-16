export interface Role {
  title: string;
  company: string;
  location: string;
  url: string;
  job_id: string;
  source_subject: string;
  received_at: string;
  /** How many alert emails carried this job. */
  match_count: number;
}

export interface CaptureMeta {
  emails_scanned: number;
  roles_found: number;
  rows_parsed: number;
  duplicates_collapsed: number;
  range_start: string;
  range_end: string;
  source: "fixtures" | "gmail";
}

export interface CaptureResponse {
  roles: Role[];
  meta: CaptureMeta;
}

export type RangePreset = "today" | "yesterday" | "past3" | "past7" | "custom";

export interface FetchReport {
  stored: string[];
  normalized: string[];
  skipped: string[];
  failures: Record<string, string>;
  normalize_failures: Record<string, string>;
  counts: {
    stored: number;
    normalized: number;
    skipped: number;
    failed: number;
    normalize_failed: number;
  };
}

export const ATS_SOURCES = ["greenhouse", "ashby", "lever"] as const;
export type AtsSource = (typeof ATS_SOURCES)[number];

export interface TrackedCompany {
  id: number;
  company: string;
  source: AtsSource;
  board_token: string;
  enabled: boolean;
}

export interface AtsCandidate {
  source: AtsSource;
  job_id: string;
  title: string;
  company: string;
  location: string;
  url: string;
  posted_at: string | null;
}

export interface ScanReport {
  candidates: AtsCandidate[];
  companies_scanned: number;
  companies_failed: Record<string, string>;
}

export interface StoredJob {
  source: string;
  job_id: string;
  title: string;
  company: string;
  location: string;
  url: string;
  apply_url: string | null;
  posted_at: string | null;
  posted_at_is_approximate: boolean;
  description_raw: string;
  description_chars: number;
  level_raw: string | null;
  employment_type_raw: string | null;
  workplace_raw: string | null;
  department: string | null;
  team: string | null;
  job_function: string | null;
  industries: string | null;
  salary_text: string | null;
  fetched_at: string | null;
}

export interface NormalizedJob {
  source: string;
  job_id: string;
  title: string;
  company: string;
  posted_at: string | null;
  responsibilities: string[];
  qualifications: string[];
  comp_min: number | null;
  comp_max: number | null;
  workplace: string | null;
  /** The posting's own sentences on the role's or team's purpose. null =
   * normalized before v3 (never asked); [] = the posting had none. */
  role_summary: string[] | null;
  model: string;
  normalizer_version: string;
  normalized_at: string | null;
}

/** A past application ranked by embedding similarity to a job being looked
 * at now — the outcome rides along so the score is never seen in isolation.
 * score is a z-score against the current corpus (how many standard
 * deviations above/below average this match is), not raw cosine similarity —
 * comparable across fields and across responses, unlike the raw value. */
export interface SimilarApplication {
  application_id: number;
  company: string;
  title: string;
  role: string;
  status: string;
  highest_round: string | null;
  score: number;
}

export interface SimilarApplicationsResponse {
  responsibilities: SimilarApplication[];
  qualifications: SimilarApplication[];
  /** Responsibilities and Qualifications z-scores averaged 50/50 — a rough
   * triage aid, not a restatement of either list, and can rank a well-
   * rounded match above one that is extreme on only one dimension. */
  overall: SimilarApplication[];
  /** Role categories with too few past applications (< 5) for their own
   * average to be a reliable baseline — shown so thin results are not read
   * with the same confidence as well-supported ones. */
  thin_categories: string[];
}

export const ROUND_LADDER = [
  "applied",
  "phone_screen",
  "interview",
  "final_round",
  "offer",
  "accepted",
] as const;

export type Round = (typeof ROUND_LADDER)[number];

export const ROUND_LABELS: Record<string, string> = {
  applied: "Applied only",
  phone_screen: "Phone screen",
  interview: "Interview",
  final_round: "Final round",
  offer: "Offer",
  accepted: "Accepted",
};

// The only categories the dashboard assigns going forward. Legacy Notion rows
// carry free-text values (e.g. "Strategist") outside this list.
//
// Simplified from six categories to four: Product Marketing merged into
// Marketing, Product Strategy & Ops merged into Product Manager, AI Strategy
// renamed to Strategy. Existing rows were rewritten to match (see BACKLOG).
export const ROLE_CATEGORIES = ["Product Manager", "Strategy", "Data Analyst", "Marketing"] as const;

export type RoleCategory = (typeof ROLE_CATEGORIES)[number];

export interface Application {
  id: number;
  company: string;
  /** RoleCategory going forward; legacy Notion rows may hold free text (e.g. "Strategist") outside it. */
  role: string | null;
  title: string;
  job_id: string | null;
  applied_at: string | null;
  status: string;
  /** null means unknown and needing backfill, not "never got past applied". */
  highest_round: Round | null;
  referral: string | null;
  salary_range: string | null;
}

// A row needs backfill for either reason: legacy rows are missing
// highest_round, dashboard-applied rows are missing role. Shared between
// ApplicationsView and Sidebar (for its badge count) — note this is not the
// same figure as BackfillSummary.needs_backfill, which the backend derives
// from highest_round alone and does not know about role.
export function needsBackfill(a: Application): boolean {
  return !a.highest_round || !a.role;
}

export interface BackfillSummary {
  total: number;
  known: number;
  needs_backfill: number;
  reached_past_applied: number;
  by_round: Record<string, number>;
  response_rate_of_known: number | null;
}

/** An application missing a JD, a resume, or both — the merged one-time
 * backfill worklist, not part of the regular applications flow. */
export interface ApplicationNeedingAttachments {
  id: number;
  company: string;
  title: string;
  applied_at: string | null;
  needs_jd: boolean;
  needs_resume: boolean;
}

/** Result of POST /api/applications/{id}/attach-resume. */
export interface AttachResumeResult {
  status: "ingested" | "already_linked" | "replaced";
  resume_id: string;
  sections?: number;
  bullets?: number;
  /** Only on "replaced": the resume that was deleted in favor of this one. */
  replaced_resume_id?: string;
}

export interface ResumeSection {
  slot: string;
  header: string | null;
  bullets: string[];
}

/** The parsed resume attached to one application, for the All Applications
 * expand panel — see GET /api/applications/{id}/resume. */
export interface ResumeForApplication {
  resume_id: string;
  headline: string | null;
  sections: ResumeSection[];
}

/** Only complete for normalize calls and evaluations from after cost
 * tracking was added to each — earlier rows recorded no token usage. */
export interface Costs {
  normalize_cost_usd: number;
  evaluation_cost_usd: number;
  embedding_cost_usd: number;
  resume_cost_usd: number;
  assembler_cost_usd: number;
  total_cost_usd: number;
}

export interface ExperienceEntry {
  context: string;
  bullets: string[];
}

/** One ICP Resume generation for one posting. Every generation appends a new
 * row rather than replacing a prior one — see backend resume_service.py. */
export interface IcpResumeRecord {
  id: number;
  source: string;
  job_id: string;
  company: string;
  title: string;
  experience: ExperienceEntry[];
  model: string;
  prompt_version: string;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  generated_at: string | null;
}

export const VERDICTS = ["SKIP", "MAYBE", "APPLY"] as const;
export type Verdict = (typeof VERDICTS)[number];

/** Human labels for the ten rubric sub-score codes. */
export const SUBSCORE_LABELS: Record<string, string> = {
  "4a": "Function alignment",
  "4b": "Company tier",
  "4c": "Seniority & scope",
  "4d": "Location",
  "5a": "Keyword/signal match",
  "5b": "YOE & title framing",
  "5c": "Education & hard reqs",
  "5d": "Story depth",
  "5e": "Gap exposure",
  "5f": "Why-this-company",
};

export interface SubScore {
  code: string;
  /** null when abstained — the posting did not state it, not a bad score. */
  score: number | null;
  weight: number;
  abstained: boolean;
  rationale: string;
}

export interface Evaluation {
  id: number;
  source: string;
  job_id: string;
  title: string;
  company: string;
  rubric_version: string;
  score_1: number | null;
  score_2: number | null;
  verdict: Verdict;
  /** Which hard gate forced a SKIP, if one did. */
  disqualifier: string | null;
  reasoning: string;
  model: string;
  /** Facts from the API. cost_usd is what the call cost at the time. */
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  latency_ms: number | null;
  created_at: string | null;
  /** The user's own note on this verdict, for reviewing the rubric later. */
  note: string | null;
  note_updated_at: string | null;
  scores: SubScore[];
}

export interface EvaluateReport {
  evaluated: string[];
  skipped: string[];
  failures: Record<string, string>;
}

/** Live status of a /api/evaluate run, meant to be polled. */
export interface EvaluateProgress {
  running: boolean;
  total: number;
  done_ids: string[];
  report: EvaluateReport | null;
  error: string | null;
}

/** Live status of a /api/jobs/fetch run, meant to be polled. */
export interface FetchProgress {
  running: boolean;
  total: number;
  done_ids: string[];
  report: FetchReport | null;
  error: string | null;
}

export interface ApplyReport {
  applied: string[];
  skipped_existing: string[];
  skipped_missing: string[];
}

/** Which prompted workflow's versions to list — matches a data/prompts/
 * subdirectory name on the backend. */
export type PromptKind =
  | "evaluator"
  | "normalizer"
  | "resume"
  | "ats_criteria"
  | "ats_scanner"
  | "recruiter_scanner"
  | "assembler"
  | "bullet_tagger";

export interface PromptVersions {
  versions: string[];
  active: string;
}

/** One line of an assembler draft, with where it came from. */
export interface DraftLine {
  text: string;
  source_resume_id: string;
  source_bullet_id?: string;
}

export interface DraftSection {
  slot: string;
  header: DraftLine | null;
  bullets: DraftLine[];
}

export interface AssemblyDraft {
  headline: string | null;
  sections: DraftSection[];
}

export interface SeedCandidate {
  application_id: number;
  resume_id: string | null;
  company: string;
  title: string;
  score: number;
}

/** A scanner's latest verdict on the draft. Pairwise scanners carry
 * winner/reasons/labels; the hard gate carries defects. */
export interface ScanVerdict {
  draft_version: number;
  passed: boolean;
  winner?: "candidate" | "anchor" | "tie";
  reasons?: string;
  labels?: Record<string, string>;
  coverage?: { criterion: string; required: boolean; candidate: boolean; anchor: boolean }[];
  defects?: { kind: string; refs: string[]; detail: string }[];
}

export type AssemblyStatus = "seeded" | "running" | "passed" | "hit_cap" | "stopped" | "error";

export interface AssemblyTurn {
  seq: number;
  kind: "model" | "tool" | "system";
  tool_name: string | null;
  // Shape depends on kind/tool — see backend assembler_agent.py.
  payload: Record<string, any> | null;
  result: Record<string, any> | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  created_at: string | null;
}

export interface AssemblyRun {
  id: number;
  source: string;
  job_id: string;
  company: string;
  title: string;
  anchor_resume_id: string;
  donor_resume_ids: string[];
  seed: { anchor: SeedCandidate; donors: SeedCandidate[]; ranked: SeedCandidate[] };
  draft: AssemblyDraft;
  status: AssemblyStatus;
  rounds_used: number;
  turns_used: number;
  verdicts: Partial<Record<"hard_gate" | "ats" | "recruiter", ScanVerdict>>;
  prompt_versions: Record<string, string>;
  error: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  started_at: string | null;
  finished_at: string | null;
  /** Only on the single-run endpoint. */
  turns?: AssemblyTurn[];
}

/** A Bullet Bank tag. category is a role category (drives the color) or
 * null for an uncategorized tag. usage = how many sentences carry it. */
export interface BulletTag {
  id: number;
  name: string;
  category: string | null;
  definition: string;
  usage: number;
}

/** One distinct bullet sentence across every uploaded resume. */
export interface BankBullet {
  text: string;
  /** Resume section slots it appears under (see slots.ts). */
  slots: string[];
  resume_count: number;
  last_used: string | null;
  tag_ids: number[];
  /** Pending tag suggestions — never applied until accepted. */
  suggestions: { id: number; tag_id: number; reason: string }[];
  resumes: { resume_id: string; company: string | null; title: string | null; resume_date: string | null }[];
}

/** How the user has answered the tag suggester so far. */
export interface SuggestionStats {
  suggested: number;
  accepted: number;
  rejected: number;
}

export interface TagSuggestProgress {
  running: boolean;
  total: number;
  done: number;
  report: { sentences: number; batches: number; suggestions: number; dropped: number; cost_usd: number } | null;
  error: string | null;
}

