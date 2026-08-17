import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled application error", error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface p-6">
        <section className="max-w-md rounded-lg border border-border bg-surface-raised p-6 text-center shadow-raised" role="alert">
          <h1 className="text-h3 font-semibold text-text-primary">Something went wrong</h1>
          <p className="mt-2 text-small text-text-muted">The page encountered an unexpected error. Reloading usually restores the application safely.</p>
          <button type="button" className="mt-5 h-11 rounded-md bg-button-primary-bg px-4 text-small font-semibold text-button-primary-text hover:bg-button-primary-bg-hover" onClick={() => window.location.reload()}>Reload application</button>
        </section>
      </main>
    );
  }
}
