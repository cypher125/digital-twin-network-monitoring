import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 px-4 text-center">
      <h1 className="text-xl font-semibold text-ink">Page not found</h1>
      <p className="text-sm text-ink-2">The page you asked for does not exist.</p>
      <Link href="/" className="text-sm text-accent-ink hover:underline">
        Go to the network overview
      </Link>
    </main>
  );
}
