import { useContext, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ShellContext } from "../../../app/AppShell";
import { Button, Card, FormField, Input } from "../../../components/ui";
import { changeAccountPassword } from "../../accounts/api";
import { useAuthStore } from "../../../stores/authStore";
import { logout as revokeSession } from "../../auth/api";
import { importAirViolations } from "../../airViolations/api";
import { importIncidents } from "../../news/api";
import { ROLES } from "../../../constants/roles";

type PasswordFormState = {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
};

const emptyPasswordForm: PasswordFormState = {
  currentPassword: "",
  newPassword: "",
  confirmPassword: "",
};

type ImportKind = "incidents" | "air_violations";

type ImportState = {
  file: File | null;
  isSubmitting: boolean;
  error: string | null;
};

const emptyImportState: ImportState = {
  file: null,
  isSubmitting: false,
  error: null,
};

const UploadIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden="true">
    <path
      d="M12 16V7m0 0-3.5 3.5M12 7l3.5 3.5M5 16.5v1a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5v-1"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const ShieldIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden="true">
    <path
      d="M12 3.75 6.75 6v5.1c0 4.25 2.83 8.2 6.73 9.26 3.9-1.06 6.77-5.01 6.77-9.26V6L12 3.75Z"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const DatabaseIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden="true">
    <ellipse cx="12" cy="6.5" rx="6.5" ry="2.75" stroke="currentColor" strokeWidth="1.8" />
    <path
      d="M5.5 6.5v5c0 1.52 2.9 2.75 6.5 2.75s6.5-1.23 6.5-2.75v-5M5.5 11.5v5c0 1.52 2.9 2.75 6.5 2.75s6.5-1.23 6.5-2.75v-5"
      stroke="currentColor"
      strokeWidth="1.8"
    />
  </svg>
);

const ImportPanel = ({
  id,
  label,
  description,
  buttonLabel,
  state,
  onChange,
  onSubmit,
  accent,
  icon,
}: {
  id: string;
  label: string;
  description: string;
  buttonLabel: string;
  state: ImportState;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onSubmit: () => void;
  accent: string;
  icon: ReactNode;
}) => (
  <section className={`group flex h-full flex-col rounded-[1.75rem] border ${accent} bg-[linear-gradient(180deg,rgba(255,255,255,0.98)_0%,rgba(244,248,252,0.98)_100%)] p-5 shadow-[0_18px_40px_rgba(11,34,54,0.08)] transition-transform duration-200 ease-out hover:-translate-y-0.5`}>
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white text-accent shadow-[0_10px_20px_rgba(8,45,111,0.12)]">
          {icon}
        </div>
        <div className="space-y-1">
          <h3 className="text-h4 font-semibold text-text-primary">{label}</h3>
          <p className="text-small leading-6 text-text-muted">{description}</p>
        </div>
      </div>

      <input
        id={id}
        type="file"
        accept=".xlsx"
        onChange={onChange}
        className="sr-only"
      />

      <div className="rounded-2xl border border-border bg-white p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <label
            htmlFor={id}
            className="inline-flex h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 text-small font-semibold text-text-primary transition-colors duration-150 ease-out hover:border-input-border-hover hover:bg-surface-muted"
          >
            <UploadIcon />
            Choose file
          </label>
          <div className="min-w-0 flex-1">
            <p className="truncate text-small font-medium text-text-primary">
              {state.file?.name ?? "No file selected"}
            </p>
          </div>
        </div>
      </div>

      {state.error ? (
        <p className="text-small font-medium text-danger" role="alert">
          {state.error}
        </p>
      ) : null}
    </div>

    <div className="mt-auto pt-5">
      <div className="flex justify-end">
        <Button
          type="button"
          onClick={onSubmit}
          disabled={!state.file}
          isLoading={state.isSubmitting}
          loadingText="Importing"
        >
          {buttonLabel}
        </Button>
      </div>

    </div>
  </section>
);

