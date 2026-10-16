import { useCallback, useEffect, useMemo, useState, type ComponentProps } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  LinearProgress,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import LocalOfferOutlinedIcon from "@mui/icons-material/LocalOfferOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import ExpandableTable, { type ColumnDef } from "./ExpandableTable";
import {
  createBulletTag,
  decideTagSuggestion,
  deleteBulletTag,
  getBulletTags,
  getTagSuggestProgress,
  searchBulletBank,
  setBulletTags,
  startTagSuggestions,
  updateBulletTag,
} from "../api";
import {
  ROLE_CATEGORIES,
  type BankBullet,
  type BulletTag,
  type SuggestionStats,
  type TagSuggestProgress,
} from "../types";
import { ROLE_COLORS, UNASSIGNED_COLOR } from "../colors";
import { useSlotLabels } from "../slots";
import { parseIsoDate } from "../dates";
import CopyButton, { showCopyOnHover } from "./CopyButton";

const UNCATEGORIZED = "Uncategorized";

function tagColors(tag: BulletTag) {
  return (tag.category && ROLE_COLORS[tag.category]) || UNASSIGNED_COLOR;
}

/** A tag chip in its role category's color — the same colors the role
 * category chips use everywhere else. */
function TagChip({ tag, onDelete }: { tag: BulletTag; onDelete?: ComponentProps<typeof Chip>["onDelete"] }) {
  const { color, textColor } = tagColors(tag);
  return (
    <Tooltip title={tag.definition || ""} disableInteractive>
      <Chip
        size="small"
        label={tag.name}
        onDelete={onDelete}
        sx={{
          bgcolor: color,
          color: textColor ?? "#fff",
          height: 22,
          fontSize: "0.72rem",
          "& .MuiChip-deleteIcon": { color: textColor ?? "#fff", opacity: 0.7 },
        }}
      />
    </Tooltip>
  );
}

/** A pending suggestion: dashed, in the tag's color, with accept / reject. */
function SuggestionChip({
  tag,
  reason,
  onDecide,
}: {
  tag: BulletTag;
  reason: string;
  onDecide: (accept: boolean) => void;
}) {
  const { color } = tagColors(tag);
  return (
    <Tooltip title={`Suggested: ${reason}`} disableInteractive>
      <Box
        component="span"
        onClick={(e) => e.stopPropagation()}
        sx={{
          display: "inline-flex",
          alignItems: "center",
          height: 22,
          pl: 1,
          border: "1px dashed",
          borderColor: color,
          borderRadius: 11,
          color,
          fontSize: "0.72rem",
          fontWeight: 500,
        }}
      >
        {tag.name}
        <IconButton size="small" aria-label={`Accept ${tag.name}`} onClick={() => onDecide(true)} sx={{ p: 0.25, ml: 0.25 }}>
          <CheckIcon sx={{ fontSize: 14, color }} />
        </IconButton>
        <IconButton size="small" aria-label={`Reject ${tag.name}`} onClick={() => onDecide(false)} sx={{ p: 0.25, mr: 0.25 }}>
          <CloseIcon sx={{ fontSize: 14, color: "text.secondary" }} />
        </IconButton>
      </Box>
    </Tooltip>
  );
}

function formatDate(iso: string | null): string {
  return iso ? parseIsoDate(iso).toLocaleDateString() : "—";
}

/** Multi-select over the tags, grouped by role category. */
function TagPicker({
  tags,
  value,
  onChange,
  label,
  placeholder,
}: {
  tags: BulletTag[];
  value: number[];
  onChange: (ids: number[]) => void;
  label?: string;
  placeholder?: string;
}) {
  const byId = useMemo(() => new Map(tags.map((t) => [t.id, t])), [tags]);
  const selected = value.map((id) => byId.get(id)).filter((t): t is BulletTag => !!t);
  return (
    <Autocomplete
      multiple
      size="small"
      options={tags}
      value={selected}
      groupBy={(t) => t.category ?? UNCATEGORIZED}
      getOptionLabel={(t) => t.name}
      isOptionEqualToValue={(a, b) => a.id === b.id}
      onChange={(_, next) => onChange(next.map((t) => t.id))}
      renderValue={(items, getItemProps) =>
        items.map((tag, index) => {
          const { key, onDelete } = getItemProps({ index });
          return (
            <Box key={key} component="span" sx={{ mr: 0.5 }}>
              <TagChip tag={tag} onDelete={onDelete} />
            </Box>
          );
        })
      }
      renderInput={(params) => (
        <TextField {...params} label={label} placeholder={selected.length ? undefined : placeholder} />
      )}
      onClick={(e) => e.stopPropagation()}
      sx={{ minWidth: 280 }}
    />
  );
}

