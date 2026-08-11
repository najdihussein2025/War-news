import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { ShellContext } from "../../../app/AppShell";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, Card, EmptyState, FormField, Input, Label } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { createAccount, deleteAccount, setAccountActive } from "../api";
import { useAccounts } from "../hooks";
import type { MockUser, MockUserRole } from "../../../mocks/mockUsers";

type SortKey = "username" | "full_name" | "role" | "last_login_at" | "is_active";
type SortDirection = "asc" | "desc";
type DialogMode = "create" | "edit";
type ConfirmAction = "active" | "delete";
type UserFormState = {
  username: string;
  full_name: string;
  password: string;
  role: MockUserRole;
  is_active: boolean;
};

const focusableSelector =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const emptyForm: UserFormState = {
  username: "",
  full_name: "",
  password: "",
  role: "super_admin",
  is_active: true,
};

const roleLabels: Record<MockUserRole, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
};

const now = new Date("2026-08-10T12:00:00+03:00");
const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

const IconBase = ({ children, className }: { children: ReactNode; className?: string }) => (
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
    {children}
  </svg>
);

const CheckIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="m5 12 4 4L19 6" />
  </IconBase>
);

const PauseIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M8 5v14" />
    <path d="M16 5v14" />
  </IconBase>
);

const MoreIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <circle cx="12" cy="12" r="1" />
    <circle cx="19" cy="12" r="1" />
    <circle cx="5" cy="12" r="1" />
  </IconBase>
);

const SortIcon = ({ direction, active }: { direction: SortDirection; active: boolean }) => (
  <IconBase className="ml-2 h-3.5 w-3.5 text-text-muted">
    {active && direction === "asc" ? (
      <>
        <path d="m7 9 5-5 5 5" />
        <path d="M12 4v16" />
      </>
    ) : active ? (
      <>
        <path d="m7 15 5 5 5-5" />
        <path d="M12 4v16" />
      </>
    ) : (
      <>
        <path d="m8 7 4-4 4 4" />
        <path d="m8 17 4 4 4-4" />
        <path d="M12 3v18" />
      </>
    )}
  </IconBase>
);

const formatRelativeTime = (value: string | null) => {
  if (!value) {
    return "Never";
  }

  const diffMs = new Date(value).getTime() - now.getTime();
  const diffMinutes = Math.round(diffMs / 60000);
  const absMinutes = Math.abs(diffMinutes);

  if (absMinutes < 60) {
    return relativeFormatter.format(diffMinutes, "minute");
  }

  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return relativeFormatter.format(diffHours, "hour");
  }

  const diffDays = Math.round(diffHours / 24);
  if (Math.abs(diffDays) < 30) {
    return relativeFormatter.format(diffDays, "day");
  }

  const diffMonths = Math.round(diffDays / 30);
  return relativeFormatter.format(diffMonths, "month");
};

const compareUsers = (a: MockUser, b: MockUser, key: SortKey) => {
  const aValue = a[key];
  const bValue = b[key];

  if (key === "last_login_at") {
    return (aValue ? new Date(aValue as string).getTime() : 0) - (bValue ? new Date(bValue as string).getTime() : 0);
  }

  if (key === "is_active") {
    return Number(aValue) - Number(bValue);
  }

  return String(aValue).localeCompare(String(bValue));
};

const Dialog = ({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) => {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const focusableElements = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? [],
    );
    focusableElements[0]?.focus();

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        onCloseRef.current();
        return;
      }

      if (event.key !== "Tab" || focusableElements.length === 0) {
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4">
      <section
        ref={dialogRef}
        className="w-full max-w-lg rounded-lg border border-border bg-surface-raised p-6 shadow-overlay"
        role="dialog"
        aria-modal="true"
        aria-labelledby="account-dialog-title"
      >
        <div className="flex items-center justify-between gap-4">
          <h2 id="account-dialog-title" className="text-h4 font-semibold text-text-primary">
            {title}
          </h2>
          <button
            type="button"
            className="rounded-md px-2 py-1 text-small font-semibold text-text-muted transition-colors duration-150 ease-out hover:bg-surface-muted hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <div className="mt-5">{children}</div>
      </section>
    </div>
  );
};

