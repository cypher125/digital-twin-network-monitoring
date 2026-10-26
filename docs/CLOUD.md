# Running the Digital Twin in the cloud

The laptop deployment (`docs/INSTALL.md`) stays the reference. The cloud copy runs the same code so the dashboard can be opened from anywhere:

| Part | Where | What runs there |
|---|---|---|
| API and twin | [Modal](https://modal.com), app `digital-twin` | one always-on container: PostgreSQL, the network emulator, the Digital Twin Engine and the Django API on Waitress (`deploy/modal_app.py`) |
| Dashboard | [Vercel](https://vercel.com), project `digital-twin-network-monitoring` | the Next.js dashboard; it forwards `/api`, `/admin` and `/static` to Modal |

The browser only ever talks to the Vercel address. Vercel forwards the Django paths to Modal (`frontend/next.config.ts`), so the session and CSRF cookies are first-party and no CORS is needed, the same arrangement as Caddy on the laptop.

## Why one container

The database runs inside the twin's container, on its own disk. The alternative was Neon's free plan, which suspends a database after 5 idle minutes and allows 100 compute-hours a month. A twin that writes every minute never lets it suspend, so the allowance would run out after about 16 days. There is never more than one container (`max_containers=1`), because a second one would start a second database.

The database survives restarts through the Modal volume `digital-twin-var`. Every 10 minutes, and when the container stops, it is dumped to the volume (`var/backup/twin.dump`), together with the emulator's clock at that moment. A new container restores both, so the emulator resumes where the data ends and any gap after it is generated again. The trained models are on the same volume. If Modal stops the container without warning (preemption), at most the last 10 minutes of history are lost and regenerated.

A redeploy (`modal deploy`) can briefly run the old and the new container side by side. The new one restores the last dump, so the history can lose the few minutes of the overlap.

## The first start, and starting again after a pause

On the first start the volume is empty. The container generates 14 days of network history (about half an hour), starts the engine, then trains the models, as `deploy/setup.ps1` does on the laptop. The API answers throughout. The dashboard shows live data once the engine starts, and forecasts once the first model is trained.

After the twin has been switched off, the network clock is behind real time. On the next start the container fills the gap from the emulator in the same way (`backfill_history`, repeated until it has caught up), then the engine carries on. A gap under 15 minutes is skipped, like a short outage.

## Commands

From the project root, with the Modal CLI logged in:

```powershell
modal deploy deploy/modal_app.py        # switch on, or update after a code change
modal app stop digital-twin             # switch off (the data stays in the volume)
modal app logs digital-twin             # follow the logs
```

The dashboard is deployed from `frontend/` with the Vercel CLI (`vercel deploy --prod`). The Vercel project needs one environment variable: `DT_DJANGO_URL=https://osawayecyrus--digital-twin.modal.run`. Sign in only at https://digital-twin-network-monitoring.vercel.app. The per-deployment addresses that the CLI also prints are refused at sign-in, because Django trusts that one address only (`DJANGO_CSRF_TRUSTED_ORIGINS`).

## Cost

Modal bills a container for the CPU and memory it reserves or uses, whichever is higher. This one reserves 0.25 CPU cores and 1 GiB of memory, and may burst to 1 core and 3 GiB while it generates history or trains. At Modal's published prices ($0.0000131 per core-second and $0.00000222 per GiB-second), the reservation alone comes to about $0.47 a day, about $14 a month. Expect somewhat more if the twin uses more than it reserves; check Modal's usage page in the first days. Switch it off when it is not needed, and switch it on a day before a demo so the history and forecasts are ready.

## Accounts and secrets

The Modal secret `digital-twin` holds `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and the names and passwords of the two cloud accounts, one Senior and one Junior Administrator (`DT_SENIOR_USERNAME`, `DT_SENIOR_PASSWORD`, `DT_JUNIOR_USERNAME`, `DT_JUNIOR_PASSWORD`). The account names are kept out of this repository on purpose. Sign-in lockout counts per username (see below), so anyone who knew a name could keep that account locked. The values are in `var/cloud/secret.env`, and the accounts are listed in `var/cloud/accounts.txt`. Both files are git-ignored, so never commit or screenshot them. To change a value, edit `secret.env`, then recreate the secret and redeploy:

```powershell
modal secret create digital-twin --from-dotenv var/cloud/secret.env --force
modal deploy deploy/modal_app.py
```

The accounts are created on the first start only. A changed password in the secret does not change an existing account; change it on the dashboard instead.

## Differences from the laptop

- **HTTPS:** Modal and Vercel provide it, so there is no Caddy. Vercel sends the security headers that Caddy sends on the laptop (`frontend/next.config.ts`), and Django serves its own static files for the admin and API pages (`config/settings/cloud.py`).
- **Sign-in lockout:** after 5 failures, a username is locked for 15 minutes. On the laptop the lockout applies to a username and address together. In the cloud the client's address arrives in a header that anyone calling Modal directly could forge, so the lockout applies to the username alone.
- **Lab interface:** the emulator's lab interface (surges, failures) listens inside the container only. Demos that use it, such as `walkthrough.mjs --surge`, run against the laptop.
- **Audit trail:** it goes to Modal's logs (`modal app logs digital-twin`) and to a file on the container's disk, not to the volume, because a file held open on the volume would make every volume commit fail. Every entry records the address of Modal's proxy, not the client's. The client's address arrives only in headers that a direct caller could forge, so the API does not trust them.
