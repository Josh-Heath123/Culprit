import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, changePassword } from "@/lib/api";

const MIN_PASSWORD_LENGTH = 12;

/** Self-service password change (Phase 16), opened from AppHeader.tsx's account
 * menu. Invalidates nothing else on success — tokens are short-lived
 * and there's no server-side session store to revoke (see
 * api/app/auth/router.py's own comment), so the current session just
 * keeps working with the old token until it naturally expires. */
export function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => changePassword(currentPassword, newPassword),
    onSuccess: onClose,
    onError: (err) =>
      setError(
        err instanceof ApiError && err.status === 401
          ? "That isn't your current password."
          : err instanceof Error
            ? err.message
            : "Couldn't change password.",
      ),
  });

  const valid = newPassword.length >= MIN_PASSWORD_LENGTH;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent aria-describedby={undefined} className="p-5 sm:p-6">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (currentPassword && valid) mutation.mutate();
          }}
          className="flex flex-col gap-4"
        >
          <DialogTitle className="text-base">Change your password</DialogTitle>

          <div className="flex flex-col gap-1">
            <label htmlFor="current-password" className="text-xs font-medium text-fg-muted">
              Current password
            </label>
            <Input
              id="current-password"
              type="password"
              autoFocus
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="new-password" className="text-xs font-medium text-fg-muted">
              New password
            </label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
            />
          </div>

          {error ? (
            <p role="alert" className="text-xs text-fail">
              {error}
            </p>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={!currentPassword || !valid || mutation.isPending}>
              {mutation.isPending ? "Changing…" : "Change password"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