export const SettingsPage = () => {
  const shell = useContext(ShellContext);
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const role = useAuthStore((state) => state.role);
  const clearSession = useAuthStore((state) => state.logout);
  const [form, setForm] = useState<PasswordFormState>(emptyPasswordForm);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [incidentImport, setIncidentImport] = useState<ImportState>(emptyImportState);
  const [airViolationImport, setAirViolationImport] = useState<ImportState>(emptyImportState);

  const isSuperAdmin = role === ROLES.SUPER_ADMIN;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!user?.id) {
      setSubmitError("Could not identify the signed-in user.");
      return;
    }

    if (form.newPassword !== form.confirmPassword) {
      setSubmitError("New password and confirmation must match.");
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      await changeAccountPassword(user.id, {
        current_password: form.currentPassword,
        new_password: form.newPassword,
      });
      setForm(emptyPasswordForm);
      shell?.showToast("Password changed successfully. Please sign in again.");
      await revokeSession().catch(() => undefined);
      clearSession();
      navigate("/login", { replace: true, state: { passwordChanged: true } });
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setSubmitError(detail ?? "Could not change password. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileChange =
    (kind: ImportKind) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0] ?? null;
      const setter = kind === "incidents" ? setIncidentImport : setAirViolationImport;
      setter((current) => ({
        ...current,
        file,
        error: null,
      }));
    };

  const handleImport = async (kind: ImportKind) => {
    const state = kind === "incidents" ? incidentImport : airViolationImport;
    const setter = kind === "incidents" ? setIncidentImport : setAirViolationImport;

    if (!state.file) {
      setter((current) => ({
        ...current,
        error: "Choose an .xlsx file to upload.",
      }));
      return;
    }

    setter((current) => ({
      ...current,
      isSubmitting: true,
      error: null,
    }));

    try {
      const summary =
        kind === "incidents"
          ? await importIncidents(state.file)
          : await importAirViolations(state.file);
      setter((current) => ({
        ...current,
        isSubmitting: false,
        file: null,
      }));
      const label = kind === "incidents" ? "Incident import" : "Air violation import";
      const toastMessage =
        summary.failed > 0
          ? `${label} finished: ${summary.succeeded} succeeded, ${summary.failed} failed.`
          : `${label} completed successfully: ${summary.succeeded} rows imported.`;
      shell?.showToast(
        toastMessage,
      );
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setter((current) => ({
        ...current,
        isSubmitting: false,
        error: detail ?? "Import failed. Please try again.",
      }));
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-6 2xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] 2xl:items-start">
      <Card className="overflow-hidden p-6 sm:p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-brand-sky/50 text-accent">
            <ShieldIcon />
          </div>
          <div>
            <p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">
              Account security
            </p>
            <h2 className="text-h4 font-semibold text-text-primary">Change password</h2>
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-small text-text-muted">
            Update your account password. You will need your current password to confirm the change.
          </p>
        </div>

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <FormField id="settings-current-password" label="Current password">
            <Input
              id="settings-current-password"
              type="password"
              value={form.currentPassword}
              onChange={(event) => setForm((current) => ({ ...current, currentPassword: event.target.value }))}
              autoComplete="current-password"
              minLength={1}
              required
            />
          </FormField>

          <FormField id="settings-new-password" label="New password">
            <Input
              id="settings-new-password"
              type="password"
              value={form.newPassword}
              onChange={(event) => setForm((current) => ({ ...current, newPassword: event.target.value }))}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </FormField>

          <FormField id="settings-confirm-password" label="Confirm new password">
            <Input
              id="settings-confirm-password"
              type="password"
              value={form.confirmPassword}
              onChange={(event) => setForm((current) => ({ ...current, confirmPassword: event.target.value }))}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </FormField>

          {submitError ? (
            <p className="text-small font-medium text-danger" role="alert">
              {submitError}
            </p>
          ) : null}

          <div className="flex justify-end pt-2">
            <Button type="submit" isLoading={isSubmitting} loadingText="Saving">
              Save password
            </Button>
          </div>
        </form>
      </Card>

      {isSuperAdmin ? (
        <Card className="overflow-hidden p-6 sm:p-8">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-brand-gold-soft/70 text-accent">
              <DatabaseIcon />
            </div>
            <div>
              <p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">
                Data operations
              </p>
              <h2 className="text-h4 font-semibold text-text-primary">Import data</h2>
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-small text-text-muted">
              Upload legacy Excel workbooks to create incidents or air-violation records in bulk.
            </p>
          </div>

          <div className="mt-6 grid gap-5 xl:grid-cols-2">
            <ImportPanel
              id="settings-import-incidents"
              label="Import incidents"
              description="Bulk-create incident records from the legacy workbook without duplicate checks."
              buttonLabel="Import incidents"
              state={incidentImport}
              onChange={handleFileChange("incidents")}
              onSubmit={() => void handleImport("incidents")}
              accent="border-brand-sky/70"
              icon={<UploadIcon />}
            />
            <ImportPanel
              id="settings-import-air-violations"
              label="Import air violations"
              description="Bulk-create air-violation records using the established workbook template."
              buttonLabel="Import air violations"
              state={airViolationImport}
              onChange={handleFileChange("air_violations")}
              onSubmit={() => void handleImport("air_violations")}
              accent="border-brand-gold/60"
              icon={<UploadIcon />}
            />
          </div>
        </Card>
      ) : null}
      </div>
    </div>
  );
};
