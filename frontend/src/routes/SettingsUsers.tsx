import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useUsers } from "@/hooks/useUsers";
import { createUser, patchUser, resetUserPassword } from "@/lib/api";
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
      <DialogContent className="p-5">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) mutation.mutate();
          }}
          className="flex flex-col gap-3"
        >
          <div>
            <p className="text-sm font-semibold text-foreground">Reset password for {username}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Hand the new password to {username} out of band — there's no reset-by-email.
            </p>
          </div>
          <Input
            type="password"
            autoFocus
            placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
          />
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
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
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (username && passwordValid) mutation.mutate();
      }}
      className="flex flex-col gap-3 rounded-md border border-border p-4"
    >
      <p className="text-sm font-semibold text-foreground">Create a user</p>

      <div className="flex flex-col gap-1">
        <label htmlFor="new-user-username" className="text-xs font-medium text-muted-foreground">
          Username
        </label>
        <Input
          id="new-user-username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="new-user-password" className="text-xs font-medium text-muted-foreground">
          Password — hand it over out of band, there's no invite-by-email
        </label>
        <Input
          id="new-user-password"
          type="password"
          placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {password && !passwordValid ? (
          <p className="text-xs text-destructive">
            at least {MIN_PASSWORD_LENGTH} characters, and not the same as the username
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="new-user-role" className="text-xs font-medium text-muted-foreground">
          Role
        </label>
        <select
          id="new-user-role"
          value={role}
          onChange={(event) => setRole(event.target.value as UserRole)}
          className="h-8 rounded-md border border-border bg-transparent px-2 text-sm text-foreground"
        >
          <option value="member">Member</option>
          <option value="admin">Admin</option>
        </select>
      </div>

      {mutation.isError ? (
        <p className="font-mono text-xs text-destructive">
          {mutation.error instanceof Error ? mutation.error.message : "Couldn't create user."}
        </p>
      ) : null}

      <Button
        type="submit"
        size="sm"
        className="self-start"
        disabled={!username || !passwordValid || mutation.isPending}
      >
        {mutation.isPending ? "Creating…" : "Create user"}
      </Button>
    </form>
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

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm text-foreground">{user.username}</span>
          <Badge variant={user.role === "admin" ? "primary" : "outline"}>{user.role}</Badge>
          {user.disabled ? <Badge variant="outline">disabled</Badge> : null}
          {isSelf ? <Badge variant="outline">you</Badge> : null}
        </div>
        <div className="flex items-center gap-2">
          {/* No role or disable control on your own row: demoting or
              disabling yourself took the only admin's access away with no
              way back short of `just create-user` on the host (Phase 31.2
              truth pass). The API does not refuse it — docs/LIMITS.md. */}
          {isSelf ? null : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => toggleRole.mutate()}
              disabled={toggleRole.isPending}
            >
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

      {toggleRole.error ?? toggleDisabled.error ? (
        <p className="text-xs text-destructive">
          {(toggleRole.error ?? toggleDisabled.error)?.message || "That change was not saved."}
        </p>
      ) : null}

      <p className="text-xs text-muted-foreground">
        {user.last_login_at
          ? `last login ${new Date(user.last_login_at).toLocaleString()}`
          : "never logged in"}
      </p>

      {resettingPassword ? (
        <ResetPasswordDialog
          userId={user.id}
          username={user.username}
          onClose={() => setResettingPassword(false)}
        />
      ) : null}
    </div>
  );
}

export function SettingsUsers() {
  const { users, isPending, isError } = useUsers();
  const currentUser = useCurrentUser();

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <Link to="/" className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-primary" aria-hidden />
          <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
        </Link>
        <span className="text-xs text-muted-foreground">/ Users</span>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 overflow-y-auto p-6">
        <AddUserForm />

        {isPending ? <p className="text-xs text-muted-foreground">Loading users…</p> : null}
        {isError ? (
          <p className="text-xs text-destructive">
            Couldn't load users — this page is admin-only, and your account may not have that role.
          </p>
        ) : null}

        <div className="flex flex-col gap-3">
          {users.map((user) => (
            <UserRow key={user.id} user={user} isSelf={user.id === currentUser.data?.id} />
          ))}
        </div>
      </main>
    </div>
  );
}
