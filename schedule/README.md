# Kindle calendar — GitHub Actions + KUAL

## Architecture

```text
Google Calendar (ICS)
        |
        v
GitHub Actions (daily)  -->  calendar.png on GitHub Pages
        |
        v
Kindle KUAL "Tablero"
  Hoy / Calendario / Clima / Mes
    Actualizar y mostrar  =  Wi-Fi on -> download that PNG -> Wi-Fi off -> FBInk
    Mostrar (cache)       =  show last PNG for that view
    Salir                 =  restore Home UI
```

**Why not Google Apps Script?** Apps Script cannot reasonably render a Paperwhite-sized PNG. GitHub Actions runs the same Python generator and publishes the image.

**Why this avoids airplane-mode issues:** the Kindle only turns Wi‑Fi on for one short download when you tap **Actualizar**, then turns it off. No background loop.

## 1) GitHub setup

1. Push this repo to GitHub.
2. **Settings → Secrets and variables → Actions → New repository secret**
   - `ICS_URL` = your Google Calendar **secret iCal URL**  
     (Calendar settings → Integrate calendar → Secret address in iCal format)
   - Optional: `PUBLISH_SLUG` = random string (e.g. `a8f3c1…`) for a harder-to-guess URL
   - Optional: `ICS_URLS` = more URLs separated by `|`
3. Optional **Variables**: `TIMEZONE` (default `America/Argentina/Buenos_Aires`), `CALENDAR_DAYS` (default `14`)
4. **Settings → Pages → Build and deployment → Source: GitHub Actions**
5. Actions → **Build Kindle calendar** → **Run workflow** (or wait for the daily cron)

Published files:

- `https://<user>.github.io/<repo>/calendar.png`
- optional: `https://<user>.github.io/<repo>/c/<PUBLISH_SLUG>/calendar.png`

Anyone with that URL can see your agenda image — use `PUBLISH_SLUG` if you care.

## 2) Kindle KUAL app

1. Copy `extensions/calendar` to the Kindle: `I:\extensions\calendar`
2. Copy `bin/config.example` → `bin/config` and set:

```sh
CALENDAR_URL="https://YOURUSER.github.io/kindle_apps/c/YOURSLUG/calendar.png"
WGET_INSECURE=1
FBINK="/mnt/us/libkh/bin/fbink"
```

3. KUAL → **Tablero**
   - **Hoy / Calendario / Clima / Mes** → **Actualizar y mostrar**
   - **Mostrar (cache)** — offline
   - **Salir** — back to Home

## 3) Local PC (optional)

Still works for testing:

```powershell
cd schedule
powershell -ExecutionPolicy Bypass -File .\sync.ps1
```

## What you get

Five KUAL PNGs share one download path:

- **Hoy** — date, weather line, today's events, tomorrow, tasks
- **Semanal** — week timetable + tasks + birthdays + weather
- **Calendario** — timetable from today forward (`schedule_days` columns)
- **Clima** — current conditions + 7-day forecast (Open-Meteo)
- **Mes** — month wall with event lines

The week view still includes:

- Hour grid (08–22 configurable)
- Event blocks with title, time, location
- Styles: normal / striped (quiz) / black (exam-importante)
- All-day chips under day headers
- Footer **SALIR** (power button or KUAL > Salir)

PDF still includes a multi-day agenda list for KOReader if you want it.


- Keep `ICS_URL` only in GitHub Secrets (never commit `config.toml` with the real URL).
- The published PNG is readable by URL; prefer `PUBLISH_SLUG`.
- If the ICS URL leaks, use Google’s **Reset** on the secret address.
