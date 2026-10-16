import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  Paper,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import { getCosts } from "../api";
import { ROLE_CATEGORIES, ROUND_LABELS, ROUND_LADDER, type Application, type Costs, type Round } from "../types";
import { ROLE_COLORS, TABLEAU10, UNASSIGNED_COLOR } from "../colors";
import { google } from "../theme";
import { mondayOfIso, parseIsoDate, todayIso } from "../dates";
import { usePrivacy } from "../privacy";
import { useApplicationsData } from "../applicationsContext";
import MaskedText from "./MaskedText";

const CHART_HEIGHT = 220;
const UNASSIGNED = "Unassigned";
const LEGEND_KEYS = [...ROLE_CATEGORIES, UNASSIGNED];

function colorFor(role: string): { color: string; textColor?: string } {
  return ROLE_COLORS[role] ?? UNASSIGNED_COLOR;
}

type Granularity = "month" | "week";

interface TimeBucket {
  key: string;
  label: string;
  total: number;
  byRole: Record<string, number>;
}

// Week buckets truncate to the Monday on or before applied_at, so a
// Wednesday application counts toward that week's Monday-dated bucket.
function buildBuckets(rows: Application[], granularity: Granularity): TimeBucket[] {
  const buckets = new Map<string, TimeBucket>();
  const known = new Set<string>(ROLE_CATEGORIES);

  for (const row of rows) {
    if (!row.applied_at) continue;
    const key = granularity === "month" ? row.applied_at.slice(0, 7) : mondayOfIso(row.applied_at);
    let bucket = buckets.get(key);
    if (!bucket) {
      const label =
        granularity === "month"
          ? parseIsoDate(`${key}-01`).toLocaleDateString(undefined, { month: "short", year: "numeric" })
          : parseIsoDate(key).toLocaleDateString(undefined, { month: "short", day: "numeric" });
      bucket = { key, label, total: 0, byRole: {} };
      buckets.set(key, bucket);
    }
    const roleKey = row.role && known.has(row.role) ? row.role : UNASSIGNED;
    bucket.byRole[roleKey] = (bucket.byRole[roleKey] ?? 0) + 1;
    bucket.total += 1;
  }

  return [...buckets.values()].sort((a, b) => a.key.localeCompare(b.key));
}

function TimeStackedChart({ rows, granularity }: { rows: Application[]; granularity: Granularity }) {
  const { masked } = usePrivacy();
  const buckets = useMemo(() => buildBuckets(rows, granularity), [rows, granularity]);
  const maxTotal = Math.max(1, ...buckets.map((b) => b.total));

  if (buckets.length === 0) {
    return (
      <Paper variant="outlined" sx={{ p: 4, textAlign: "center", borderColor: google.border, borderRadius: 2 }}>
        <Typography color="text.secondary">No applications with a known date yet.</Typography>
      </Paper>
    );
  }

  return (
    <Box>
      <Stack direction="row" spacing={2} sx={{ mb: 2, flexWrap: "wrap" }}>
        {LEGEND_KEYS.map((role) => (
          <Stack key={role} direction="row" spacing={0.75} sx={{ alignItems: "center" }}>
            <Box sx={{ width: 10, height: 10, borderRadius: 0.5, backgroundColor: colorFor(role).color }} />
            <Typography variant="caption" color="text.secondary">
              {role === UNASSIGNED ? role : <MaskedText>{role}</MaskedText>}
            </Typography>
          </Stack>
        ))}
      </Stack>

      <Box sx={{ display: "flex", alignItems: "flex-end", gap: 2, height: CHART_HEIGHT, px: 1 }}>
        {buckets.map((bucket) => {
          const barHeight = Math.round((bucket.total / maxTotal) * CHART_HEIGHT);
          const segments = LEGEND_KEYS.filter((role) => bucket.byRole[role]);
          return (
            <Box
              key={bucket.key}
              sx={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1, minWidth: 28 }}
            >
              <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5 }}>
                {bucket.total}
              </Typography>
              <Box
                sx={{
                  width: "100%",
                  height: barHeight,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "flex-end",
                }}
              >
                {segments.map((role, i) => (
                  <Tooltip
                    key={role}
                    title={`${masked && role !== UNASSIGNED ? "••••••" : role}: ${bucket.byRole[role]}`}
                  >
                    <Box
                      sx={{
                        flex: bucket.byRole[role],
                        backgroundColor: colorFor(role).color,
                        mb: i < segments.length - 1 ? "2px" : 0,
                        borderRadius: 0.5,
                        "&:hover": { filter: "brightness(0.92)" },
                      }}
                    />
                  </Tooltip>
                ))}
              </Box>
            </Box>
          );
        })}
      </Box>

      <Box sx={{ display: "flex", gap: 2, px: 1, mt: 1 }}>
        {buckets.map((bucket) => (
          <Typography
            key={bucket.key}
            variant="caption"
            color="text.secondary"
            sx={{ flex: 1, minWidth: 28, textAlign: "center" }}
          >
            {bucket.label}
          </Typography>
        ))}
      </Box>
    </Box>
  );
}

