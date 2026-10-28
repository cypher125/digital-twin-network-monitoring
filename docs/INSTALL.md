# Installing and running the Digital Twin

This guide sets up the Digital Twin-Based Network Monitoring and Optimization System on a Windows 10 or 11 laptop. It takes about 30 minutes, plus about an hour of unattended work while the system generates its training history.

## What you need

- **Laptop:** Windows 10 or 11, 2 cores, 4 GB RAM, 5 GB of free disk space.
- **Internet:** needed during installation, and while the system runs, because the database is on Neon. For a venue without internet, see [Offline fallback](#offline-fallback-no-internet).
- **A Neon database:** see step 2.

Close other programs while installing. Browsers and editors use a lot of the memory on a 4 GB laptop.

## 1. Install the tools

Open **PowerShell** and run these four commands, one at a time:

```powershell
winget install astral-sh.uv
winget install OpenJS.NodeJS.LTS
winget install CaddyServer.Caddy
winget install Git.Git
```

Close PowerShell and open a new window, so the new commands are found. Check them:

```powershell
uv --version
node --version      # 20 or later
caddy version
```

Python does not need a separate install: `uv` installs Python 3.13 for the project.

## 2. Create the database (Neon)

1. Sign up at [neon.com](https://neon.com) and create a project:
   - Postgres version **17**;
   - region **AWS Europe (Frankfurt)**, the closest to Lagos.
2. Keep the default compute size (0.25–1 CU) and scale-to-zero.
3. Open **Connect** and choose the **direct** connection, not the pooled one. Copy the connection string; it starts with `postgresql://`.

Keep the connection string private: it contains the database password. Paste it only when the setup script asks for it. Never put it in a document, a chat or a commit.

## 3. Get the project

Copy the project folder to the laptop, for example to `C:\DigitalTwin`, and open PowerShell in it:

```powershell
cd C:\DigitalTwin
```

## 4. Run the setup script

```powershell
powershell -ExecutionPolicy Bypass -File deploy\setup.ps1 -AdminUser yourname
```

The script:

1. checks the tools from step 1;
2. installs the Python packages, at the exact versions the project was tested with;
3. asks for the Neon connection string (it is not shown while you type) and writes `backend\.env`;
4. creates the database tables, the two roles, and your **Senior Administrator** account (you choose the password: at least 10 characters);
5. loads the campus topology;
6. generates 14 days of network history and trains the forecasting models. **This takes about an hour.** Leave the laptop plugged in and awake;
7. builds the dashboard;
8. installs the local HTTPS certificate. Windows asks once whether to trust it: answer **Yes**.

If something fails, the script stops with a message. Fix the cause and run it again: finished steps are skipped.

## 5. Start and stop

```powershell
powershell -ExecutionPolicy Bypass -File deploy\start.ps1 -Speed 10
```

The system opens at **https://localhost** in the browser. Sign in with the account from step 4.

`-Speed` sets how fast the emulated campus network runs:
- `1` is real time;
- `10` makes an hour of campus traffic pass in 6 minutes, good for a demonstration.

Pick the highest speed at which **System → Cycles missed** stays at 0. On a 2-core laptop with a browser open, that is about 10.

To stop everything:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\stop.ps1
```

To see what is running:

```powershell
backend\.venv\Scripts\python.exe deploy\supervisor.py status
```

## 6. More accounts

Senior Administrators can sign in to the admin site at **https://localhost/admin** to add accounts:

1. Add a user.
2. Add the user to the group **Senior Administrator** (full access) or **Junior Administrator** (view only).
3. For a Senior Administrator, also tick **Staff status**. The dashboard does not need it, but without it they cannot sign in to this admin site to add accounts themselves.

In the cloud the admin site is at **https://digital-twin-network-monitoring.vercel.app/admin**.

You can also add an account from PowerShell:

```powershell
cd backend
$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
.venv\Scripts\python.exe manage.py setup_roles --create-user ada --role junior
```

## Offline fallback (no internet)

If the venue has no internet, the system can use a database on the laptop instead of Neon:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\setup.ps1 -LocalDatabase -AdminUser yourname
powershell -ExecutionPolicy Bypass -File deploy\start.ps1 -Speed 10 -LocalDatabase
```

The local database is separate from Neon. Set it up and test it **before** the day it is needed, because setup generates its own history (about an hour).

## When something goes wrong

| What you see | What to do |
|---|---|
| The browser warns about the certificate | Run `caddy trust` in an administrator PowerShell, then restart the browser |
| "Cannot reach the server" on the sign-in page | Start the system: `deploy\start.ps1` |
| Header shows **Engine stopped** | Open `var\log\engine.log`. The supervisor restarts the engine; if it keeps failing, the cause is in that log |
| Header shows **Data delayed** | The engine is behind. Lower `-Speed`, or close other programs |
| "Waiting for the database" on the System page | Check the internet connection. Neon may take a few seconds to wake up after a quiet period |
| **Cycles missed** keeps rising | The laptop cannot keep up at this speed. Restart with a lower `-Speed` |
| Sign-in says "Too many failed attempts" | Wait 15 minutes. Five wrong passwords lock that account and address for 15 minutes |

Logs are in `var\log`: `emulator.log`, `api.log`, `engine.log`, `caddy.log`, `audit.log` (who signed in and what they changed) and `supervisor.log`.
