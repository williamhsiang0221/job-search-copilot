import { createTheme } from "@mui/material/styles";

// Google's product palette (Gmail / Drive / Cloud Console).
export const google = {
  blue: "#1a73e8",
  blueHover: "#1765cc",
  blueSurface: "#e8f0fe",
  textPrimary: "#202124",
  textSecondary: "#5f6368",
  // Verdict colours. SKIP deliberately has none of its own — it falls back to
  // the border grey, because it is the verdict that means "stop looking".
  green: "#1e8e3e",
  yellow: "#f9ab00",
  red: "#d93025",
  border: "#dadce0",
  surface: "#ffffff",
  background: "#f8f9fa",
};

export const theme = createTheme({
  palette: {
    primary: { main: google.blue, dark: google.blueHover },
    background: { default: google.background, paper: google.surface },
    text: { primary: google.textPrimary, secondary: google.textSecondary },
    divider: google.border,
  },
  typography: {
    fontFamily: '"Google Sans", Roboto, Arial, sans-serif',
    h1: { fontSize: "1.375rem", fontWeight: 400, color: google.textPrimary },
    button: { textTransform: "none", fontWeight: 500, letterSpacing: 0.25 },
    body2: { fontSize: "0.875rem" },
  },
  shape: { borderRadius: 8 },
  components: {
    MuiButton: {
      styleOverrides: {
        root: { borderRadius: 100, paddingInline: 24, boxShadow: "none" },
        contained: { "&:hover": { boxShadow: "0 1px 3px rgba(60,64,67,.3)" } },
      },
    },
    MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
    MuiTableCell: {
      styleOverrides: {
        root: { borderColor: google.border, fontSize: "0.875rem" },
        head: { fontWeight: 500, color: google.textSecondary, backgroundColor: google.background },
      },
    },
  },
});