interface FunnelStage {
  round: Round;
  label: string;
  count: number;
}

function buildFunnel(rows: Application[], role: string): FunnelStage[] {
  const roleRows = rows.filter((r) => r.role === role);
  return ROUND_LADDER.map((round, i) => {
    const count =
      i === 0
        ? roleRows.length
        : roleRows.filter((r) => r.highest_round && ROUND_LADDER.indexOf(r.highest_round) >= i).length;
    return { round, label: ROUND_LABELS[round], count };
  });
}

// Same definition as the dashboard-level Conversion Rate tile
// (backfill_summary's response_rate_of_known), just scoped to one role:
// of this role's applications with a KNOWN outcome, what share got past
// "applied." Computed client-side since the data is already loaded here.
function roleConversionRate(rows: Application[], role: string): number | null {
  const roleRows = rows.filter((r) => r.role === role);
  const known = roleRows.filter((r) => r.highest_round).length;
  if (known === 0) return null;
  const reachedPastApplied = roleRows.filter((r) => r.highest_round && r.highest_round !== "applied").length;
  return Math.round((reachedPastApplied / known) * 1000) / 10;
}

function RoleFunnelPanel({ role, rows }: { role: string; rows: Application[] }) {
  const funnel = useMemo(() => buildFunnel(rows, role), [rows, role]);
  const conversionRate = useMemo(() => roleConversionRate(rows, role), [rows, role]);
  const applied = funnel[0].count;
  const color = colorFor(role).color;

  return (
    <Paper variant="outlined" sx={{ p: 2, borderColor: google.border, borderRadius: 2 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "baseline", mb: 1.5, flexWrap: "wrap" }}>
        <Typography sx={{ fontWeight: 500 }}>
          <MaskedText>{role}</MaskedText>
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {applied} applied
        </Typography>
        {conversionRate !== null && (
          <Tooltip title="Share of this role's applications with a KNOWN outcome that got past the application stage — the unknowns are excluded, not counted as failures.">
            <Typography variant="caption" color="text.secondary">
              &middot; {conversionRate}% conversion
            </Typography>
          </Tooltip>
        )}
      </Stack>
      <Stack spacing={0.75}>
        {funnel.map((stage) => {
          const pct = applied === 0 ? 0 : Math.max((stage.count / applied) * 100, stage.count > 0 ? 4 : 0);
          return (
            <Tooltip key={stage.round} title={`${stage.label}: ${stage.count} of ${applied}`}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Typography variant="caption" color="text.secondary" sx={{ width: 84, flexShrink: 0 }}>
                  {stage.label}
                </Typography>
                <Box
                  sx={{
                    flex: 1,
                    backgroundColor: google.background,
                    borderRadius: 0.5,
                    height: 16,
                    overflow: "hidden",
                  }}
                >
                  <Box
                    sx={{
                      width: `${pct}%`,
                      height: "100%",
                      backgroundColor: color,
                      borderRadius: 0.5,
                      "&:hover": { filter: "brightness(0.92)" },
                    }}
                  />
                </Box>
                <Typography variant="caption" sx={{ width: 24, textAlign: "right", flexShrink: 0 }}>
                  {stage.count}
                </Typography>
              </Box>
            </Tooltip>
          );
        })}
      </Stack>
    </Paper>
  );
}

