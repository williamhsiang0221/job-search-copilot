import type {
  Application,
  BankBullet,
  BulletTag,
  SuggestionStats,
  TagSuggestProgress,
  ApplicationNeedingAttachments,
  ApplyReport,
  AssemblyRun,
  AtsSource,
  AttachResumeResult,
  BackfillSummary,
  CaptureResponse,
  Costs,
  EvaluateProgress,
  Evaluation,
  FetchProgress,
  FetchReport,
  IcpResumeRecord,
  NormalizedJob,
  PromptKind,
  PromptVersions,
  RangePreset,
  ResumeForApplication,
  ScanReport,
  SimilarApplicationsResponse,
  StoredJob,
  TrackedCompany,
} from "./types";

export async function runCapture(
  preset: RangePreset,
  start?: string,
  end?: string,
): Promise<CaptureResponse> {
  const params = new URLSearchParams({ range: preset });
  if (preset === "custom" && start && end) {
    params.set("start", start);
    params.set("end", end);
  }

  // A capture is a Gmail read plus parsing — seconds, not minutes. Without a
  // ceiling any backend stall shows up as a spinner that never resolves.
  const timeout = AbortSignal.timeout(120_000);

  let response: Response;
  try {
    response = await fetch(`/api/capture?${params}`, { signal: timeout });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new Error("Capture timed out after 2 minutes. Check the backend terminal.");
    }
    throw new Error("Could not reach the backend. Is it running on port 8000?");
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Capture failed (${response.status})`);
  }
  return response.json();
}

/** Which job ids already have normalized fields stored. */
export async function getJobsStatus(
  jobIds: string[],
  source: string = "linkedin",
): Promise<Set<string>> {
  if (jobIds.length === 0) return new Set();

  const response = await fetch(
    `/api/jobs/status?ids=${encodeURIComponent(jobIds.join(","))}&source=${source}`,
  );
  if (!response.ok) throw new Error(`Status check failed (${response.status})`);

  const data = (await response.json()) as { ready: string[] };
  return new Set(data.ready);
}

/** Starts a fetch run on the backend. It runs in the background there —
 * poll getJobFetchProgress() for live status and the final report. */
export async function startJobFetch(
  jobIds: string[],
  source: string = "linkedin",
  jobCompanies?: Record<string, string>,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/jobs/fetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_ids: jobIds, source, job_companies: jobCompanies }),
    });
  } catch {
    throw new Error("Could not reach the backend. Is it running on port 8000?");
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Fetch failed (${response.status})`);
  }
}

/** Progress is tracked per source on the backend — a LinkedIn batch and a
 * Greenhouse batch can run at once, so each is polled separately. */
export async function getJobFetchProgress(source: string = "linkedin"): Promise<FetchProgress> {
  return getJson(
    `/api/jobs/fetch/progress?source=${encodeURIComponent(source)}`,
    "Checking fetch progress",
  );
}

const FETCH_POLL_MS = 1000;

/** Starts a fetch and polls until it finishes, returning the final report.
 * For a caller that only wants the end result — one that wants to show live
 * progress along the way should call startJobFetch/getJobFetchProgress directly. */
async function runJobFetch(
  jobIds: string[],
  source: string,
  jobCompanies?: Record<string, string>,
): Promise<FetchReport> {
  await startJobFetch(jobIds, source, jobCompanies);

  // Fetching is sequential and paced on the server, so a large selection can
  // run for minutes. The ceiling is generous but not absent.
  const deadline = Date.now() + 10 * 60_000;
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, FETCH_POLL_MS));
    if (Date.now() > deadline) throw new Error("Fetch timed out. Try selecting fewer roles.");

    const progress = await getJobFetchProgress(source);
    if (progress.error) throw new Error(progress.error);
    if (!progress.running && progress.report) return progress.report;
  }
}

export async function fetchJobDescriptions(jobIds: string[]): Promise<FetchReport> {
  return runJobFetch(jobIds, "linkedin");
}

export async function fetchAtsDescriptions(
  source: AtsSource,
  items: { job_id: string; company: string }[],
): Promise<FetchReport> {
  const jobIds = items.map((i) => i.job_id);
  const jobCompanies = Object.fromEntries(items.map((i) => [i.job_id, i.company]));
  return runJobFetch(jobIds, source, jobCompanies);
}

export async function uploadJobPdf(
  company: string,
  title: string,
  file: File,
  url?: string,
): Promise<FetchReport> {
  const body = new FormData();
  body.set("company", company);
  body.set("title", title);
  if (url) body.set("url", url);
  body.set("file", file);

  const response = await fetch("/api/jobs/upload-pdf", { method: "POST", body });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Upload failed (${response.status})`);
  }
  return response.json();
}

/** The merged one-time backfill worklist: applications missing a JD, a
 * resume, or both. */
export async function getApplicationsNeedingAttachments(): Promise<ApplicationNeedingAttachments[]> {
  const data = await getJson<{ applications: ApplicationNeedingAttachments[] }>(
    "/api/applications/needing-attachments",
    "Loading applications needing attachments",
  );
  return data.applications;
}

export async function attachPdfToApplication(
  applicationId: number,
  file: File,
): Promise<FetchReport> {
  const body = new FormData();
  body.set("file", file);

  const response = await fetch(`/api/applications/${applicationId}/attach-pdf`, {
    method: "POST",
    body,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Attach failed (${response.status})`);
  }
  return response.json();
}