const RoleBadge = ({ role }: { role: MockUserRole }) => (
  <StatusBadge label={roleLabels[role]} variant={role === "super_admin" ? "accent" : "neutral"} />
);

const ActivityState = ({ isActive }: { isActive: boolean }) => (
  <span className="inline-flex items-center gap-2 text-small font-medium text-text-primary">
    <span className="flex h-6 w-6 items-center justify-center rounded-md border border-border bg-surface-muted text-text-muted">
      {isActive ? <CheckIcon className="h-3.5 w-3.5" /> : <PauseIcon className="h-3.5 w-3.5" />}
    </span>
    {isActive ? "Active" : "Inactive"}
  </span>
);

const SortButton = ({
  children,
  sortKey,
  activeSort,
  onSort,
}: {
  children: ReactNode;
  sortKey: SortKey;
  activeSort: { key: SortKey; direction: SortDirection };
  onSort: (key: SortKey) => void;
}) => (
  <button
    type="button"
    className="inline-flex items-center text-left text-caption font-semibold uppercase text-text-muted transition-colors duration-150 ease-out hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    onClick={() => onSort(sortKey)}
  >
    {children}
    <SortIcon direction={activeSort.direction} active={activeSort.key === sortKey} />
  </button>
);

const AccountForm = ({
  mode,
  value,
  onChange,
  onSubmit,
  onCancel,
  isSubmitting,
  submitError,
}: {
  mode: DialogMode;
  value: UserFormState;
  onChange: (nextValue: UserFormState) => void;
  onSubmit: () => void | Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
  submitError: string | null;
}) => {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <FormField id="account-username" label="Username">
        <Input
          id="account-username"
          value={value.username}
          onChange={(event) => onChange({ ...value, username: event.target.value })}
          required
        />
      </FormField>
      <FormField id="account-full-name" label="Full name">
        <Input
          id="account-full-name"
          value={value.full_name}
          onChange={(event) => onChange({ ...value, full_name: event.target.value })}
          required
        />
      </FormField>
      {mode === "create" ? (
        <FormField id="account-password" label="Password">
          <Input
            id="account-password"
            type="password"
            value={value.password}
            onChange={(event) => onChange({ ...value, password: event.target.value })}
            minLength={8}
            autoComplete="new-password"
            required
          />
        </FormField>
      ) : null}
      <div className="space-y-2">
        <Label htmlFor="account-role">Role</Label>
        <select
          id="account-role"
          className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary transition-colors duration-150 ease-out hover:border-input-border-hover focus:border-input-border-focus focus:bg-surface focus:outline-none focus:ring-2 focus:ring-focus-ring focus:ring-offset-1 focus:ring-offset-surface-raised"
          value={value.role}
          onChange={(event) => onChange({ ...value, role: event.target.value as MockUserRole })}
        >
          <option value="super_admin">Super Admin</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      {mode === "edit" ? (
        <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-surface p-3">
        <div>
          <p className="text-small font-semibold text-text-primary">Active account</p>
          <p className="text-caption text-text-muted">Inactive users cannot access protected tools later.</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={value.is_active}
          className={cn(
            "flex h-7 w-12 items-center rounded-full border border-border p-1 transition-colors duration-150 ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
            value.is_active ? "justify-end bg-surface-muted" : "justify-start bg-surface",
          )}
          onClick={() => onChange({ ...value, is_active: !value.is_active })}
        >
          <span className="h-4 w-4 rounded-full bg-accent" />
        </button>
        </div>
      ) : null}
      {submitError ? (
        <p className="text-small font-medium text-danger" role="alert">
          {submitError}
        </p>
      ) : null}
      <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting} loadingText="Creating user">
          {mode === "create" ? "Create user" : "Save changes"}
        </Button>
      </div>
    </form>
  );
};

