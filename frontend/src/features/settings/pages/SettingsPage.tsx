import { useContext, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ShellContext } from "../../../app/AppShell";
import { Button, Card, FormField, Input } from "../../../components/ui";
import { changeAccountPassword } from "../../accounts/api";
import { useAuthStore } from "../../../stores/authStore";
import { logout as revokeSession } from "../../auth/api";

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

export const SettingsPage = () => {
  const shell = useContext(ShellContext);
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const clearSession = useAuthStore((state) => state.logout);
  const [form, setForm] = useState<PasswordFormState>(emptyPasswordForm);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

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
    </div>
  );
};