function TagForm({
  initial,
  onSubmit,
  submitLabel,
}: {
  initial?: BulletTag;
  onSubmit: (tag: { name: string; category: string | null; definition: string }) => Promise<void>;
  submitLabel: string;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [category, setCategory] = useState<string>(initial?.category ?? "");
  const [definition, setDefinition] = useState(initial?.definition ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed =
    !initial ||
    name.trim() !== initial.name ||
    (category || null) !== initial.category ||
    definition.trim() !== initial.definition;

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ name: name.trim(), category: category || null, definition: definition.trim() });
      if (!initial) {
        setName("");
        setDefinition("");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the tag");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <TextField size="small" label="Name" value={name} onChange={(e) => setName(e.target.value)} sx={{ flex: 1 }} />
        <TextField
          size="small"
          select
          label="Category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          sx={{ width: 180 }}
        >
          <MenuItem value="">{UNCATEGORIZED}</MenuItem>
          {ROLE_CATEGORIES.map((c) => (
            <MenuItem key={c} value={c}>
              {c}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      <TextField
        size="small"
        fullWidth
        multiline
        minRows={2}
        label="Definition"
        value={definition}
        onChange={(e) => setDefinition(e.target.value)}
      />
      <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: "center" }}>
        <Button
          size="small"
          variant="outlined"
          disabled={!name.trim() || !changed || saving}
          startIcon={saving ? <CircularProgress size={14} /> : undefined}
          onClick={() => void submit()}
        >
          {submitLabel}
        </Button>
        {error && (
          <Typography variant="caption" color="error">
            {error}
          </Typography>
        )}
      </Stack>
    </Box>
  );
}

function ManageTagsDialog({
  open,
  tags,
  onClose,
  onChanged,
}: {
  open: boolean;
  tags: BulletTag[];
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function remove(tag: BulletTag) {
    const where = tag.usage ? ` It is on ${tag.usage} bullet(s) and will be removed from them.` : "";
    if (!window.confirm(`Delete the tag "${tag.name}"?${where}`)) return;
    setError(null);
    try {
      await deleteBulletTag(tag.id);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the tag");
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Manage tags</DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>
          New tag
        </Typography>
        <TagForm
          submitLabel="Create tag"
          onSubmit={async (tag) => {
            await createBulletTag(tag);
            await onChanged();
          }}
        />
        {error && (
          <Alert severity="error" sx={{ mt: 2, borderRadius: 2 }}>
            {error}
          </Alert>
        )}
        {[...ROLE_CATEGORIES, null].map((category) => {
          const group = tags.filter((t) => t.category === category);
          if (group.length === 0) return null;
          return (
            <Box key={category ?? UNCATEGORIZED} sx={{ mt: 3 }}>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>
                {category ?? UNCATEGORIZED}
              </Typography>
              {group.map((tag) => (
                <Box key={tag.id} sx={{ py: 1, borderTop: 1, borderColor: "divider" }}>
                  {editing === tag.id ? (
                    <TagForm
                      initial={tag}
                      submitLabel="Save"
                      onSubmit={async (changes) => {
                        await updateBulletTag(tag.id, changes);
                        setEditing(null);
                        await onChanged();
                      }}
                    />
                  ) : (
                    <Stack direction="row" spacing={1.5} sx={{ alignItems: "flex-start" }}>
                      <Box sx={{ minWidth: 220 }}>
                        <TagChip tag={tag} />
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                          on {tag.usage} bullet{tag.usage === 1 ? "" : "s"}
                        </Typography>
                      </Box>
                      <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
                        {tag.definition || "No definition."}
                      </Typography>
                      <Button size="small" onClick={() => setEditing(tag.id)}>
                        Edit
                      </Button>
                      <IconButton size="small" aria-label={`Delete ${tag.name}`} onClick={() => void remove(tag)}>
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Stack>
                  )}
                </Box>
              ))}
            </Box>
          );
        })}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Done</Button>
      </DialogActions>
    </Dialog>
  );
}

function BulletDetail({
  bullet,
  tags,
  onTagsSaved,
}: {
  bullet: BankBullet;
  tags: BulletTag[];
  onTagsSaved: (text: string, tagIds: number[]) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  async function save(ids: number[]) {
    setError(null);
    try {
      const saved = await setBulletTags(bullet.text, ids);
      onTagsSaved(bullet.text, saved.tag_ids);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save tags");
    }
  }

  return (
    <Box>
      <Typography variant="body2" sx={{ mb: 1.5, ...showCopyOnHover }}>
        {bullet.text}
        <CopyButton text={bullet.text} />
      </Typography>
      <TagPicker tags={tags} value={bullet.tag_ids} onChange={(ids) => void save(ids)} label="Tags" placeholder="Add tags" />
      {error && (
        <Alert severity="error" sx={{ mt: 1, borderRadius: 2 }}>
          {error}
        </Alert>
      )}
      <Typography variant="body2" sx={{ fontWeight: 500, mt: 2, mb: 0.5 }}>
        Used in {bullet.resume_count} resume{bullet.resume_count === 1 ? "" : "s"}
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 3 }}>
        {bullet.resumes.map((r) => (
          <Typography component="li" variant="body2" key={r.resume_id} color="text.secondary">
            {formatDate(r.resume_date)} — {r.company ?? "Unknown company"}
            {r.title ? `, ${r.title}` : ""}
          </Typography>
        ))}
      </Box>
    </Box>
  );
}

export default function BulletBankView() {
  const SLOT_LABELS = useSlotLabels();
  const [keywords, setKeywords] = useState("");
  const [debounced, setDebounced] = useState("");
  const [tagFilter, setTagFilter] = useState<number[]>([]);
  const [untagged, setUntagged] = useState(false);
  const [tags, setTags] = useState<BulletTag[]>([]);
  const [bullets, setBullets] = useState<BankBullet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [managing, setManaging] = useState(false);
  const [stats, setStats] = useState<SuggestionStats | null>(null);
  const [progress, setProgress] = useState<TagSuggestProgress | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(keywords), 250);
    return () => clearTimeout(timer);
  }, [keywords]);

  const loadTags = useCallback(async () => {
    setTags(await getBulletTags());
  }, []);

  const search = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await searchBulletBank({ keywords: debounced, tagIds: tagFilter, untagged });
      setBullets(data.bullets);
      setStats(data.suggestion_stats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not search the bullet bank");
    } finally {
      setLoading(false);
    }
  }, [debounced, tagFilter, untagged]);

  useEffect(() => {
    loadTags().catch((err) => setError(err instanceof Error ? err.message : "Could not load tags"));
  }, [loadTags]);

  useEffect(() => {
    void search();
  }, [search]);

  const byId = useMemo(() => new Map(tags.map((t) => [t.id, t])), [tags]);

  // Poll while suggestions run; refresh the bank when they finish. Also
  // picks a run back up after a page reload.
  const running = progress?.running ?? false;
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const next = await getTagSuggestProgress();
        if (cancelled) return;
        setProgress(next);
        if (!next.running && running) void search();
      } catch {
        /* a missed poll is retried on the next tick */
      }
    }
    if (!running && progress !== null) return;
    void poll();
    const timer = running ? setInterval(() => void poll(), 1000) : undefined;
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  async function suggest() {
    setError(null);
    try {
      const started = await startTagSuggestions(bullets.map((b) => b.text));
      setProgress({ running: true, total: started.total, done: 0, report: null, error: null });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start tag suggestions");
    }
  }

  async function decideSuggestion(text: string, suggestionId: number, tagId: number, accept: boolean) {
    try {
      await decideTagSuggestion(suggestionId, accept);
      setBullets((rows) =>
        rows.map((row) =>
          row.text !== text
            ? row
            : {
                ...row,
                suggestions: row.suggestions.filter((s) => s.id !== suggestionId),
                tag_ids: accept ? [...new Set([...row.tag_ids, tagId])].sort((a, b) => a - b) : row.tag_ids,
              },
        ),
      );
      setStats((s) =>
        s && { suggested: s.suggested - 1, accepted: s.accepted + (accept ? 1 : 0), rejected: s.rejected + (accept ? 0 : 1) },
      );
      if (accept) void loadTags();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save that decision");
    }
  }

  const columns: ColumnDef<BankBullet>[] = [
    {
      id: "text",
      label: "Bullet",
      render: (b) => (
        <Box component="span" sx={showCopyOnHover}>
          {b.text}
          <CopyButton text={b.text} />
        </Box>
      ),
    },
    {
      id: "slots",
      label: "Section",
      width: 150,
      render: (b) => b.slots.map((s) => SLOT_LABELS[s] ?? s).join(", "),
    },
    {
      id: "resume_count",
      label: "Resumes",
      width: 90,
      nowrap: true,
      sortValue: (b) => b.resume_count,
      defaultSortDirection: "desc",
      render: (b) => b.resume_count,
    },
    {
      id: "last_used",
      label: "Last used",
      width: 110,
      nowrap: true,
      sortValue: (b) => b.last_used,
      defaultSortDirection: "desc",
      render: (b) => formatDate(b.last_used),
    },
    {
      id: "tags",
      label: "Tags",
      width: 260,
      render: (b) => (
        <Stack direction="row" sx={{ flexWrap: "wrap", gap: 0.5 }}>
          {b.tag_ids.map((id) => {
            const tag = byId.get(id);
            return tag ? <TagChip key={id} tag={tag} /> : null;
          })}
          {b.suggestions.map((s) => {
            const tag = byId.get(s.tag_id);
            return tag ? (
              <SuggestionChip
                key={`s${s.id}`}
                tag={tag}
                reason={s.reason}
                onDecide={(accept) => void decideSuggestion(b.text, s.id, s.tag_id, accept)}
              />
            ) : null;
          })}
        </Stack>
      ),
    },
  ];

  async function tagsChanged() {
    await loadTags();
    await search();
  }

  return (
    <Box>
      <Stack direction="row" spacing={2} sx={{ mb: 2, alignItems: "center", flexWrap: "wrap", rowGap: 1.5 }}>
        <TextField
          size="small"
          label="Keywords"
          placeholder="Comma-separated — e.g. define, ai"
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          slotProps={{ input: { startAdornment: <SearchIcon fontSize="small" sx={{ mr: 1, color: "text.secondary" }} /> } }}
          sx={{ minWidth: 320 }}
        />
        <TagPicker tags={tags} value={tagFilter} onChange={setTagFilter} label="Tags" placeholder="Filter by tags" />
        <FormControlLabel
          control={<Switch size="small" checked={untagged} onChange={(e) => setUntagged(e.target.checked)} />}
          label="Untagged only"
        />
        <Chip
          size="small"
          variant="outlined"
          label={loading ? "Searching…" : `${bullets.length} bullet${bullets.length === 1 ? "" : "s"}`}
        />
        <Box sx={{ flex: 1 }} />
        {stats && stats.accepted + stats.rejected > 0 && (
          <Tooltip title="How often you have agreed with the tag suggester — the measure of how far to trust it.">
            <Typography variant="caption" color="text.secondary">
              Suggestions accepted {stats.accepted} of {stats.accepted + stats.rejected}
            </Typography>
          </Tooltip>
        )}
        <Tooltip title="Ask Haiku to suggest tags for the professional-experience bullets shown here that it has not seen yet. Education, summary and Additional lines are never sent. Nothing is applied until you accept it.">
          <span>
            <Button
              size="small"
              startIcon={running ? <CircularProgress size={14} /> : <AutoAwesomeOutlinedIcon />}
              disabled={running || loading || bullets.length === 0}
              onClick={() => void suggest()}
            >
              {running ? `Suggesting… (${progress?.done ?? 0}/${progress?.total ?? 0})` : "Suggest tags"}
            </Button>
          </span>
        </Tooltip>
        <Button size="small" startIcon={<LocalOfferOutlinedIcon />} onClick={() => setManaging(true)}>
          Manage tags
        </Button>
      </Stack>

      {running && progress && progress.total > 0 && (
        <LinearProgress
          variant="determinate"
          value={(100 * progress.done) / progress.total}
          sx={{ mb: 2, borderRadius: 1 }}
        />
      )}
      {!running && progress?.report && (
        <Alert severity="success" sx={{ mb: 2, borderRadius: 2 }} onClose={() => setProgress(null)}>
          {progress.report.sentences === 0
            ? "Every experience bullet shown here has already been through the suggester."
            : `${progress.report.suggestions} suggestion${progress.report.suggestions === 1 ? "" : "s"} across ${progress.report.sentences} bullet${progress.report.sentences === 1 ? "" : "s"} ($${progress.report.cost_usd.toFixed(4)}). Accept with ✓ or reject with ✗.`}
        </Alert>
      )}
      {!running && progress?.error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }} onClose={() => setProgress(null)}>
          Tag suggestions failed: {progress.error}
        </Alert>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {!loading && bullets.length === 0 ? (
        <Alert severity="info" sx={{ borderRadius: 2 }}>
          No bullets match. Every keyword must appear in the bullet, and every selected tag must be on it.
        </Alert>
      ) : (
        <ExpandableTable
          rows={bullets}
          columns={columns}
          rowKey={(b) => b.text}
          minWidth={1000}
          expanded={(b) => (
            <BulletDetail
              bullet={b}
              tags={tags}
              onTagsSaved={(text, tagIds) => {
                setBullets((rows) => rows.map((row) => (row.text === text ? { ...row, tag_ids: tagIds } : row)));
                void loadTags();
              }}
            />
          )}
        />
      )}

      <ManageTagsDialog open={managing} tags={tags} onClose={() => setManaging(false)} onChanged={tagsChanged} />
    </Box>
  );
}
