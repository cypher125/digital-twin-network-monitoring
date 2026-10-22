"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { get, post, rememberCsrfToken } from "@/lib/api";
import type { User } from "@/lib/types";
import { Button } from "@/components/ui";

/**
 * Only return to pages of this dashboard (no open redirects). The address is resolved
 * with the same URL parser the router uses, so tricks such as "/\evil.example" or a tab
 * inside "//" cannot lead to another site. A path that only becomes "//evil.example"
 * once dot segments are resolved ("/..//evil.example", "/%2e%2e//evil.example") keeps
 * this origin here, but the router would read the result as another site's address,
 * so it is refused as well.
 */
function safeNext(value: string | null): string {
  if (!value) return "/";
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin || url.pathname.startsWith("//") || url.pathname.startsWith("/login")) return "/";
    return url.pathname + url.search + url.hash;
  } catch {
    return "/";
  }
}

export function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // the static dashboard gets its CSRF cookie before the first POST
    get<{ csrfToken: string }>("auth/csrf")
      .then((data) => rememberCsrfToken(data.csrfToken))
      .catch(() => setError("Cannot reach the server. Check that the system is running."));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await post<{ user: User; csrfToken: string }>("auth/login", { username, password });
      rememberCsrfToken(data.csrfToken); // Django rotates the token at login
      queryClient.clear();
      queryClient.setQueryData(["me"], data.user);
      router.replace(safeNext(search.get("next")));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Sign-in failed.");
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border border-line bg-surface p-5">
      <div>
        <label htmlFor="username" className="mb-1 block text-xs font-medium text-ink">
          Username
        </label>
        <input
          id="username"
          className="field"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          required
          autoFocus
        />
      </div>
      <div>
        <label htmlFor="password" className="mb-1 block text-xs font-medium text-ink">
          Password
        </label>
        <input
          id="password"
          type="password"
          className="field"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
      </div>
      {error ? (
        <p className="text-sm text-danger-ink" role="alert">
          {error}
        </p>
      ) : null}
      <Button type="submit" variant="primary" className="w-full" disabled={busy || !username || !password}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
