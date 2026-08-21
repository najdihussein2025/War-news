import { useContext, useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ShellContext } from "../../../app/AppShell";
import { Button, Card, FormField, Input } from "../../../components/ui";
import { changeAccountPassword } from "../../accounts/api";
import { useAuthStore } from "../../../stores/authStore";
import { logout as revokeSession } from "../../auth/api";
import { importAirViolations } from "../../airViolations/api";
import { importIncidents, type WorkbookImportSummary } from "../../news/api";
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
  summary: WorkbookImportSummary | null;
};

const emptyImportState: ImportState = {
  file: null,
  isSubmitting: false,
  error: null,
  summary: null,
};

const SummaryPanel = ({ summary }: { summary: WorkbookImportSummary }) => (
  <div className="rounded-lg border border-border bg-surface p-4">
    <div className="grid gap-3 sm:grid-cols-3">
      <div>
        <p className="text-caption font-semibold uppercase text-text-muted">Processed</p>
        <p className="mt-1 text-body font-semibold text-text-primary">{summary.processed}</p>
      </div>
      <div>
        <p className="text-caption font-semibold uppercase text-text-muted">Succeeded</p>
        <p className="mt-1 text-body font-semibold text-text-primary">{summary.succeeded}</p>
      </div>
      <div>
        <p className="text-caption font-semibold uppercase text-text-muted">Failed</p>
        <p className="mt-1 text-body font-semibold text-text-primary">{summary.failed}</p>
      </div>
    </div>
    {summary.row_errors.length > 0 ? (
      <div className="mt-4 space-y-2">
        <h3 className="text-small font-semibold text-text-primary">Failed rows</h3>
        <ul className="space-y-2 text-small text-text-muted">
          {summary.row_errors.map((rowError) => (
            <li key={`${rowError.row}-${rowError.error}`} className="rounded-md border border-border bg-surface-raised px-3 py-2">
              Row {rowError.row}: {rowError.error}
            </li>
          ))}
        </ul>
      </div>
    ) : null}
  </div>
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
      summary: null,
    }));

    try {
      const summary =
        kind === "incidents"
          ? await importIncidents(state.file)
          : await importAirViolations(state.file);
      setter((current) => ({
        ...current,
        isSubmitting: false,
        summary,
      }));
      shell?.showToast(
        kind === "incidents"
          ? "Incident import completed."
          : "Air violation import completed.",
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
      <Card className="max-w-2xl p-6 sm:p-8">
        <div className="space-y-2">
          <h2 className="text-h4 font-semibold text-text-primary">Change password</h2>
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
        <Card className="max-w-2xl p-6 sm:p-8">
          <div className="space-y-2">
            <h2 className="text-h4 font-semibold text-text-primary">Import data</h2>
            <p className="text-small text-text-muted">
              Upload legacy Excel workbooks to create incidents or air-violation records in bulk.
            </p>
          </div>

          <div className="mt-6 space-y-6">
            <div className="space-y-4">
              <FormField
                id="settings-import-incidents"
                label="Import incidents"
                hint="Legacy 191-column .xlsx format"
              >
                <Input
                  id="settings-import-incidents"
                  type="file"
                  accept=".xlsx"
                  onChange={handleFileChange("incidents")}
                />
              </FormField>

              {incidentImport.error ? (
                <p className="text-small font-medium text-danger" role="alert">
                  {incidentImport.error}
                </p>
              ) : null}

              <div className="flex justify-end">
                <Button
                  type="button"
                  onClick={() => void handleImport("incidents")}
                  disabled={!incidentImport.file}
                  isLoading={incidentImport.isSubmitting}
                  loadingText="Importing"
                >
                  Import incidents
                </Button>
              </div>

              {incidentImport.summary ? <SummaryPanel summary={incidentImport.summary} /> : null}
            </div>

            <div className="border-t border-border pt-6">
              <div className="space-y-4">
                <FormField
                  id="settings-import-air-violations"
                  label="Import air violations"
                  hint="11-column .xlsx format"
                >
                  <Input
                    id="settings-import-air-violations"
                    type="file"
                    accept=".xlsx"
                    onChange={handleFileChange("air_violations")}
                  />
                </FormField>

                {airViolationImport.error ? (
                  <p className="text-small font-medium text-danger" role="alert">
                    {airViolationImport.error}
                  </p>
                ) : null}

                <div className="flex justify-end">
                  <Button
                    type="button"
                    onClick={() => void handleImport("air_violations")}
                    disabled={!airViolationImport.file}
                    isLoading={airViolationImport.isSubmitting}
                    loadingText="Importing"
                  >
                    Import air violations
                  </Button>
                </div>

                {airViolationImport.summary ? <SummaryPanel summary={airViolationImport.summary} /> : null}
              </div>
            </div>
          </div>
        </Card>
      ) : null}
    </div>
  );
};
