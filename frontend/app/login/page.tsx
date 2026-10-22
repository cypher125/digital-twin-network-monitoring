import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-xl font-semibold text-ink">Network Digital Twin</h1>
          <p className="mt-1 text-sm text-ink-2">Monitoring, prediction and simulation for the campus network</p>
        </div>
        <Suspense fallback={<div className="h-64 rounded-lg border border-line bg-surface" />}>
          <LoginForm />
        </Suspense>
        <p className="mt-6 text-center text-xs text-ink-2">
          Accounts are created by a Senior Administrator. Five wrong passwords lock sign-in for 15 minutes.
        </p>
      </div>
    </main>
  );
}