export const AccountsPage = () => {
  const { data: accountData, isLoading, isError } = useAccounts();
  const shell = useContext(ShellContext);
  const [users, setUsers] = useState<MockUser[]>([]);
  const [sort, setSort] = useState<{ key: SortKey; direction: SortDirection }>({
    key: "username",
    direction: "asc",
  });
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [dialogMode, setDialogMode] = useState<DialogMode | null>(null);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [formState, setFormState] = useState<UserFormState>(emptyForm);
  const [confirmUser, setConfirmUser] = useState<MockUser | null>(null);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [localToast, setLocalToast] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!accountData) {
      return;
    }

    setUsers(
      accountData.map((account) => ({
        id: account.id,
        username: account.username,
        full_name: account.full_name,
        role: account.role.name,
        is_active: account.is_active,
        last_login_at: account.last_login_at,
        created_at: account.created_at,
      })),
    );
  }, [accountData]);

  const showToast = (message: string) => {
    if (shell) {
      shell.showToast(message);
      return;
    }

    setLocalToast(message);
    window.setTimeout(() => setLocalToast(null), 3600);
  };

  const openCreateDialog = () => {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setFormState(emptyForm);
    setSubmitError(null);
    setEditingUserId(null);
    setDialogMode("create");
  };

  useEffect(() => {
    shell?.setPageAction(
      <Button type="button" className="w-full sm:w-auto" onClick={openCreateDialog}>
        New User
      </Button>,
    );

    return () => shell?.setPageAction(null);
  }, [shell]);

  const sortedUsers = useMemo(() => {
    return [...users].sort((a, b) => {
      const result = compareUsers(a, b, sort.key);
      return sort.direction === "asc" ? result : -result;
    });
  }, [sort, users]);

  const closeDialog = useCallback(() => {
    setDialogMode(null);
    setConfirmUser(null);
    setConfirmAction(null);
    window.setTimeout(() => returnFocusRef.current?.focus(), 0);
  }, []);

  const handleSort = (key: SortKey) => {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  };

  const openEditDialog = (user: MockUser) => {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setOpenMenuId(null);
    setEditingUserId(user.id);
    setFormState({
      username: user.username,
      full_name: user.full_name,
      password: "",
      role: user.role,
      is_active: user.is_active,
    });
    setDialogMode("edit");
  };

  const handleSubmit = async () => {
    if (dialogMode === "create") {
      setIsSubmitting(true);
      setSubmitError(null);
      try {
        const account = await createAccount({
          username: formState.username.trim(),
          full_name: formState.full_name.trim(),
          password: formState.password,
          role_id: formState.role === "super_admin" ? 1 : 2,
        });
        setUsers((current) => [
          {
            id: account.id,
            username: account.username,
            full_name: account.full_name,
            role: account.role.name,
            is_active: account.is_active,
            last_login_at: account.last_login_at,
            created_at: account.created_at,
          },
          ...current,
        ]);
        showToast(`${account.full_name} was saved.`);
        closeDialog();
      } catch (error) {
        const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        setSubmitError(detail ?? "Could not save the user. Please try again.");
      } finally {
        setIsSubmitting(false);
      }
      return;
    } else if (dialogMode === "edit" && editingUserId) {
      setUsers((current) =>
        current.map((user) =>
          user.id === editingUserId
            ? {
                ...user,
                username: formState.username,
                full_name: formState.full_name,
                role: formState.role,
                is_active: formState.is_active,
              }
            : user,
        ),
      );
      showToast(`${formState.full_name} was updated.`);
    }

    closeDialog();
  };

  const requestActiveChange = (user: MockUser) => {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setOpenMenuId(null);
    setConfirmAction("active");
    setConfirmUser(user);
  };

  const requestDelete = (user: MockUser) => {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setOpenMenuId(null);
    setConfirmAction("delete");
    setConfirmUser(user);
  };

  const confirmActiveChange = async () => {
    if (!confirmUser) {
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const updated = await setAccountActive(confirmUser.id, !confirmUser.is_active);
      setUsers((current) => current.map((user) =>
        user.id === updated.id ? { ...user, is_active: updated.is_active } : user,
      ));
      showToast(`${confirmUser.full_name} was ${updated.is_active ? "reactivated" : "deactivated"}.`);
      closeDialog();
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setSubmitError(detail ?? "Could not change the account status.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const confirmDelete = async () => {
    if (!confirmUser) {
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);
    try {
      await deleteAccount(confirmUser.id);
      setUsers((current) => current.filter((user) => user.id !== confirmUser.id));
      showToast(`${confirmUser.full_name} was deleted.`);
      closeDialog();
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setSubmitError(detail ?? "Could not delete the user.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMenuKeyDown = (event: KeyboardEvent<HTMLButtonElement>, userId: string) => {
    if (event.key === "Escape") {
      setOpenMenuId(null);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpenMenuId((current) => (current === userId ? null : userId));
    }
  };

  if (isLoading) {
    return (
      <Card>
        <EmptyState title="Loading users" description="Reading accounts from the database." />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <EmptyState
          title="Could not load users"
          description="The accounts API could not read users from the database."
        />
      </Card>
    );
  }

  if (users.length === 0) {
    return (
      <>
        <Card>
          <EmptyState
            title="No users yet"
            description="Create the first Super Admin or Admin account."
            className="min-h-80"
          />
          <div className="flex justify-center border-t border-border px-6 py-5">
            <Button type="button" onClick={openCreateDialog}>
              New User
            </Button>
          </div>
        </Card>

        {dialogMode === "create" ? (
          <Dialog title="New User" onClose={closeDialog}>
            <AccountForm
              mode="create"
              value={formState}
              onChange={setFormState}
              onSubmit={handleSubmit}
              onCancel={closeDialog}
              isSubmitting={isSubmitting}
              submitError={submitError}
            />
          </Dialog>
        ) : null}
      </>
    );
  }

  return (
    <>
      {localToast ? (
        <div className="fixed right-4 top-4 z-50 max-w-sm rounded-lg border border-border bg-surface-raised px-4 py-3 text-small font-medium text-text-primary shadow-overlay">
          {localToast}
        </div>
      ) : null}

      <Card className="min-h-[360px] overflow-visible">
        <div className="min-h-[360px] overflow-x-auto">
          <table className="min-w-[980px] w-full border-collapse">
            <thead className="sticky top-0 z-10 bg-surface-raised">
              <tr className="border-b border-border">
                <th className="px-4 py-3 text-left">
                  <SortButton sortKey="username" activeSort={sort} onSort={handleSort}>
                    Username
                  </SortButton>
                </th>
                <th className="px-4 py-3 text-left">
                  <SortButton sortKey="full_name" activeSort={sort} onSort={handleSort}>
                    Full name
                  </SortButton>
                </th>
                <th className="px-4 py-3 text-left">
                  <SortButton sortKey="role" activeSort={sort} onSort={handleSort}>
                    Role
                  </SortButton>
                </th>
                <th className="px-4 py-3 text-left">
                  <SortButton sortKey="last_login_at" activeSort={sort} onSort={handleSort}>
                    Last login
                  </SortButton>
                </th>
                <th className="px-4 py-3 text-left">
                  <SortButton sortKey="is_active" activeSort={sort} onSort={handleSort}>
                    Status
                  </SortButton>
                </th>
                <th className="px-4 py-3 text-right text-caption font-semibold uppercase text-text-muted">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sortedUsers.map((user) => (
                <tr
                  key={user.id}
                  className="transition-colors duration-150 ease-out hover:bg-surface-muted"
                >
                  <td className="px-4 py-4 text-small font-semibold text-text-primary">
                    {user.username}
                  </td>
                  <td className="px-4 py-4 text-small text-text-primary">{user.full_name}</td>
                  <td className="px-4 py-4">
                    <RoleBadge role={user.role} />
                  </td>
                  <td className="px-4 py-4 text-small text-text-muted">
                    {formatRelativeTime(user.last_login_at)}
                  </td>
                  <td className="px-4 py-4">
                    <ActivityState isActive={user.is_active} />
                  </td>
                  <td className="relative px-4 py-4 text-right">
                    <button
                      type="button"
                      className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface-raised text-text-muted transition-colors duration-150 ease-out hover:bg-surface-muted hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                      aria-label={`Open actions for ${user.full_name}`}
                      aria-expanded={openMenuId === user.id}
                      onClick={() => setOpenMenuId((current) => (current === user.id ? null : user.id))}
                      onKeyDown={(event) => handleMenuKeyDown(event, user.id)}
                    >
                      <MoreIcon className="h-4 w-4" />
                    </button>
                    {openMenuId === user.id ? (
                      <div className="absolute right-4 top-14 z-20 w-56 rounded-lg border border-border bg-surface-raised p-1.5 text-left shadow-overlay">
                        <button
                          type="button"
                          className="block w-full rounded-md px-3 py-2 text-left text-small font-medium text-text-primary hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                          onClick={() => openEditDialog(user)}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="block w-full rounded-md px-3 py-2 text-left text-small font-medium text-danger hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                          onClick={() => requestActiveChange(user)}
                        >
                          {user.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                        <button
                          type="button"
                          className="mt-1 block w-full rounded-md border-t border-border px-3 py-2 text-left text-small font-medium text-danger hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                          onClick={() => requestDelete(user)}
                        >
                          Delete
                        </button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {dialogMode ? (
        <Dialog title={dialogMode === "create" ? "New User" : "Edit User"} onClose={closeDialog}>
          <AccountForm
            mode={dialogMode}
            value={formState}
            onChange={setFormState}
            onSubmit={handleSubmit}
            onCancel={closeDialog}
            isSubmitting={isSubmitting}
            submitError={submitError}
          />
        </Dialog>
      ) : null}

      {confirmUser ? (
        <Dialog
          title={
            confirmAction === "delete"
              ? `Delete ${confirmUser.full_name}?`
              : `${confirmUser.is_active ? "Deactivate" : "Reactivate"} ${confirmUser.full_name}?`
          }
          onClose={closeDialog}
        >
          <div className="space-y-5">
            <p className="text-small text-text-muted">
              {confirmAction === "delete" ? (
                <>
                  This will permanently remove{" "}
                  <span className="font-semibold text-text-primary">{confirmUser.full_name}</span>.
                </>
              ) : (
                <>
                  This will mark{" "}
                  <span className="font-semibold text-text-primary">{confirmUser.full_name}</span>{" "}
                  as {confirmUser.is_active ? "inactive" : "active"}.
                </>
              )}
            </p>
            {submitError ? <p className="text-small font-medium text-danger" role="alert">{submitError}</p> : null}
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <Button type="button" variant="secondary" onClick={closeDialog}>
                Cancel
              </Button>
              <Button
                type="button"
                variant={confirmAction === "delete" || confirmUser.is_active ? "destructive" : "primary"}
                onClick={confirmAction === "delete" ? confirmDelete : confirmActiveChange}
                isLoading={isSubmitting}
                loadingText={confirmAction === "delete" ? "Deleting user" : "Updating user"}
              >
                {confirmAction === "delete"
                  ? "Delete user"
                  : confirmUser.is_active
                    ? "Deactivate"
                    : "Reactivate"}
              </Button>
            </div>
          </div>
        </Dialog>
      ) : null}
    </>
  );
};
