import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// The dashboard is a static site (plan decision D14): `next build` writes plain
// files to out/, which Caddy serves on the same origin as the Django API, so the
// session and CSRF cookies work without CORS. During development the Next.js dev
// server forwards the Django paths instead (rewrites are not allowed in a static export).
// On Vercel (docs/CLOUD.md) the dashboard is built as a normal Next.js app that
// forwards them the same way, to the API on Modal (DT_DJANGO_URL), so the cookies
// stay first-party there too.
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

const forwardDjango = (url: string): NextConfig => ({
  ...shared,
  // Django's admin paths end in a slash. Next.js must neither redirect it away nor drop it when
  // rewriting (":path*" alone does), or Django adds it back and the browser loops.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return ["api", "admin", "static"].flatMap((prefix) => [
      { source: `/${prefix}`, destination: `${url}/${prefix}/` },
      { source: `/${prefix}/`, destination: `${url}/${prefix}/` },
      { source: `/${prefix}/:path+/`, destination: `${url}/${prefix}/:path+/` },
      { source: `/${prefix}/:path*`, destination: `${url}/${prefix}/:path*` },
    ]);
  },
});

// The headers Caddy sends on the laptop (deploy/Caddyfile); Vercel adds HSTS itself.
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  {
    key: "Content-Security-Policy",
    value:
      "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; " +
      "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; " +
      "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
  },
];

export default function config(phase: string): NextConfig {
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return forwardDjango(DJANGO_URL);
  }
  if (process.env.VERCEL) {
    if (!process.env.DT_DJANGO_URL) {
      throw new Error("Set DT_DJANGO_URL in the Vercel project to the API's Modal address (docs/CLOUD.md)");
    }
    return {
      ...forwardDjango(process.env.DT_DJANGO_URL.replace(/\/$/, "")),
      async headers() {
        return [{ source: "/:path*", headers: SECURITY_HEADERS }];
      },
    };
  }
  return { ...shared, output: "export" };
}
