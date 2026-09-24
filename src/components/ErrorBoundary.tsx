import React from "react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

// A render-time crash anywhere in the tree below this (a null-pointer on a
// malformed API payload, a third-party chart library choking on unexpected
// data, ...) would otherwise unmount the entire app and leave a blank white
// page with nothing but a console error the user will never see. This is the
// last line of defense: it can't catch errors from event handlers or async
// code (those already go through each call site's own try/catch and
// ApiError handling), only errors thrown while React is rendering — but for
// that class of failure it's the only thing standing between a real crash
// and a page that recovers.
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // Logged for anyone looking at the browser console or an error-tracking
    // integration, but never rendered to the page — the fallback UI below is
    // deliberately generic so no stack trace or internal detail ever reaches
    // the user.
    console.error("Unhandled error in the dashboard UI:", error);
  }

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "0.75rem",
          padding: "2rem",
          textAlign: "center",
          background: "var(--bg-base, #0f131c)",
          color: "var(--text-primary, #dfe2ef)",
        }}
      >
        <div style={{ fontSize: "2.5rem" }}>⚠️</div>
        <div style={{ fontSize: "1.05rem", fontWeight: 600, fontFamily: "Lora, serif" }}>
          Something went wrong
        </div>
        <div style={{ fontSize: "0.875rem", color: "var(--text-muted, #908fa0)", maxWidth: "28rem" }}>
          The dashboard hit an unexpected error and couldn't continue. Reloading the page usually
          fixes this.
        </div>
        <button
          onClick={this.handleReload}
          style={{
            marginTop: "0.5rem",
            padding: "0.5rem 1.25rem",
            borderRadius: "0.5rem",
            border: "1px solid var(--border, rgba(49, 53, 63, 0.6))",
            background: "var(--accent-dim, rgba(128, 131, 255, 0.15))",
            color: "var(--accent-light, #c0c1ff)",
            fontSize: "0.875rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Reload page
        </button>
      </div>
    );
  }
}