export async function getResumeForApplication(applicationId: number): Promise<ResumeForApplication | null> {
  const data = await getJson<{ resume: ResumeForApplication | null }>(
    `/api/applications/${applicationId}/resume`,
    "Loading resume",
  );
  return data.resume;
}

export async function attachResumeToApplication(
  applicationId: number,
  file: File,
): Promise<AttachResumeResult> {
  const body = new FormData();
  body.set("file", file);

  const response = await fetch(`/api/applications/${applicationId}/attach-resume`, {
    method: "POST",
    body,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Attach failed (${response.status})`);
  }
  return response.json();
}

async function getJson<T>(path: string, label: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path);
  } catch {
    throw new Error("Could not reach the backend. Is it running on port 8000?");
  }
  if (!response.ok) throw new Error(`${label} failed (${response.status})`);
  return response.json();
}

export async function getStoredJobs(): Promise<StoredJob[]> {
  const data = await getJson<{ jobs: StoredJob[] }>("/api/jobs", "Loading jobs");
  return data.jobs;
}

export async function getNormalizedJobs(): Promise<NormalizedJob[]> {
  const data = await getJson<{ jobs: NormalizedJob[] }>(
    "/api/jobs/normalized",
    "Loading normalized jobs",
  );
  return data.jobs;
}

/** Recomputed on every call — see the backend's similarity_service module
 * docstring for why that is cheap enough to be the simple choice. */
export async function getSimilarApplications(
  source: string,
  jobId: string,
): Promise<SimilarApplicationsResponse> {
  return getJson(
    `/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(jobId)}/similar-applications`,
    "Loading similar applications",
  );
}

export async function getApplications(): Promise<{
  applications: Application[];
  summary: BackfillSummary;
}> {
  return getJson("/api/applications", "Loading applications");
}

export async function updateApplication(
  id: number,
  changes: Partial<
    Pick<
      Application,
      "status" | "highest_round" | "referral" | "job_id" | "role" | "applied_at" | "company" | "title"
    >
  >,
): Promise<void> {
  const response = await fetch(`/api/applications/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Update failed (${response.status})`);
  }
}

export async function getEvaluations(): Promise<Evaluation[]> {
  const data = await getJson<{ evaluations: Evaluation[] }>(
    "/api/evaluations",
    "Loading evaluations",
  );
  return data.evaluations;
}

export async function setEvaluationNote(
  id: number,
  note: string,
): Promise<Pick<Evaluation, "id" | "note" | "note_updated_at">> {
  const response = await fetch(`/api/evaluations/${id}/note`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Saving the note failed (${response.status})`);
  }
  return response.json();
}

export async function getCosts(): Promise<Costs> {
  return getJson("/api/costs", "Loading costs");
}

export async function getPromptVersions(kind: PromptKind): Promise<PromptVersions> {
  return getJson(`/api/prompts/${kind}`, "Loading prompt versions");
}

export async function getPromptBody(kind: PromptKind, version: string): Promise<string> {
  const data = await getJson<{ body: string }>(
    `/api/prompts/${kind}/${encodeURIComponent(version)}`,
    "Loading prompt",
  );
  return data.body;
}

export async function getIcpResumes(): Promise<IcpResumeRecord[]> {
  const data = await getJson<{ resumes: IcpResumeRecord[] }>("/api/icp-resumes", "Loading ICP resumes");
  return data.resumes;
}

/** Synchronous — a single LLM call, not a background batch. Takes a few
 * seconds; the caller should show its own loading state. */
export async function generateIcpResume(source: string, jobId: string): Promise<IcpResumeRecord> {
  let response: Response;
  try {
    response = await fetch(
      `/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(jobId)}/icp-resume`,
      { method: "POST" },
    );
  } catch {
    throw new Error("Could not reach the backend. Is it running on port 8000?");
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `ICP resume generation failed (${response.status})`);
  }
  return response.json();
}

/** Starts an evaluation run on the backend. It runs in the background there —
 * poll getEvaluateProgress() for live status and the final report. */
export async function startEvaluateJob(jobIds: string[], source: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_ids: jobIds, source }),
    });
  } catch {
    throw new Error("Could not reach the backend. Is it running on port 8000?");
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Evaluation failed (${response.status})`);
  }
}

/** Progress is tracked per source on the backend, same as fetch — a
 * selection spanning several sources evaluates them concurrently. */
export async function getEvaluateProgress(source: string): Promise<EvaluateProgress> {
  return getJson(
    `/api/evaluate/progress?source=${encodeURIComponent(source)}`,
    "Checking evaluation progress",
  );
}

export async function applyToJobs(jobIds: string[], source: string): Promise<ApplyReport> {
  const response = await fetch("/api/applications/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: jobIds, source }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Apply failed (${response.status})`);
  }
  return response.json();
}

