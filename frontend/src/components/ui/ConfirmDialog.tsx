import { Button } from "./Button";
import { Dialog } from "./Dialog";

type ConfirmDialogProps = {
  title: string;
  description: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
  destructive?: boolean;
  isLoading?: boolean;
};

export const ConfirmDialog = ({ title, description, confirmLabel, onCancel, onConfirm, destructive = false, isLoading = false }: ConfirmDialogProps) => (
  <Dialog title={title} eyebrow="Please confirm" onClose={onCancel} size="md">
    <p className="text-body text-text-muted">{description}</p>
    <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
      <Button type="button" variant="secondary" disabled={isLoading} onClick={onCancel}>Cancel</Button>
      <Button type="button" variant={destructive ? "destructive" : "primary"} isLoading={isLoading} loadingText="Working…" onClick={onConfirm}>{confirmLabel}</Button>
    </div>
  </Dialog>
);
