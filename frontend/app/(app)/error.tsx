"use client";

// Error boundary for the dashboard pages (Next.js error.tsx). It sits inside the
// signed-in layout, so when one page fails while drawing (for example the network
// map), only that page is replaced by this note: the header and navigation still work.

import { Button, ErrorNote } from "@/components/ui";

export default function PageError({ error, retry }: { error: unknown; retry: () => void }) {
  // a thrown value is not always an Error
  const detail = error instanceof Error ? error.message : String(error ?? "");
  return (
    <div className="mx-auto max-w-xl space-y-3 py-10">
      <ErrorNote
        title="This page could not be shown"
        error="Something went wrong while drawing this page. The rest of the dashboard still works: try again, or choose another page above."
      />
      {detail ? (
        <details className="text-xs text-ink-2">
          <summary className="cursor-pointer">Technical detail</summary>
          <p className="mt-1 font-mono wrap-break-word">{detail}</p>
        </details>
      ) : null}
      <Button onClick={() => retry()}>Try again</Button>
    </div>
  );
}