export async function getTrackedCompanies(): Promise<TrackedCompany[]> {
  const data = await getJson<{ companies: TrackedCompany[] }>(
    "/api/ats/companies",
    "Loading tracked companies",
  );
  return data.companies;
}

export async function addTrackedCompany(
  company: string,
  source: AtsSource,
  boardToken: string,
): Promise<void> {
  const response = await fetch("/api/ats/companies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company, source, board_token: boardToken }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Add company failed (${response.status})`);
  }
}

export async function removeTrackedCompany(id: number): Promise<void> {
  const response = await fetch(`/api/ats/companies/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error(`Remove company failed (${response.status})`);
}

export async function setTrackedCompanyEnabled(id: number, enabled: boolean): Promise<void> {
  const response = await fetch(`/api/ats/companies/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) throw new Error(`Update company failed (${response.status})`);
}

export async function scanAtsCompanies(): Promise<ScanReport> {
  // A full sequential scan across every tracked company; generous ceiling
  // for the same reason as Fetch JD.
  const timeout = AbortSignal.timeout(10 * 60_000);

  let response: Response;
  try {
    response = await fetch("/api/ats/scan", { method: "POST", signal: timeout });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new Error("Scan timed out.");
    }
    throw new Error("Could not reach the backend. Is it running on port 8000?");
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Scan failed (${response.status})`);
  }
  return response.json();
}

/** Seeds a Resume Assembler run and starts it in the background. A 409 means
 * no similar past role has a resume on file yet. */
export async function startAssembly(source: string, jobId: string): Promise<number> {
  let response: Response;
  try {
    response = await fetch(
      `/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(jobId)}/assemble`,
      { method: "POST" },
    );
  } catch {
    throw new Error("Could not reach the backend. Is it running on port 8000?");
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Could not start the assembler (${response.status})`);
  }
  return (await response.json()).run_id;
}

export async function getAssemblyRuns(): Promise<AssemblyRun[]> {
  const data = await getJson<{ runs: AssemblyRun[] }>("/api/assembly-runs", "Loading assembler runs");
  return data.runs;
}

export async function getAssemblyRun(runId: number): Promise<AssemblyRun> {
  return getJson<AssemblyRun>(`/api/assembly-runs/${runId}`, "Loading assembler run");
}

async function sendJson<T>(method: string, path: string, body: unknown, label: string): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `${label} failed (${response.status})`);
  }
  return response.json();
}

export async function searchBulletBank(params: {
  keywords: string;
  tagIds: number[];
  untagged: boolean;
}): Promise<{ bullets: BankBullet[]; suggestion_stats: SuggestionStats }> {
  const query = new URLSearchParams();
  if (params.keywords.trim()) query.set("q", params.keywords);
  if (params.tagIds.length) query.set("tags", params.tagIds.join(","));
  if (params.untagged) query.set("untagged", "true");
  return getJson(`/api/bullet-bank?${query}`, "Searching the bullet bank");
}

/** Ask the suggester about these bullets (experience ones not yet asked). */
export function startTagSuggestions(texts: string[]): Promise<{ started: boolean; total: number }> {
  return sendJson("POST", "/api/bullet-bank/suggest", { texts }, "Starting tag suggestions");
}

export function getTagSuggestProgress(): Promise<TagSuggestProgress> {
  return getJson("/api/bullet-bank/suggest/progress", "Checking suggestion progress");
}

export function decideTagSuggestion(id: number, accept: boolean): Promise<unknown> {
  return sendJson("POST", `/api/bullet-bank/suggestions/${id}/${accept ? "accept" : "reject"}`, undefined, "Saving");
}

export async function getBulletTags(): Promise<BulletTag[]> {
  return (await getJson<{ tags: BulletTag[] }>("/api/bullet-tags", "Loading tags")).tags;
}

export function createBulletTag(tag: { name: string; category: string | null; definition: string }): Promise<BulletTag> {
  return sendJson("POST", "/api/bullet-tags", tag, "Creating the tag");
}

export function updateBulletTag(
  id: number,
  changes: Partial<Pick<BulletTag, "name" | "category" | "definition">>,
): Promise<BulletTag> {
  return sendJson("PATCH", `/api/bullet-tags/${id}`, changes, "Saving the tag");
}

export function deleteBulletTag(id: number): Promise<unknown> {
  return sendJson("DELETE", `/api/bullet-tags/${id}`, undefined, "Deleting the tag");
}

export function setBulletTags(text: string, tagIds: number[]): Promise<{ text: string; tag_ids: number[] }> {
  return sendJson("PUT", "/api/bullet-bank/tags", { text, tag_ids: tagIds }, "Saving tags");
}

