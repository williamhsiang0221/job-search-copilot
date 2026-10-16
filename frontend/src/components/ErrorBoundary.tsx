import { Component, type ErrorInfo, type ReactNode } from "react";
import { Alert, AlertTitle, Box, Button } from "@mui/material";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches render errors so a crash shows something readable instead of a blank
 * page.
 *
 * Without this, any thrown error unmounts the whole tree and leaves white
 * space — indistinguishable from "the data disappeared", which sends you
 * looking in the database for a problem that is in the browser.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled error in the dashboard:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <Box sx={{ p: 3 }}>
        <Alert
          severity="error"
          sx={{ borderRadius: 2 }}
          action={
            <Button color="inherit" size="small" onClick={() => window.location.reload()}>
              Reload
            </Button>
          }
        >
          <AlertTitle>Something broke in the page</AlertTitle>
          {error.message}
          <Box sx={{ mt: 1, fontSize: "0.8125rem", opacity: 0.85 }}>
            Your stored data is unaffected — this is a display problem. Reloading usually
            clears it, especially after the code has just changed underneath the page.
          </Box>
        </Alert>
      </Box>
    );
  }
}
