import { useState } from "react";
import { Box, Container } from "@mui/material";
import Sidebar from "./components/Sidebar";
import CaptureView from "./components/CaptureView";
import AtsCaptureView from "./components/AtsCaptureView";
import PdfCaptureView from "./components/PdfCaptureView";
import LinkedInJobIdView from "./components/LinkedInJobIdView";
import JobDescriptionsView from "./components/JobDescriptionsView";
import EvaluationsView from "./components/EvaluationsView";
import ApplicationsView from "./components/ApplicationsView";
import DashboardView from "./components/DashboardView";
import NeedsAttachmentsView from "./components/NeedsAttachmentsView";
import ResumeBuilderView from "./components/ResumeBuilderView";
import ErrorBoundary from "./components/ErrorBoundary";
import { PrivacyProvider } from "./privacy";
import { ApplicationsProvider } from "./applicationsContext";

export default function App() {
  // Always "parent/child" — the sidebar owns sub-views now, so the active
  // view is a path rather than a single id.
  const [active, setActive] = useState("capture/linkedin");
  const [parent, child] = active.split("/");
  // Which assembler run the tracer shows — set by Build My Resume so a new
  // run opens straight into its live trace.
  const [assemblyRunId, setAssemblyRunId] = useState<number | null>(null);
  const openAssemblyRun = (id: number) => {
    setAssemblyRunId(id);
    setActive("resume-builder/assembler");
  };

  return (
    <PrivacyProvider>
      <ApplicationsProvider>
        <Box sx={{ display: "flex", minHeight: "100vh" }}>
          <Sidebar active={active} onSelect={setActive} />
          <Box component="main" sx={{ flexGrow: 1, py: 4 }}>
            <Container maxWidth="xl">
              <ErrorBoundary>
                {/*
                  Both Capture sub-views stay mounted and are hidden rather than
                  unmounted, so a run survives switching tabs — recreating one
                  costs a Gmail round trip or a sequential scan across every
                  tracked company.

                  Job descriptions is deliberately the opposite: it unmounts, so
                  returning to it always reloads. That list is cheap to fetch and
                  changes whenever a description is fetched, so stale is worse than
                  a second of loading. Switching between its own sub-views does not
                  remount it, so that reload happens on arrival, not on every click.
                */}
                <Box sx={{ display: active === "capture/linkedin" ? "block" : "none" }}>
                  <CaptureView />
                </Box>
                <Box sx={{ display: active === "capture/ats" ? "block" : "none" }}>
                  <AtsCaptureView />
                </Box>
                {parent === "capture" && child === "linkedin-id" && <LinkedInJobIdView />}
                {parent === "capture" && child === "pdf" && <PdfCaptureView />}
                {parent === "jd" && (
                  <JobDescriptionsView
                    sub={child === "raw" ? "raw" : child === "prompt" ? "prompt" : "normalized"}
                    onOpenAssemblyRun={openAssemblyRun}
                  />
                )}
                {parent === "evaluations" && (
                  <EvaluationsView sub={child === "prompt" ? "prompt" : "history"} />
                )}
                {parent === "applications" && child === "dashboard" && <DashboardView />}
                {parent === "applications" && child === "needs-attachments" && <NeedsAttachmentsView />}
                {parent === "applications" &&
                  child !== "dashboard" &&
                  child !== "needs-attachments" && <ApplicationsView sub={child === "all" ? "all" : "needs"} />}
                {parent === "resume-builder" && (
                  <ResumeBuilderView
                    sub={
                      child === "prompt"
                        ? "prompt"
                        : child === "assembler"
                          ? "assembler"
                          : child === "bullets"
                            ? "bullets"
                            : "icp"
                    }
                    assemblyRunId={assemblyRunId}
                    onSelectAssemblyRun={setAssemblyRunId}
                  />
                )}
              </ErrorBoundary>
            </Container>
          </Box>
        </Box>
      </ApplicationsProvider>
    </PrivacyProvider>
  );
}
