import {
  Box,
  Chip,
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Switch,
  Toolbar,
  Typography,
} from "@mui/material";
import InboxIcon from "@mui/icons-material/MoveToInbox";
import DescriptionIcon from "@mui/icons-material/Description";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import HistoryIcon from "@mui/icons-material/History";
import AssignmentIndIcon from "@mui/icons-material/AssignmentInd";
import VisibilityIcon from "@mui/icons-material/Visibility";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";
import { google } from "../theme";
import { usePrivacy } from "../privacy";
import { useNeedsBackfillCount } from "../applicationsContext";

const DRAWER_WIDTH = 256;

interface Task {
  id: string;
  label: string;
  icon: React.ReactNode;
  ready: boolean;
  /** Sub-views, addressed as `${parent}/${child}`. First one is the default. */
  children?: { id: string; label: string; ready?: boolean }[];
}

// Every workflow is built. Any future one is listed here disabled rather
// than hidden, so the shape of the platform stays visible.
//
// Sub-views live here rather than as tabs inside the page: they are
// destinations, not a control on a view, and the sidebar is where this app
// says where you are.
const TASKS: Task[] = [
  {
    id: "capture",
    label: "Capture",
    icon: <InboxIcon />,
    ready: true,
    children: [
      { id: "linkedin", label: "LinkedIn Job Alerts" },
      { id: "linkedin-id", label: "LinkedIn Job ID" },
      { id: "ats", label: "ATS Boards" },
      { id: "pdf", label: "PDF Upload" },
    ],
  },
  {
    id: "jd",
    label: "Job descriptions",
    icon: <DescriptionIcon />,
    ready: true,
    children: [
      // Normalized leads because it is the working view — what the evaluator
      // reads, and where roles are acted on. Raw exists to settle arguments.
      { id: "normalized", label: "Normalized" },
      { id: "raw", label: "Raw" },
      { id: "prompt", label: "Prompt" },
    ],
  },
  {
    id: "evaluations",
    label: "Evaluations",
    icon: <FactCheckIcon />,
    ready: true,
    children: [
      { id: "history", label: "History" },
      { id: "prompt", label: "Prompt" },
    ],
  },
  {
    id: "resume-builder",
    label: "Resume Builder",
    icon: <AssignmentIndIcon />,
    ready: true,
    children: [
      { id: "icp", label: "ICP Resume" },
      { id: "assembler", label: "Assembler" },
      { id: "bullets", label: "Bullet Bank" },
      { id: "prompt", label: "Prompt" },
    ],
  },
  {
    id: "applications",
    label: "Applications",
    icon: <HistoryIcon />,
    ready: true,
    children: [
      { id: "needs", label: "Needs Backfill" },
      { id: "all", label: "All Applications" },
      { id: "dashboard", label: "Dashboard" },
      // A one-time backfill tool, not a regular workflow — listed last since
      // it is occasional, worked through once and rarely revisited.
      { id: "needs-attachments", label: "Needs JD / Resume" },
    ],
  },
];

/** The path a task opens at: its first child, or the task itself. */
function defaultPath(task: Task): string {
  return task.children?.length ? `${task.id}/${task.children[0].id}` : task.id;
}

interface Props {
  /** Either `id` or `parent/child`. */
  active: string;
  onSelect: (path: string) => void;
}

export default function Sidebar({ active, onSelect }: Props) {
  const [activeParent, activeChild] = active.split("/");
  // Derived from the shared ApplicationsContext, not its own fetch — the
  // sidebar never has to go get this data itself, only read whatever the
  // page you're actually on (or the context's own background poll) already
  // loaded.
  const needsBackfillCount = useNeedsBackfillCount();
  const { masked, toggle: togglePrivacy } = usePrivacy();

  const badges: Record<string, number> = { "applications/needs": needsBackfillCount };

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: DRAWER_WIDTH,
        flexShrink: 0,
        "& .MuiDrawer-paper": {
          width: DRAWER_WIDTH,
          borderRight: `1px solid ${google.border}`,
          backgroundColor: google.background,
          display: "flex",
          flexDirection: "column",
        },
      }}
    >
      <Toolbar sx={{ px: 3 }}>
        <Typography sx={{ fontSize: "1.25rem", color: google.textPrimary }}>
          Job Board
        </Typography>
      </Toolbar>

      <Box sx={{ pr: 1.5 }}>
        <List sx={{ py: 0 }}>
          {TASKS.map((task) => {
            const isActiveParent = activeParent === task.id;

            return (
              <Box key={task.id}>
                <ListItemButton
                  disabled={!task.ready}
                  // A parent with children is never "selected" on its own —
                  // the highlight belongs to whichever child is open, or the
                  // pill would read as a third selected item.
                  selected={isActiveParent && !task.children}
                  onClick={() => onSelect(defaultPath(task))}
                  sx={{
                    // Gmail's rounded-pill nav item.
                    borderRadius: "0 100px 100px 0",
                    minHeight: 40,
                    pl: 3,
                    "&.Mui-selected": {
                      backgroundColor: google.blueSurface,
                      color: google.blue,
                      "& .MuiListItemIcon-root": { color: google.blue },
                      "&:hover": { backgroundColor: google.blueSurface },
                    },
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 36, color: google.textSecondary }}>
                    {task.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={task.label}
                    slotProps={{
                      primary: {
                        sx: {
                          fontSize: "0.875rem",
                          fontWeight: 500,
                          color: isActiveParent && task.children ? google.blue : undefined,
                        },
                      },
                    }}
                  />
                </ListItemButton>

                {task.children?.map((child) => {
                  const badgeCount = badges[`${task.id}/${child.id}`];
                  return (
                    <ListItemButton
                      key={child.id}
                      disabled={child.ready === false}
                      selected={isActiveParent && activeChild === child.id}
                      onClick={() => onSelect(`${task.id}/${child.id}`)}
                      sx={{
                        borderRadius: "0 100px 100px 0",
                        minHeight: 32,
                        // Indented to sit under the parent's label, not its icon.
                        pl: 7.5,
                        "&.Mui-selected": {
                          backgroundColor: google.blueSurface,
                          color: google.blue,
                          "&:hover": { backgroundColor: google.blueSurface },
                        },
                      }}
                    >
                      <ListItemText
                        primary={child.label}
                        slotProps={{ primary: { sx: { fontSize: "0.8125rem" } } }}
                      />
                      {!!badgeCount && (
                        <Chip
                          size="small"
                          label={badgeCount}
                          sx={{
                            height: 18,
                            minWidth: 18,
                            fontSize: "0.6875rem",
                            fontWeight: 600,
                            backgroundColor: google.blue,
                            color: "#fff",
                            "& .MuiChip-label": { px: 0.75 },
                          }}
                        />
                      )}
                    </ListItemButton>
                  );
                })}
              </Box>
            );
          })}
        </List>
      </Box>

      <Box
        sx={{
          mt: "auto",
          display: "flex",
          alignItems: "center",
          gap: 1,
          pl: 3,
          pr: 2,
          py: 1,
          borderTop: `1px solid ${google.border}`,
          color: google.textSecondary,
        }}
      >
        {masked ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
        <Typography sx={{ fontSize: "0.8125rem", flexGrow: 1 }}>Mask sensitive info</Typography>
        <Switch size="small" checked={masked} onChange={togglePrivacy} />
      </Box>
    </Drawer>
  );
}

export { DRAWER_WIDTH };
