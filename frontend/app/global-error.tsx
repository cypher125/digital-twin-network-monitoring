"use client";

// Last-resort error screen (Next.js global-error.tsx), shown when the root layout itself
// fails. It replaces the whole document, so it brings its own <html> and <body>, the
// global styles and the saved light/dark choice (the root layout's theme script is gone).

import "./globals.css";
import { Button, ErrorNote } from "@/components/ui";
import { useThemeChoice } from "@/lib/theme";

export default function GlobalError({ error, retry }: { error: unknown; retry: () => void }) {
  const theme = useThemeChoice();
  // a thrown value is not always an Error
  const detail = error instanceof Error ? error.message : String(error ?? "");
  return (
    <html lang="en-GB" data-theme={theme === "system" ? undefined : theme}>
      <body className="min-h-screen">
        <title>Something went wrong · Network Digital Twin</title>
        <main className="mx-auto max-w-xl space-y-3 px-4 py-16">
          <h1 className="text-xl font-semibold text-ink">Network Digital Twin</h1>
          <ErrorNote
            title="The dashboard could not be shown"
            error="Something went wrong while loading the dashboard. Try again; if it keeps happening, reload the page."
          />
          {detail ? (
            <details className="text-xs text-ink-2">
              <summary className="cursor-pointer">Technical detail</summary>
              <p className="mt-1 font-mono wrap-break-word">{detail}</p>
            </details>
          ) : null}
          <Button onClick={() => retry()}>Try again</Button>
        </main>
      </body>
    </html>
  );
}