function RoleFunnelGrid({ rows }: { rows: Application[] }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 2 }}>
      {ROLE_CATEGORIES.map((role) => (
        <RoleFunnelPanel key={role} role={role} rows={rows} />
      ))}
    </Box>
  );
}

// Every tile in the KPI row — flat stat or ring — shares this height and
// label treatment, so the row reads as one line instead of five
// independently-sized cards.
const TILE_MIN_HEIGHT = 220;
// Fixed so every tile's label sits at the same y position regardless of how
// tall its content is below it — centering label+content as one block per
// tile (the previous approach) put the ring tile's label higher than the
// plain-number tiles', since the ring is much taller than a single number.
const TILE_LABEL_HEIGHT = 32;

/** Every KPI tile: a fixed-height label row, then a content row that fills
 * the rest and centers whatever it holds — a number, or the ring. */
function TileFrame({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        borderColor: google.border,
        borderRadius: 2,
        flex: 1,
        minWidth: 160,
        minHeight: TILE_MIN_HEIGHT,
        textAlign: "center",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Box sx={{ height: TILE_LABEL_HEIGHT, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {/* Same weight and size as "Applications by month" and "Role funnel" —
            a tile's label is a section header for that one number, not a caption. */}
        <Typography sx={{ fontWeight: 500 }}>{label}</Typography>
      </Box>
      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        {children}
      </Box>
    </Paper>
  );
}

function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  const tile = (
    <TileFrame label={label}>
      <Typography sx={{ fontSize: "2.25rem", fontWeight: 500 }}>{value}</Typography>
    </TileFrame>
  );
  return hint ? <Tooltip title={hint}>{tile}</Tooltip> : tile;
}

const DAILY_GOAL_MIN = 3;
const DAILY_GOAL_MAX = 5;

// Four tiers, not a plain under/met/over: 0 gets its own harsher tier from
// 1-2, since showing up at all is a different story from not starting.
function dailyGoalTier(count: number): { color: string; status: string } {
  if (count === 0) return { color: google.red, status: "Unachieved" };
  if (count <= 2) return { color: google.yellow, status: "Needs work" };
  if (count <= DAILY_GOAL_MAX) return { color: google.green, status: "Achieved" };
  return { color: TABLEAU10.purple, status: "Exceeded" };
}

// The value each zone starts at — [Unachieved, Needs work, Achieved,
// Exceeded]. Zone width in the ring is always an equal quarter regardless
// of how many integers a tier spans; only the *fill within* a zone uses
// that width.
const ZONE_START_VALUES = [0, 1, DAILY_GOAL_MIN, DAILY_GOAL_MAX + 1];
const ZONE_COLORS = [google.red, google.yellow, google.green, TABLEAU10.purple];

function zoneIndexForCount(count: number): number {
  for (let i = ZONE_START_VALUES.length - 1; i >= 0; i--) {
    if (count >= ZONE_START_VALUES[i]) return i;
  }
  return 0;
}

// How far to fill the active zone's own quarter, not the whole ring. The
// first and last zones are boundaries with no natural width (0 is a single
// value; "exceeded" has no ceiling), so reaching either shows it full.
// A middle zone fills proportionally: 4 (the middle of the 3-5 "Achieved"
// zone, which needs 3 steps to reach the next zone at 6) lands at exactly
// half — (4 - 3 + 1) / (3 + 1).
function fillFractionWithinZone(count: number, zoneIndex: number): number {
  const isBoundaryZone = zoneIndex === 0 || zoneIndex === ZONE_START_VALUES.length - 1;
  if (isBoundaryZone) return 1;
  const zoneStart = ZONE_START_VALUES[zoneIndex];
  const nextZoneStart = ZONE_START_VALUES[zoneIndex + 1];
  const stepsToNextZone = nextZoneStart - zoneStart;
  return (count - zoneStart + 1) / (stepsToNextZone + 1);
}

const RING_ZONE_COUNT = 4;
const RING_ZONE_GAP_DEG = 6;
const RING_SIZE = 120;
const RING_STROKE = 14;
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2;
const RING_CENTER = RING_SIZE / 2;

// Standard polar-to-cartesian for an SVG ring: angle 0 sits at 12 o'clock,
// and increasing angle sweeps clockwise (matching the ring's usual reading
// direction), by measuring from the -90 degree point in the underlying
// trig convention.
function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(angleRad), y: cy + r * Math.sin(angleRad) };
}

