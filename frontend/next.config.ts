import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// The dashboard is a static site (plan decision D14): `next build` writes plain
// files to out/, which Caddy serves on the same origin as the Django API, so the
// session and CSRF cookies work without CORS. During development the Next.js dev
// server forwards the Django paths instead (rewrites are not allowed in a static export).
const DJANGO_URL = process.env.DT_DJANGO_URL ?? "http://127.0.0.1:8000";

// Cache Components (partial prerendering) is not available in a static export, and
// the dashboard fetches all of its data in the browser, so it stays off.
const shared: NextConfig = {
  poweredByHeader: false,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default function config(phase: string): NextConfig {
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return {
      ...shared,
      async rewrites() {
        return ["api", "admin", "static"].map((prefix) => ({
          source: `/${prefix}/:path*`,
          destination: `${DJANGO_URL}/${prefix}/:path*`,
        }));
      },
    };
  }
  return { ...shared, output: "export" };
}
