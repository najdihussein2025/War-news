import { useEffect, useState, type FocusEvent, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { logout as revokeSession } from "../api";
import { useLogin } from "../hooks";
import { getLoginErrorMessage } from "../loginErrors";
import { useAuthStore } from "../../../stores/authStore";
import { ROLES } from "../../../constants/roles";
import { Button, Card, FormField, Input } from "../../../components/ui";
import { cn } from "../../../lib/cn";

type FieldName = "username" | "password";

const UserIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M20 21a8 8 0 0 0-16 0" />
    <circle cx="12" cy="8" r="4" />
  </svg>
);

const LockIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </svg>
);

const EyeIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const EyeOffIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="m3 3 18 18" />
    <path d="M10.6 10.6a3 3 0 0 0 4.2 4.2" />
    <path d="M9.9 4.2A10.8 10.8 0 0 1 12 4c7 0 10 8 10 8a16.5 16.5 0 0 1-3.1 4.4" />
    <path d="M6.1 6.1C3.4 8 2 12 2 12s3 8 10 8a10.8 10.8 0 0 0 5.9-1.7" />
  </svg>
);

const IdentityHeader = ({ compact = false }: { compact?: boolean }) => (
  <div className={cn("space-y-4", compact && "space-y-3")}>
    <div
      className={cn(
        "flex items-center",
        compact ? "max-w-xs gap-5" : "max-w-md gap-7",
      )}
      aria-label="National Council for Scientific Research and National Center for Natural Hazards and Early Warning"
    >
      <img
        src="/cnrs-logo-transparent.png"
        alt="National Council for Scientific Research"
        className="h-auto min-w-0 flex-1 object-contain"
      />
      <img
        src="/ncne-logo-transparent.png"
        alt="National Center for Natural Hazards and Early Warning"
        className="h-auto min-w-0 flex-1 object-contain"
      />
    </div>
    <div className="space-y-2">
      <p className="text-caption font-semibold uppercase text-text-muted">Secure Records Access</p>
      <h1
        className={cn(
          "font-semibold text-text-primary",
          compact ? "text-h2 sm:text-h1" : "text-display",
        )}
      >
        War News 2026
      </h1>
    </div>
  </div>
);

export const LoginPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [sessionOnEntry] = useState(() => useAuthStore.getState().isAuthenticated);
  const clearSession = useAuthStore((state) => state.logout);
  const loginMutation = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const [touchedFields, setTouchedFields] = useState<Record<FieldName, boolean>>({
    username: false,
    password: false,
  });

  useEffect(() => {
    if (!sessionOnEntry) return;
    void revokeSession().catch(() => undefined);
    clearSession();
  }, [clearSession, sessionOnEntry]);

  const requestedPath = (location.state as { from?: string } | null)?.from;

  const fieldErrors: Partial<Record<FieldName, string>> = {
    username: touchedFields.username && username.trim() === "" ? "Username is required." : "",
    password: touchedFields.password && password === "" ? "Password is required." : "",
  };

  const validateAllFields = () => {
    setTouchedFields({ username: true, password: true });
    return username.trim() !== "" && password !== "";
  };

  const handleBlur = (event: FocusEvent<HTMLInputElement>) => {
    const fieldName = event.target.name as FieldName;
    setTouchedFields((current) => ({ ...current, [fieldName]: true }));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (loginMutation.isPending || !validateAllFields()) {
      return;
    }

    loginMutation.mutate(
      { username, password },
      {
        onSuccess: (data) => {
          const dashboard = data.role === ROLES.SUPER_ADMIN
            ? "/superadmin/dashboard"
            : "/admin/dashboard";
          navigate(requestedPath || dashboard, { replace: true });
        },
      },
    );
  };

  const hasLoginError = loginMutation.isError;
  const loginErrorMessage = hasLoginError ? getLoginErrorMessage(loginMutation.error) : "";

  return (
    <main className="min-h-screen bg-surface font-sans text-text-primary lg:grid lg:h-screen lg:min-h-0 lg:grid-cols-2 lg:overflow-hidden">
      <section className="brand-hero relative hidden overflow-hidden px-10 py-8 lg:flex lg:h-full lg:min-h-0 lg:flex-col lg:items-center lg:justify-center">
        <div className="relative z-10 w-full max-w-xl rounded-lg border border-white/40 bg-white/95 p-8 shadow-overlay backdrop-blur-sm xl:p-10">
          <IdentityHeader />
          <p className="mt-6 max-w-md text-body-large text-text-muted">
            Internal incident records for review, source control, and administrative oversight.
          </p>
        </div>
      </section>

      <section className="login-auth-panel flex min-h-screen items-center justify-center border-t-4 border-brand-gold px-4 py-8 lg:h-full lg:min-h-0 lg:border-l lg:border-border lg:border-t-0 lg:px-10 lg:py-8">
        <div className="w-full min-w-0 max-w-md space-y-5">
          <div className="lg:hidden">
            <IdentityHeader compact />
          </div>

          <Card className="animate-card-enter w-full border-t-4 border-t-brand-gold p-7 shadow-overlay sm:p-8">
        <form onSubmit={handleSubmit} noValidate>
          <div className="space-y-2">
            <h2 className="text-h3 font-semibold text-text-primary">Sign in</h2>
            <p className="text-small text-text-muted">Use your assigned administrator account.</p>
          </div>

          <div className="mt-6 space-y-4">
            <FormField id="username" label="Username" error={fieldErrors.username || undefined}>
              <Input
                id="username"
                name="username"
                placeholder="Enter your username"
                value={username}
                onChange={(event) => {
                  setUsername(event.target.value);
                  loginMutation.reset();
                }}
                onBlur={handleBlur}
                autoComplete="username"
                required
                aria-invalid={Boolean(fieldErrors.username || hasLoginError) || undefined}
                aria-describedby={fieldErrors.username ? "username-error" : undefined}
                leadingElement={<UserIcon className="h-4 w-4" />}
              />
            </FormField>

            <FormField id="password" label="Password" error={fieldErrors.password || undefined}>
              <Input
                id="password"
                name="password"
                type={isPasswordVisible ? "text" : "password"}
                placeholder="Enter your password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  loginMutation.reset();
                }}
                onBlur={handleBlur}
                autoComplete="current-password"
                required
                aria-invalid={Boolean(fieldErrors.password || hasLoginError) || undefined}
                aria-describedby={fieldErrors.password ? "password-error" : undefined}
                leadingElement={<LockIcon className="h-4 w-4" />}
                trailingElement={
                  <button
                    type="button"
                    className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted transition-colors duration-150 ease-out hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                    onClick={() => setIsPasswordVisible((value) => !value)}
                    aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                  >
                    {isPasswordVisible ? (
                      <EyeOffIcon className="h-4 w-4" />
                    ) : (
                      <EyeIcon className="h-4 w-4" />
                    )}
                  </button>
                }
              />
            </FormField>
          </div>

          {hasLoginError ? (
            <p
              className="mt-5 rounded-md border border-danger bg-surface-raised px-3 py-2 text-small text-danger"
              role="alert"
              aria-live="polite"
            >
              {loginErrorMessage}
            </p>
          ) : null}

          <Button
            className="mt-6 w-full"
            type="submit"
            isLoading={loginMutation.isPending}
            loadingText="Signing in"
          >
            Sign in
          </Button>
        </form>
          </Card>

          <p className="text-center text-caption text-text-muted">Authorized personnel only</p>
        </div>
      </section>
    </main>
  );
};