function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const start = polarToCartesian(cx, cy, r, startAngle);
  const end = polarToCartesian(cx, cy, r, endAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 1 ${end.x} ${end.y}`;
}

/** A ring with 4 fixed, equal quarters — one per tier — so the shape never
 * changes. Only the active tier's quarter fills, from its own start,
 * proportional to how far through that tier the count is; the other three
 * quarters always show just their dim background. */
function GoalRing({ count }: { count: number }) {
  const { color, status } = dailyGoalTier(count);
  const activeZone = zoneIndexForCount(count);
  const fillFraction = fillFractionWithinZone(count, activeZone);

  return (
    <Tooltip title={`${count} today — ${status} (goal: ${DAILY_GOAL_MIN}–${DAILY_GOAL_MAX})`}>
      <Box sx={{ position: "relative", width: RING_SIZE, height: RING_SIZE, mx: "auto" }}>
        <svg width={RING_SIZE} height={RING_SIZE}>
          {ZONE_COLORS.map((zoneColor, i) => {
            const zoneStartAngle = (i / RING_ZONE_COUNT) * 360 + RING_ZONE_GAP_DEG / 2;
            const zoneEndAngle = ((i + 1) / RING_ZONE_COUNT) * 360 - RING_ZONE_GAP_DEG / 2;

            // Passed zones light up fully, not just the active one —
            // reaching "Achieved" means you cleared "Needs work" too, so it
            // should not still look untouched. Lit in the current tier's
            // color, not each zone's own — the ring reads as one streak of
            // progress in today's color, not a rainbow of stages you moved
            // through.
            if (i < activeZone) {
              return (
                <path
                  key={i}
                  d={describeArc(RING_CENTER, RING_CENTER, RING_RADIUS, zoneStartAngle, zoneEndAngle)}
                  fill="none"
                  stroke={color}
                  strokeWidth={RING_STROKE}
                  strokeLinecap="round"
                />
              );
            }

            if (i === activeZone) {
              const fillEndAngle = zoneStartAngle + (zoneEndAngle - zoneStartAngle) * fillFraction;
              return (
                <g key={i}>
                  <path
                    d={describeArc(RING_CENTER, RING_CENTER, RING_RADIUS, zoneStartAngle, zoneEndAngle)}
                    fill="none"
                    stroke={zoneColor}
                    strokeWidth={RING_STROKE}
                    strokeOpacity={0.25}
                  />
                  <path
                    d={describeArc(RING_CENTER, RING_CENTER, RING_RADIUS, zoneStartAngle, fillEndAngle)}
                    fill="none"
                    stroke={color}
                    strokeWidth={RING_STROKE}
                    strokeLinecap="round"
                  />
                </g>
              );
            }

            // Not yet reached: dim background only.
            return (
              <path
                key={i}
                d={describeArc(RING_CENTER, RING_CENTER, RING_RADIUS, zoneStartAngle, zoneEndAngle)}
                fill="none"
                stroke={zoneColor}
                strokeWidth={RING_STROKE}
                strokeOpacity={0.25}
              />
            );
          })}
        </svg>
        <Box
          sx={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Typography sx={{ fontSize: "2rem", fontWeight: 500, color, lineHeight: 1 }}>{count}</Typography>
          <Typography variant="caption" sx={{ color, fontWeight: 600, mt: 0.5 }}>
            {status}
          </Typography>
        </Box>
      </Box>
    </Tooltip>
  );
}

function TodayGoalTile({ rows }: { rows: Application[] }) {
  const today = todayIso();
  const count = useMemo(() => rows.filter((r) => r.applied_at === today).length, [rows, today]);

  return (
    <TileFrame label={<>Today&rsquo;s goal ({DAILY_GOAL_MIN}&ndash;{DAILY_GOAL_MAX})</>}>
      <GoalRing count={count} />
    </TileFrame>
  );
}

function formatCost(costs: Costs | null): string {
  if (!costs) return "…";
  return `$${costs.total_cost_usd.toFixed(4)}`;
}

export default function DashboardView() {
  const { applications: rows, summary, loading, error, refresh } = useApplicationsData();
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [costs, setCosts] = useState<Costs | null>(null);
  const [costsError, setCostsError] = useState<string | null>(null);

  // Dashboard unmounts when you navigate away, so this runs fresh every time
  // you arrive here — the shared context's own background poll is just the
  // fallback for staying current while you're already on some other page.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void (async () => {
      try {
        setCosts(await getCosts());
      } catch (err) {
        setCostsError(err instanceof Error ? err.message : "Could not load costs");
      }
    })();
  }, []);

  return (
    <Box>
      <Typography variant="h1" sx={{ mb: 0.5 }}>
        Dashboard
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        How the search is going, at a glance.
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}
      {costsError && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {costsError}
        </Alert>
      )}

      {loading && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
          <CircularProgress size={20} />
        </Box>
      )}

      {!loading && (
        <Stack spacing={4}>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
            <StatTile label="Total applications" value={rows.length} />
            <StatTile label="Reached phone screen" value={summary?.reached_past_applied ?? "—"} />
            <StatTile
              label="Conversion rate"
              value={summary?.response_rate_of_known != null ? `${summary.response_rate_of_known}%` : "—"}
              hint="Share of applications with a KNOWN outcome that got past the application stage — the unknowns are excluded, not counted as failures."
            />
            <TodayGoalTile rows={rows} />
            <StatTile
              label="Total token cost"
              value={formatCost(costs)}
              hint={
                costs
                  ? `Evaluation: $${costs.evaluation_cost_usd.toFixed(4)} · Normalize: $${costs.normalize_cost_usd.toFixed(4)} · Embedding: $${costs.embedding_cost_usd.toFixed(4)} (only complete for calls made after cost tracking was added — earlier calls were not recorded)`
                  : undefined
              }
            />
          </Stack>

          <Box>
            <Stack direction="row" sx={{ alignItems: "center", justifyContent: "space-between", mb: 1.5 }}>
              <Typography sx={{ fontWeight: 500 }}>
                Applications by {granularity === "month" ? "month" : "week"}
              </Typography>
              <ToggleButtonGroup
                size="small"
                exclusive
                value={granularity}
                onChange={(_, next) => next && setGranularity(next)}
              >
                <ToggleButton value="month">Month</ToggleButton>
                <ToggleButton value="week">Week</ToggleButton>
              </ToggleButtonGroup>
            </Stack>
            <TimeStackedChart rows={rows} granularity={granularity} />
          </Box>
          <Box>
            <Typography sx={{ fontWeight: 500, mb: 1.5 }}>Role funnel</Typography>
            <RoleFunnelGrid rows={rows} />
          </Box>
        </Stack>
      )}
    </Box>
  );
}
