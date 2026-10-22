"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, post, setReauthHandler } from "@/lib/api";
import type { User } from "@/lib/types";
import { Lock } from "./icons";
import { Button } from "./ui";

/**
 * Plan decision D8: after 30 minutes without activity, changes need the password
 * again. When the API refuses a change with code "reauthenticate", this dialog asks
 * for the password, confirms it (auth/password) and the change is sent again.
 */
export function ReauthDialog() {
  const queryClient = useQueryClient();
  const dialog = useRef<HTMLDialogElement>(null);
  const waiting = useRef<((ok: boolean) => void)[]>([]);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const finish = useCallback((ok: boolean) => {
    const resolvers = waiting.current;
    waiting.current = [];
    resolvers.forEach((resolve) => resolve(ok));
    setOpen(false);
    setPassword("");
    setError(null);
  }, []);

  useEffect(() => {
    setReauthHandler(
      () =>
        new Promise<boolean>((resolve) => {
          waiting.current.push(resolve);
          setOpen(true);
        }),
      // the session has ended (signed out in another tab, or expired): the sign-in page takes over
      () => finish(false),
    );
    return () => setReauthHandler(null);
  }, [finish]);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await post<{ user: User }>("auth/password", { current_password: password });
      queryClient.setQueryData(["me"], data.user);
      finish(true);
    } catch (problem) {
      // the session itself has ended: a password cannot restore it, and the sign-in page takes over
      if (problem instanceof ApiError && problem.code === "not_authenticated") {
        finish(false);
        return;
      }
      setError(problem instanceof Error ? problem.message : "Could not confirm the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      onCancel={(event) => {
        event.preventDefault();
        finish(false);
      }}
      className="m-auto w-[min(92vw,420px)] rounded-lg border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-black/40"
      aria-labelledby="reauth-title"
    >
      <form onSubmit={confirm} className="space-y-4 p-5">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 text-accent-ink">
            <Lock size={20} />
          </span>
          <div>
            <h2 id="reauth-title" className="text-base font-semibold">
              Confirm your password
            </h2>
            <p className="mt-1 text-sm text-ink-2">
              You have been away for a while. To make changes, please confirm your password. Viewing does not need it.
            </p>
          </div>
        </div>
        <div>
          <label htmlFor="reauth-password" className="mb-1 block text-xs font-medium">
            Password
          </label>
          <input
            id="reauth-password"
            type="password"
            autoComplete="current-password"
            className="field"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "reauth-error" : undefined}
            autoFocus
            required
          />
          {error ? (
            <p id="reauth-error" role="alert" className="mt-1 text-xs text-danger-ink">
              {error}
            </p>
          ) : null}
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={() => finish(false)} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !password}>
            {busy ? "Checking…" : "Confirm"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
