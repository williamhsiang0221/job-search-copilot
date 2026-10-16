import { useState } from "react";
import { IconButton, Tooltip } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";

/** Put on the element that holds a line of text: its CopyButton stays
 * hidden until that line is hovered. */
export const showCopyOnHover = { "&:hover .copy-button": { opacity: 1 } } as const;

/** Copies `text` exactly as stored. Hidden until its line is hovered (see
 * showCopyOnHover); keyboard focus also reveals it. The click never reaches
 * a surrounding row, so copying from a table row does not expand it. */
export default function CopyButton({ text }: { text: string }) {
  const [label, setLabel] = useState("Copy");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setLabel("Copied");
    } catch {
      setLabel("Copy failed");
    }
    setTimeout(() => setLabel("Copy"), 1500);
  }

  return (
    <Tooltip title={label} placement="top" disableInteractive>
      <IconButton
        className="copy-button"
        size="small"
        aria-label="Copy text"
        onClick={(e) => {
          e.stopPropagation();
          void copy();
        }}
        sx={{
          p: 0.25,
          ml: 0.5,
          verticalAlign: "text-bottom",
          opacity: 0,
          transition: "opacity 120ms",
          "&:focus-visible": { opacity: 1 },
        }}
      >
        <ContentCopyIcon sx={{ fontSize: 14 }} />
      </IconButton>
    </Tooltip>
  );
}
