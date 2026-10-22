# Dashboard (Next.js)

The web dashboard of the Digital Twin-Based Network Monitoring and Optimization System. It is a static site: `npm run build` writes plain files to `out/`, and Caddy serves them next to the Django API on the same address.

## Layout

```
app/          pages (App Router)
  login/        sign in
  (app)/        everything behind the sign-in
    page.tsx      overview: summary, live network map, alerts, trend
    link/ device/ detail pages (?id=…)
    alerts/       predictive alerts and history
    simulation/   simulation console;  result/  one run's result (?id=…)
    trends/       long-term trends and capacity planning
    system/       engine, models, database, users, import, password
components/   shared UI: map, charts, tables, badges, dialogs
lib/          API client, data hooks, types, formatting, theme
public/       static files
scripts/      screenshots.mjs (smoke test and screenshots)
```

## Development

Start the Django API on port 8000 first (see `docs/PROJECT_PLAN.md` §12), then:

```
npm install
npm run dev          # http://localhost:3000; /api, /admin and /static are forwarded to Django
```

## Production build

```
npm run build        # writes out/
```

## Smoke test and screenshots

The script uses the Microsoft Edge that comes with Windows, so it downloads no browser. It signs in, opens every page in the light and dark themes and at phone width, and saves the screenshots to `var/screenshots/`. It fails on any console error, page error or sideways scrolling.

```
set DT_USER=senior1
set DT_PASSWORD=...
node scripts/screenshots.mjs
```
