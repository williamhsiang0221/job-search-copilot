import { Chip, MenuItem, Select } from "@mui/material";
import { google } from "../theme";

export interface ChipOption {
  value: string;
  label: string;
  color: string;
  /** Defaults to white — most of this app's chip colours are dark enough for it. */
  textColor?: string;
}

interface Props {
  value: string;
  options: ChipOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Shown, chip-styled, for an empty value — e.g. "Unknown". Omit for a
   * column that always has a real value (Status). */
  emptyLabel?: string;
}

/** A Select whose closed value renders as a colour-coded pill, the same
 * shape as VerdictChip, but content-width rather than fixed: unlike
 * Verdict's three equal-length labels, Role/Status/Round vary a lot
 * ("Product Manager" vs "Strategy"), and a fixed width would either waste
 * space or truncate. The open menu stays a plain list — the
 * colour is there to scan the closed table, not to relearn per option. */
export default function ChipSelect({ value, options, onChange, disabled, emptyLabel }: Props) {
  const byValue = new Map(options.map((o) => [o.value, o]));

  return (
    <Select
      variant="standard"
      disableUnderline
      size="small"
      fullWidth
      displayEmpty={!!emptyLabel}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      renderValue={(v) => {
        const opt = byValue.get(v as string);
        if (!opt) {
          return (
            <Chip
              size="small"
              label={emptyLabel ?? (v as string)}
              sx={{ backgroundColor: google.background, color: google.textSecondary, fontWeight: 600 }}
            />
          );
        }
        return (
          <Chip
            size="small"
            label={opt.label}
            sx={{ backgroundColor: opt.color, color: opt.textColor ?? "#fff", fontWeight: 600 }}
          />
        );
      }}
      // No box: just the chip and a small arrow, not a bordered field —
      // the click-to-open dropdown behaviour is unchanged.
      sx={{
        "& .MuiSelect-select": { py: 0.5, backgroundColor: "transparent !important" },
        "&:hover .MuiSelect-select": { backgroundColor: "transparent !important" },
      }}
    >
      {emptyLabel && (
        <MenuItem value="">
          <em>{emptyLabel}</em>
        </MenuItem>
      )}
      {options.map((o) => (
        <MenuItem key={o.value} value={o.value}>
          {o.label}
        </MenuItem>
      ))}
    </Select>
  );
}
