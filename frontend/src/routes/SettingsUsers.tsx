import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Page } from "@/components/layout/Page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ErrorPanel, LoadingRows } from "@/components/ui/states";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useUsers } from "@/hooks/useUsers";
import { createUser, patchUser, resetUserPassword } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import type { UserOut, UserRole } from "@/lib/types";

const MIN_PASSWORD_LENGTH = 12;

function ResetPasswordDialog({
  userId,
  username,
  onClose,
}: {
  userId: string;
  username: string;
  onClose: () => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => resetUserPassword(userId, newPassword),
    onSuccess: onClose,
    onError: (err) => setError(err instanceof Error ? err.message : "Couldn't reset password."),
  });

  const valid = newPassword.length >= MIN_PASSWORD_LENGTH && newPassword !== username;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent aria-describedby={undefined} className="p-5 sm:p-6">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) mutation.mutate();
          }}
          className="flex flex-col gap-4"
        >
          <div>
            <DialogTitle className="text-base">Reset password for {username}</DialogTitle>
            <p className="mt-1 text-xs text-fg-muted">
              Hand the new password to {username} out of band — there's no reset-by-email.
            </p>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="reset-password" className="text-xs font-medium text-fg-muted">
              New password
            </label>
            <Input
              id="reset-password"
              type="password"
              autoFocus
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
            <Button type="submit" size="sm" disabled={!valid || mutation.isPending}>
              {mutation.isPending ? "Resetting…" : "Reset password"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AddUserForm() {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("member");

  const mutation = useMutation({
    mutationFn: () => createUser(username, password, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setUsername("");
      setPassword("");
      setRole("member");
    },
  });

  const passwordValid = password.length >= MIN_PASSWORD_LENGTH && password !== username;

  return (
    <Card aria-labelledby="add-user-heading">
      <CardHeader id="add-user-heading" title="Create a user" />
      <CardBody>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (username && passwordValid) mutation.mutate();
          }}
          className="flex flex-col gap-4"
          data-testid="add-user-form"
        >
          <div className="grid gap-4 md:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="new-user-username" className="text-xs font-medium text-fg-muted">
                Username
              </label>
              <Input
                id="new-user-username"
                autoComplete="off"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="new-user-password" className="text-xs font-medium text-fg-muted">
                Password
              </label>
              <Input
                id="new-user-password"
                type="password"
                autoComplete="new-password"
                placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="new-user-role" className="text-xs font-medium text-fg-muted">
                Role
              </label>
              <Select id="new-user-role" value={role} onChange={(event) => setRole(event.target.value as UserRole)}>
                <option value="member">Member</option>
                <option value="admin">Admin</option>
              </Select>
            </div>
          </div>

          <p className="text-xs text-fg-subtle">
            Hand the password over out of band — there's no invite-by-email.
          </p>
          {password && !passwordValid ? (
            <p className="text-xs text-fail">
              The password needs at least {MIN_PASSWORD_LENGTH} characters, and not the username.
            </p>
          ) : null}
          {mutation.isError ? (
            <p role="alert" className="text-xs text-fail">
              {mutation.error instanceof Error ? mutation.error.message : "Couldn't create user."}
            </p>
          ) : null}

          <Button type="submit" className="self-start" disabled={!username || !passwordValid || mutation.isPending}>
            {mutation.isPending ? "Creating…" : "Create user"}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function UserRow({ user, isSelf }: { user: UserOut; isSelf: boolean }) {
  const queryClient = useQueryClient();
  const [resettingPassword, setResettingPassword] = useState(false);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["users"] });
  }

  const toggleDisabled = useMutation({
    mutationFn: () => patchUser(user.id, { disabled: !user.disabled }),
    onSuccess: invalidate,
  });

  const toggleRole = useMutation({
    mutationFn: () => patchUser(user.id, { role: user.role === "admin" ? "member" : "admin" }),
    onSuccess: invalidate,
  });

  const failure = toggleRole.error ?? toggleDisabled.error;

  return (
    <li className="flex flex-col gap-3 px-4 py-4 sm:px-5" data-testid="user-row">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm wrap-anywhere text-fg">{user.username}</span>
            <Badge variant={user.role === "admin" ? "primary" : "outline"}>{user.role}</Badge>
            {user.disabled ? <Badge variant="refused">disabled</Badge> : null}
            {isSelf ? <Badge variant="outline">you</Badge> : null}
          </div>
          <span className="text-xs text-fg-subtle">
            {user.last_login_at ? `Last signed in ${formatDateTime(user.last_login_at)}` : "Never signed in"}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* No role or disable control on your own row: demoting or
              disabling yourself could take the only admin's access away
              (Phase 31.2 truth pass); the API also refuses to remove the
              last enabled admin (docs/LIMITS.md). */}
          {isSelf ? null : (
            <Button variant="outline" size="sm" onClick={() => toggleRole.mutate()} disabled={toggleRole.isPending}>
              {user.role === "admin" ? "Make member" : "Make admin"}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => setResettingPassword(true)}>
            Reset password
          </Button>
          {isSelf ? null : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => toggleDisabled.mutate()}
              disabled={toggleDisabled.isPending}
            >
              {user.disabled ? "Enable" : "Disable"}
            </Button>
          )}
        </div>
      </div>

      {failure ? (
        <p role="alert" className="text-xs text-fail">
          {failure.message || "That change was not saved."}
        </p>
      ) : null}

      {resettingPassword ? (
        <ResetPasswordDialog userId={user.id} username={user.username} onClose={() => setResettingPassword(false)} />
      ) : null}
    </li>
  );
}

export function SettingsUsers() {
  const { users, isPending, isError, error, refetch } = useUsers();
  const currentUser = useCurrentUser();

  return (
    <Page
      eyebrow="Settings"
      title="Users"
      description="Who can sign in to this control plane, and as what. Admins manage the system model and users; members read."
    >
      <AddUserForm />

      {isPending ? <LoadingRows label="Loading users" rows={2} /> : null}
      {isError ? (
        <ErrorPanel
          title="Couldn't load users."
          message={error instanceof Error ? error.message : "The request failed."}
          onRetry={() => refetch()}
        />
      ) : null}

      {users.length > 0 ? (
        <Card aria-labelledby="users-heading">
          <CardHeader id="users-heading" title="Accounts" trailing={<span className="text-2xs text-fg-subtle">{users.length}</span>} />
          <ul className="divide-y divide-line">
            {users.map((user) => (
              <UserRow key={user.id} user={user} isSelf={user.id === currentUser.data?.id} />
            ))}
          </ul>
        </Card>
      ) : null}
    </Page>
  );
}
