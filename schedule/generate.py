# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "icalendar>=6.0.0",
#   "recurring-ical-events>=3.0.0",
#   "reportlab>=4.0.0",
#   "Pillow>=10.0.0",
#   "tzdata>=2024.1",
# ]
# ///
"""
Generate Kindle calendar PDF + PNG on your PC.

PNG is for a KUAL/FBInk viewer (no on-device network).
PDF is optional for KOReader.
"""

from __future__ import annotations

import argparse
import json
import ssl
import tomllib
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import portrait
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
import recurring_ical_events


WEEKDAYS_ES = [
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
]
WEEKDAYS_ES_SHORT = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]
MONTHS_ES = [
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
WD_SHORT = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]


@dataclass
class Config:
    ics_urls: list[str]
    ics_files: list[Path]
    timezone: str
    days: int
    schedule_days: int
    start_hour: int
    end_hour: int
    output: Path
    png_output: Path
    png_width: int
    png_height: int
    png_rotate: int
    page_width_in: float
    page_height_in: float
    insecure_ssl: bool
    extras_url: str = ""
    # On a 24h grid, empty hours outside core_start_hour..core_end_hour get a
    # short row so the daytime rows can breathe.
    compress_night: bool = True
    core_start_hour: int = 7
    core_end_hour: int = 23
    weather_lat: float = -31.4241
    weather_lon: float = -64.4978
    weather_place: str = "Carlos Paz, Cordoba"


FOOTER_H = 50


def canvas_size(cfg: Config) -> tuple[int, int]:
    """Layout size before png_rotate. Landscape boards draw at 1024x758."""
    if cfg.png_rotate in (90, 270):
        return cfg.png_height, cfg.png_width
    return cfg.png_width, cfg.png_height


def sibling_png(cfg: Config, name: str) -> Path:
    return cfg.png_output.with_name(name)


def save_kindle_png(cfg: Config, img: Image.Image, dest: Path | None = None) -> Path:
    dest = dest or cfg.png_output
    dest.parent.mkdir(parents=True, exist_ok=True)
    if cfg.png_rotate:
        img = img.rotate(cfg.png_rotate, expand=True)
    img.save(dest, format="PNG", optimize=True)
    return dest


def draw_exit_footer(
    d: ImageDraw.ImageDraw,
    w: int,
    h: int,
    generated: datetime | None = None,
    failed_feeds: int = 0,
    extra: str = "",
) -> None:
    """Black SALIR bar shared by every board."""
    footer_h = FOOTER_H
    f_foot = pil_fonts(18, bold=True)
    f_hint = pil_fonts(15, bold=False)
    d.rectangle([0, h - footer_h, w, h], fill=0)
    d.text((w // 2, h - footer_h + 6), "SALIR", font=f_foot, fill=255, anchor="ma")
    hint = "Toca la pantalla o boton power"
    if generated is not None:
        hint = f"{generated.strftime('%d/%m %H:%M')}  -  {hint}"
    if extra:
        hint = f"{hint}  -  {extra}"
    if failed_feeds:
        hint = f"{hint}  -  SIN DATOS: {failed_feeds} calendario(s)"
    d.text(
        (w // 2, h - footer_h + 27),
        _fit_text(hint, f_hint, w - 40),
        font=f_hint,
        fill=255,
        anchor="ma",
    )


@dataclass
class Ev:
    start: datetime | date
    end: datetime | date
    summary: str
    all_day: bool
    location: str = ""
    description: str = ""
    style: str = "normal"  # normal | striped | black


def load_config(path: Path) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    urls = list(data.get("ics_urls") or [])
    files_raw = list(data.get("ics_files") or [])
    files: list[Path] = []
    for p in files_raw:
        fp = Path(p).expanduser()
        if not fp.is_absolute():
            fp = (path.parent / fp).resolve()
        files.append(fp)
    if not urls and not files:
        raise SystemExit(f"No ics_urls or ics_files in {path}")
    for u in urls:
        if "REPLACE" in u:
            raise SystemExit(f"Edit {path}: replace REPLACE in ics_urls")
    screen = data.get("screen") or {}
    out = Path(data.get("output", "output/calendar.pdf")).expanduser()
    if not out.is_absolute():
        out = path.parent / out
    png = Path(data.get("png_output", "output/calendar.png")).expanduser()
    if not png.is_absolute():
        png = path.parent / png
    return Config(
        ics_urls=urls,
        ics_files=files,
        timezone=data.get("timezone", "America/Argentina/Buenos_Aires"),
        days=int(data.get("days", 14)),
        schedule_days=int(data.get("schedule_days", 5)),
        start_hour=int(data.get("start_hour", 8)),
        end_hour=int(data.get("end_hour", 22)),
        output=out,
        png_output=png,
        png_width=int(screen.get("png_width", 758)),
        png_height=int(screen.get("png_height", 1024)),
        png_rotate=int(screen.get("png_rotate", 0)) % 360,
        page_width_in=float(screen.get("width_in", 3.58)),
        page_height_in=float(screen.get("height_in", 4.82)),
        insecure_ssl=bool(data.get("insecure_ssl", False)),
        extras_url=str(data.get("extras_url", "")).strip(),
        compress_night=bool(data.get("compress_night", True)),
        core_start_hour=int(data.get("core_start_hour", 7)),
        core_end_hour=int(data.get("core_end_hour", 23)),
        weather_lat=float(data.get("weather_lat", -31.4241)),
        weather_lon=float(data.get("weather_lon", -64.4978)),
        weather_place=str(data.get("weather_place", "Carlos Paz, Cordoba")).strip() or "Carlos Paz, Cordoba",
    )


@dataclass
class Task:
    title: str
    due: date | None
    notes: str = ""


def fetch_extras(cfg: Config) -> tuple[list[Task], list[Ev]]:
    """Read the Apps Script feed: Google Tasks plus Contacts birthdays.

    Never fatal: the calendar must still render if the feed is down.
    """
    if not cfg.extras_url:
        return [], []
    try:
        raw = fetch_ics(cfg.extras_url, cfg.insecure_ssl)
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - report and carry on
        print(f"WARNING: extras feed failed: {exc}")
        return [], []

    for key in ("tasksError", "birthdaysError", "error"):
        if data.get(key):
            print(f"WARNING: extras feed {key}: {data[key]}")

    tasks: list[Task] = []
    for t in data.get("tasks") or []:
        title = str(t.get("title", "")).strip()
        if not title:
            continue
        # Only dated tasks are shown, so drop anything the feed sends undated.
        if not t.get("due"):
            continue
        try:
            due = date.fromisoformat(str(t["due"])[:10])
        except ValueError:
            continue
        tasks.append(Task(title=sanitize_text(title), due=due, notes=sanitize_text(str(t.get("notes", "")))))

    birthdays: list[Ev] = []
    for b in data.get("birthdays") or []:
        name = str(b.get("name", "")).strip()
        if not name or not b.get("date"):
            continue
        try:
            day = date.fromisoformat(str(b["date"])[:10])
        except ValueError:
            continue
        birthdays.append(
            Ev(
                start=day,
                end=day + timedelta(days=1),
                summary=f"Cumple {sanitize_text(name)}",
                all_day=True,
            )
        )

    print(f"Extras: {len(tasks)} task(s), {len(birthdays)} birthday(s).")
    return tasks, birthdays


def fetch_ics(url: str, insecure: bool) -> bytes:
    ctx = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "kindle-apps-schedule/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        return resp.read()


def merge_calendars(blobs: list[bytes]) -> Calendar:
    merged = Calendar()
    merged.add("prodid", "-//kindle_apps schedule//")
    merged.add("version", "2.0")
    for blob in blobs:
        cal = Calendar.from_ical(blob)
        for component in cal.walk():
            if component.name == "VEVENT":
                merged.add_component(component)
    return merged


def to_local(dt: datetime | date, tz: ZoneInfo) -> datetime | date:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc).astimezone(tz)
        return dt.astimezone(tz)
    return dt


def pick_style(summary: str, description: str) -> str:
    blob = f"{summary} {description}".lower()
    if any(k in blob for k in ("examen", "exam", "importante", "important", "final")):
        return "black"
    if any(k in blob for k in ("quiz", "parcial", "entrega", "deadline")):
        return "striped"
    return "normal"


def collect_events(cal: Calendar, start: date, end: date, tz: ZoneInfo) -> list[Ev]:
    query_start = datetime.combine(start, time.min, tzinfo=tz)
    query_end = datetime.combine(end, time.max, tzinfo=tz)
    raw = recurring_ical_events.of(cal).between(query_start, query_end)
    out: list[Ev] = []
    for component in raw:
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue
        ds = component.get("DTSTART")
        de = component.get("DTEND")
        if ds is None:
            continue
        start_v = to_local(ds.dt, tz)
        if de is not None:
            end_v = to_local(de.dt, tz)
        else:
            end_v = start_v
        all_day = not isinstance(start_v, datetime)
        summary = sanitize_text(str(component.get("SUMMARY", "(sin titulo)")).strip() or "(sin titulo)")
        location = sanitize_text(str(component.get("LOCATION", "") or "").strip())
        description = sanitize_text(str(component.get("DESCRIPTION", "") or "").strip())
        # Keep description short for blocks
        if description:
            description = description.replace("\n", " ")
            if len(description) > 80:
                description = description[:77] + "..."
        style = pick_style(summary, description)
        out.append(
            Ev(
                start=start_v,
                end=end_v,
                summary=summary,
                all_day=all_day,
                location=location,
                description=description,
                style=style,
            )
        )

    def sort_key(e: Ev):
        if isinstance(e.start, datetime):
            return (e.start.date(), 0, e.start.timetz())
        return (e.start, 1, time.min)

    out.sort(key=sort_key)
    return out


def local_today(tz: ZoneInfo, now: datetime | None = None) -> date:
    """Calendar 'today' in the configured zone, not the build machine's UTC date.

    GitHub Actions is UTC. After 21:00 in Argentina that is already the next day,
    so date.today() on the runner would shift the first column to martes.
    """
    return (now or datetime.now(tz)).astimezone(tz).date()


def schedule_window(start: date, n: int) -> list[date]:
    """First column is today; the rest are the next days (weekends included)."""
    n_days = max(1, min(int(n), 7))
    return [start + timedelta(days=i) for i in range(n_days)]


def events_on_day(events: list[Ev], day: date) -> list[Ev]:
    day_list: list[Ev] = []
    for e in events:
        if e.all_day:
            s = e.start if isinstance(e.start, date) else e.start.date()
            en = e.end if isinstance(e.end, date) else e.end.date()
            if s <= day < en or (s == day and s == en):
                day_list.append(e)
        else:
            assert isinstance(e.start, datetime)
            if e.start.date() == day:
                day_list.append(e)
    return day_list


def sanitize_text(text: str) -> str:
    """Strip emoji / dingbats and normalize punctuation for e-ink fonts."""
    out: list[str] = []
    for ch in text:
        o = ord(ch)
        # Variation selectors, ZWJ, emoji blocks, misc symbols often missing in fonts
        if o in (0x200D, 0xFE0E, 0xFE0F, 0x20E3):
            continue
        if 0x1F000 <= o <= 0x1FAFF:
            continue
        if 0x2600 <= o <= 0x27BF:
            continue
        if 0x2300 <= o <= 0x23FF:
            continue
        if 0x2B00 <= o <= 0x2BFF:
            continue
        if 0xFE00 <= o <= 0xFE0F:
            continue
        if ch in "Â·â€¢â—âˆ™":
            out.append("-")
            continue
        if ch in "â€”â€“â€•":
            out.append("-")
            continue
        if ch == "â€¦":
            out.append("...")
            continue
        if ch in "â€œâ€â€ž":
            out.append('"')
            continue
        if ch in "â€˜â€™":
            out.append("'")
            continue
        out.append(ch)
    cleaned = "".join(out)
    # collapse leftover spaces from removed emoji
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")
    return cleaned.strip()


def fmt_time(e: Ev) -> str:
    if e.all_day:
        return "todo el dia"
    assert isinstance(e.start, datetime)
    s = e.start.strftime("%H:%M")
    if isinstance(e.end, datetime):
        return f"{s}-{e.end.strftime('%H:%M')}"
    return s


def system_font_paths() -> tuple[Path | None, Path | None]:
    """Find regular/bold TTF on Windows or Linux (GitHub Actions)."""
    regular_candidates = [
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    ]
    bold_candidates = [
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\calibrib.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ]
    regular = next((p for p in regular_candidates if p.is_file()), None)
    bold = next((p for p in bold_candidates if p.is_file()), None)
    return regular, bold


def try_register_fonts() -> str:
    regular, bold = system_font_paths()
    if regular:
        pdfmetrics.registerFont(TTFont("Body", str(regular)))
        if bold:
            pdfmetrics.registerFont(TTFont("Body-Bold", str(bold)))
        return "Body"
    return "Helvetica"


def pil_fonts(size: int, bold: bool = False) -> ImageFont.ImageFont:
    regular, bold_path = system_font_paths()
    path = bold_path if bold and bold_path else regular
    if path:
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _hatch_rect(draw: ImageDraw.ImageDraw, box: list[float], step: int = 7) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=0, width=1, fill=230)
    y = y0
    while y < y1:
        # diagonal-ish stripes via short segments
        x = x0
        while x < x1:
            x2 = min(x + step, x1)
            y2 = min(y + step, y1)
            draw.line([x, y2, x2, y], fill=160, width=1)
            x += step
        y += step
    draw.rectangle(box, outline=0, width=1)


def _assign_lanes(day_events: list[Ev]) -> dict[int, tuple[int, int]]:
    """Map event index -> (lane, lane_count) for overlapping timed events.

    lane_count is per overlap group, not per day: a single triple-booked hour
    must not squeeze the rest of the day's events into a third of the column.
    """
    timed = [(i, e) for i, e in enumerate(day_events) if not e.all_day and isinstance(e.start, datetime)]
    timed.sort(key=lambda t: (t[1].start, t[1].end))

    out: dict[int, tuple[int, int]] = {}
    group: list[int] = []  # indices in the current overlap group
    lane_end: list[datetime] = []
    group_end: datetime | None = None

    for i, e in timed:
        assert isinstance(e.start, datetime)
        e_end = e.end if isinstance(e.end, datetime) else e.start + timedelta(hours=1)
        if group_end is not None and e.start >= group_end:
            for idx in group:
                out[idx] = (out[idx][0], len(lane_end))
            group, lane_end, group_end = [], [], None

        lane = 0
        while lane < len(lane_end) and e.start < lane_end[lane]:
            lane += 1
        if lane == len(lane_end):
            lane_end.append(e_end)
        else:
            lane_end[lane] = e_end

        out[i] = (lane, 1)
        group.append(i)
        group_end = e_end if group_end is None else max(group_end, e_end)

    for idx in group:
        out[idx] = (out[idx][0], len(lane_end))
    return out


def _fit_text(text: str, font: ImageFont.ImageFont, max_w: float) -> str:
    """Truncate to the real rendered width, so text never runs past its box."""
    if font.getlength(text) <= max_w:
        return text
    ell = ".."
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.getlength(text[:mid] + ell) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ell) if lo else ell


TASK_ROW_H = 17
TASK_HEAD_H = 16


def _draw_task_sidebar(
    d: ImageDraw.ImageDraw,
    tasks: list[Task],
    box: tuple[float, float, float, float],
    today: date,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    """Pending Google Tasks grouped by due state.

    Overdue and today's tasks sit under one heading each, so the sidebar does
    not repeat "atrasada" on every row; only upcoming rows need a date.
    """
    x0, y0, x1, y1 = box
    d.rectangle([x0, y0, x1, y1], outline=0, width=1, fill=250)
    d.rectangle([x0, y0, x1, y0 + 28], fill=0)
    d.text(((x0 + x1) / 2, y0 + 5), "TAREAS", font=fonts["head"], fill=255, anchor="ma")

    dated = [t for t in tasks if t.due is not None]
    groups = [
        ("ATRASADAS", [t for t in dated if t.due and t.due < today], False),
        ("HOY", [t for t in dated if t.due == today], False),
        ("PROXIMAS", [t for t in dated if t.due and t.due > today], True),
    ]

    date_x = x0 + 8
    title_x = x0 + 44
    y = y0 + 33
    # Leave a row free for the "+N mas" counter when the list is longer.
    y_stop = y1 - 24
    shown = 0

    for label, items, dated_rows in groups:
        if not items or y + TASK_HEAD_H + TASK_ROW_H > y_stop:
            continue
        d.rectangle([x0 + 1, y, x1 - 1, y + TASK_HEAD_H - 2], fill=228)
        d.text((date_x, y + 1), label, font=fonts["meta"], fill=0)
        y += TASK_HEAD_H

        for t in items:
            if y + TASK_ROW_H > y_stop:
                break
            if dated_rows and t.due:
                d.text((date_x, y + 1), t.due.strftime("%d/%m"), font=fonts["meta"], fill=90)
                d.text((title_x, y), _fit_text(t.title, fonts["task"], x1 - title_x - 8), font=fonts["task"], fill=0)
            else:
                d.text((date_x, y), _fit_text(t.title, fonts["task"], x1 - date_x - 8), font=fonts["task"], fill=0)
            y += TASK_ROW_H
            shown += 1

    if not dated:
        d.text(((x0 + x1) / 2, y), "sin pendientes", font=fonts["meta"], fill=120, anchor="ma")
    elif shown < len(dated):
        d.text(
            ((x0 + x1) / 2, y + 2),
            f"+{len(dated) - shown} mas",
            font=fonts["meta"],
            fill=110,
            anchor="ma",
        )


BDAY_ROW_H = 17


def _birthday_box_h(rows: int) -> float:
    """Height a birthday box needs for `rows` entries, header included."""
    return 28 + 7 + rows * BDAY_ROW_H + 3


def _draw_birthday_box(
    d: ImageDraw.ImageDraw,
    birthdays: list[Ev],
    box: tuple[float, float, float, float],
    fonts: dict[str, ImageFont.ImageFont],
    hidden: int = 0,
) -> None:
    """Upcoming birthdays as one date + name line each."""
    x0, y0, x1, y1 = box
    d.rectangle([x0, y0, x1, y1], outline=0, width=1, fill=250)
    d.rectangle([x0, y0, x1, y0 + 28], fill=0)
    d.text(((x0 + x1) / 2, y0 + 5), "CUMPLES", font=fonts["head"], fill=255, anchor="ma")

    name_x = x0 + 44
    name_w = x1 - name_x - 8
    y = y0 + 33
    for e in birthdays:
        name = e.summary[7:] if e.summary.startswith("Cumple ") else e.summary
        d.text((x0 + 8, y + 1), e.start.strftime("%d/%m"), font=fonts["meta"], fill=90)
        d.text((name_x, y), _fit_text(name, fonts["task"], name_w), font=fonts["task"], fill=0)
        y += BDAY_ROW_H

    if hidden:
        d.text(((x0 + x1) / 2, y + 1), f"+{hidden} mas", font=fonts["meta"], fill=110, anchor="ma")


def draw_png(
    cfg: Config,
    events: list[Ev],
    start: date,
    tasks: list[Task] | None = None,
    birthdays: list[Ev] | None = None,
    generated: datetime | None = None,
    failed_feeds: int = 0,
) -> None:
    """Timetable from today forward (kindle_schedule-style) for KUAL.

    `generated` is stamped in the footer and marks the current time on today's
    column: without it a cached image on the Kindle looks identical to a fresh
    one. `failed_feeds` warns that the grid is missing a calendar's events.
    """
    # png_width/height describe the screen. For a rotated view the layout is
    # drawn sideways and rotated back at save time, so swap them here.
    w, h = canvas_size(cfg)
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)

    footer_h = FOOTER_H
    margin_l = 52  # hour labels
    margin_r = 16
    margin_t = 16
    # Single-line day header ("Lun 07") so the hour rows get the space back.
    header_h = 34
    margin_l = 40 if (cfg.end_hour - cfg.start_hour) > 16 else margin_l
    allday_h = 0

    f_day = pil_fonts(22, bold=True)
    f_hour = pil_fonts(16, bold=False)
    f_title = pil_fonts(18, bold=True)
    f_meta = pil_fonts(14, bold=False)
    f_chip = pil_fonts(13, bold=True)
    f_foot = pil_fonts(18, bold=True)
    f_task = pil_fonts(12, bold=True)
    f_task_meta = pil_fonts(11, bold=False)

    days = schedule_window(start, cfg.schedule_days)
    n_days = len(days)

    # All-day chips height
    max_allday = 0
    for day in days:
        max_allday = max(max_allday, len([e for e in events_on_day(events, day) if e.all_day]))
    if max_allday:
        allday_h = 10 + max_allday * 26

    grid_top = margin_t + header_h + allday_h
    grid_bottom = h - footer_h - 8
    grid_left = margin_l
    grid_right = w - margin_r

    tasks = tasks or []
    bdays = sorted(birthdays or [], key=lambda e: e.start)
    sidebar_w = 0.0
    if tasks or bdays:
        sidebar_w = max(150.0, min(215.0, w * 0.21))
        grid_right -= sidebar_w + 10

    grid_w = grid_right - grid_left
    col_w = grid_w / n_days

    start_h = cfg.start_hour
    end_h = cfg.end_hour
    if end_h <= start_h:
        end_h = start_h + 12
    hours = end_h - start_h

    # Which hours of the week hold a timed event; those always keep a full row.
    busy_hours: set[int] = set()
    for day in days:
        for e in events_on_day(events, day):
            if e.all_day or not isinstance(e.start, datetime):
                continue
            e_end = e.end if isinstance(e.end, datetime) else e.start + timedelta(hours=1)
            first = e.start.hour if e.start.date() == day else start_h
            last = e_end.hour if e_end.date() == day else end_h
            if e_end.minute == 0 and e_end > e.start:
                last -= 1  # an event ending at 10:00 does not occupy hour 10
            for hour in range(max(start_h, first), min(end_h - 1, last) + 1):
                busy_hours.add(hour)

    # Empty night hours shrink to NIGHT_ROW of a normal row.
    NIGHT_ROW = 0.42
    row_w: list[float] = []
    for hi in range(hours):
        hour = start_h + hi
        core = cfg.core_start_hour <= hour < cfg.core_end_hour
        if not cfg.compress_night or core or hour in busy_hours:
            row_w.append(1.0)
        else:
            row_w.append(NIGHT_ROW)

    unit = (grid_bottom - grid_top) / sum(row_w)
    row_y = [grid_top]
    for wt in row_w:
        row_y.append(row_y[-1] + wt * unit)

    # Scale the hour gutter to whatever height a normal row ended up with.
    if unit >= 32:
        f_hour = pil_fonts(16, bold=False)
    elif unit >= 22:
        f_hour = pil_fonts(13, bold=False)
    else:
        f_hour = pil_fonts(11, bold=False)
    f_hour_small = pil_fonts(10, bold=False)
    label_every = 1 if unit >= 15 else 2

    def y_for(dt: datetime, day: date) -> float:
        """Map a time to its pixel row, honouring the compressed night rows."""
        day_top = datetime.combine(day, time(start_h, 0), tzinfo=dt.tzinfo)
        mins = (dt - day_top).total_seconds() / 60.0
        mins = max(0.0, min(hours * 60.0, mins))
        hi = min(hours - 1, int(mins // 60))
        frac = (mins - hi * 60) / 60.0
        return row_y[hi] + frac * (row_y[hi + 1] - row_y[hi])

    # Day headers
    for i, day in enumerate(days):
        x = grid_left + i * col_w
        label = f"{WEEKDAYS_ES_SHORT[day.weekday()]} {day.day:02d}"
        d.text((x + col_w / 2, margin_t + 2), label, font=f_day, fill=0, anchor="ma")
        if day == start:
            d.rectangle([x + 8, margin_t - 2, x + col_w - 8, margin_t + header_h - 6], outline=0, width=2)

    # All-day row
    if allday_h:
        y0 = margin_t + header_h
        for i, day in enumerate(days):
            x = grid_left + i * col_w
            chips = [e for e in events_on_day(events, day) if e.all_day][:3]
            cy = y0 + 4
            for e in chips:
                box = [x + 6, cy, x + col_w - 6, cy + 22]
                d.rounded_rectangle(box, radius=6, outline=0, width=1, fill=235)
                txt = _fit_text(e.summary, f_chip, col_w - 20)
                d.text((x + col_w / 2, cy + 3), txt, font=f_chip, fill=0, anchor="ma")
                cy += 26

    # Hour lines + labels. Compressed rows get a tint so the jump is visible.
    for hi in range(hours):
        if row_w[hi] < 1.0:
            d.rectangle([grid_left, row_y[hi], grid_right, row_y[hi + 1]], fill=243)
    for hi in range(hours + 1):
        hour = start_h + hi
        y = row_y[hi]
        shade = 180 if hi % 2 == 0 else 210
        d.line([grid_left, y, grid_right, y], fill=shade, width=1)
        if hi >= hours:
            continue
        row_h = row_y[hi + 1] - y
        if row_h < 9:
            continue
        if row_w[hi] < 1.0:
            d.text((margin_l - 8, y - 1), f"{hour:02d}", font=f_hour_small, fill=90, anchor="rm")
        elif hi % label_every == 0:
            d.text((margin_l - 8, y - 2), f"{hour:02d}", font=f_hour, fill=0, anchor="rm")

    # Vertical day separators
    for i in range(n_days + 1):
        x = grid_left + i * col_w
        d.line([x, grid_top, x, grid_bottom], fill=200, width=1)

    # Timed events
    for i, day in enumerate(days):
        day_evs = events_on_day(events, day)
        lanes = _assign_lanes(day_evs)
        col_x0 = grid_left + i * col_w

        for idx, e in enumerate(day_evs):
            if e.all_day or not isinstance(e.start, datetime):
                continue
            end_dt = e.end if isinstance(e.end, datetime) else e.start + timedelta(hours=1)
            # clamp to visible window
            win_start = datetime.combine(day, time(start_h, 0), tzinfo=e.start.tzinfo)
            if end_h >= 24:
                # A full day ends at midnight of the next date; time(24) is invalid.
                win_end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=e.start.tzinfo)
            else:
                win_end = datetime.combine(day, time(end_h, 0), tzinfo=e.start.tzinfo)
            s = max(e.start, win_start)
            en = min(end_dt, win_end)
            if en <= s:
                continue

            lane, lane_count = lanes.get(idx, (0, 1))
            lane_count = max(1, lane_count)
            pad = 4
            inner_w = col_w - 2 * pad
            lane_w = inner_w / lane_count
            x0 = col_x0 + pad + lane * lane_w
            x1 = x0 + lane_w - 2
            y0 = y_for(s, day)
            y1 = y_for(en, day)
            if y1 - y0 < 22:
                y1 = y0 + 22
            box = [x0, y0, x1, y1]

            fill = 245
            ink = 0
            if e.style == "black":
                fill = 40
                ink = 255
                d.rounded_rectangle(box, radius=4, fill=fill, outline=0, width=1)
            elif e.style == "striped":
                _hatch_rect(d, box)
            else:
                d.rounded_rectangle(box, radius=4, fill=fill, outline=0, width=1)

            # Text inside block
            tx = x0 + 5
            ty = y0 + 4
            title = e.summary
            text_w = x1 - tx - 4
            when = f"{e.start.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
            # Short boxes (landscape rows) have no second line, so lead with the time.
            room_for_time = y1 - y0 >= 40
            # Narrow lanes can't fit "09:00 Reunion", and the title matters more.
            if not room_for_time and text_w >= 70:
                title = f"{e.start.strftime('%H:%M')} {title}"
            d.text((tx, ty), _fit_text(title, f_title, text_w), font=f_title, fill=ink)
            ty += 18
            if room_for_time:
                d.text((tx, ty), _fit_text(when, f_meta, text_w), font=f_meta, fill=ink)
                ty += 16
            if y1 - y0 >= 56:
                note = e.location or e.description
                if note:
                    d.text((tx, ty), _fit_text(note, f_meta, text_w), font=f_meta, fill=ink)

    if sidebar_w:
        side_fonts = {"head": f_foot, "task": f_task, "meta": f_task_meta}
        side_x0 = w - margin_r - sidebar_w
        side_x1 = w - margin_r

        # The birthday box takes only the height its rows need; tasks get the rest.
        bday_h = 0.0
        rows = len(bdays)
        avail = grid_bottom - margin_t - (150.0 if tasks else 0.0)
        while rows > 0 and _birthday_box_h(rows) > avail:
            rows -= 1
        hidden = len(bdays) - rows
        if hidden and rows:
            rows -= 1  # trade a row for the "+N mas" counter
            hidden += 1
        if rows:
            bday_h = _birthday_box_h(rows + (1 if hidden else 0))

        if tasks:
            tasks_bottom = grid_bottom - (bday_h + 10 if bday_h else 0)
            _draw_task_sidebar(d, tasks, (side_x0, margin_t, side_x1, tasks_bottom), start, side_fonts)
        if bday_h:
            b_y0 = grid_bottom - bday_h if tasks else margin_t
            _draw_birthday_box(d, bdays[:rows], (side_x0, b_y0, side_x1, b_y0 + bday_h), side_fonts, hidden)

    # Now marker: the build time is "now" only on the day it was generated.
    if generated is not None and generated.date() in days and start_h <= generated.hour < end_h:
        gi = days.index(generated.date())
        gx = grid_left + gi * col_w
        gy = y_for(generated, generated.date())
        d.line([gx, gy, gx + col_w, gy], fill=0, width=2)
        d.ellipse([gx - 3, gy - 3, gx + 3, gy + 3], fill=0)

    draw_exit_footer(d, w, h, generated, failed_feeds)
    save_kindle_png(cfg, img)


def draw_pdf(cfg: Config, events: list[Ev], start: date) -> None:
    """PDF: page 1 = same timetable as PNG; following pages = agenda list."""
    from reportlab.lib.utils import ImageReader

    font = try_register_fonts()
    bold = "Body-Bold" if font == "Body" and "Body-Bold" in pdfmetrics.getRegisteredFontNames() else font
    if font == "Helvetica":
        bold = "Helvetica-Bold"

    page = portrait((cfg.page_width_in * inch, cfg.page_height_in * inch))
    cfg.output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(cfg.output), pagesize=page)
    w, h = page
    margin = 0.18 * inch
    today = start

    # Page 1: embed the timetable PNG so PDF and KUAL view match
    if cfg.png_output.is_file():
        c.drawImage(
            ImageReader(str(cfg.png_output)),
            0,
            0,
            width=w,
            height=h,
            preserveAspectRatio=True,
            anchor="c",
        )
        c.showPage()
    else:
        c.setFont(bold, 12)
        c.drawCentredString(w / 2, h / 2, "Genera calendar.png primero")
        c.showPage()

    def new_page_header(title: str) -> float:
        c.setFont(bold, 11)
        c.drawString(margin, h - margin - 10, title)
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.8)
        c.line(margin, h - margin - 16, w - margin, h - margin - 16)
        return h - margin - 28

    # Following pages: text agenda
    y = 0
    for offset in range(cfg.days):
        day = start + timedelta(days=offset)
        day_evs = events_on_day(events, day)
        need = 28 + max(1, len(day_evs)) * 12
        if y < margin + need or offset == 0:
            if offset == 0:
                y = new_page_header(f"Agenda - proximos {cfg.days} dias")
            else:
                c.showPage()
                y = new_page_header(f"Agenda - {MONTHS_ES[day.month]} {day.year}")

        c.setFont(bold, 9)
        head = f"{WD_SHORT[day.weekday()]} {day.day}/{day.month}"
        if day == today:
            head += "  (hoy)"
        c.drawString(margin, y, head)
        y -= 12
        c.setFont(font, 8)
        if not day_evs:
            c.drawString(margin + 8, y, "(sin eventos)")
            y -= 12
        else:
            for e in day_evs:
                if y < margin + 24:
                    c.showPage()
                    y = new_page_header("Agenda (cont.)")
                    c.setFont(font, 8)
                line = f"{fmt_time(e)}  {sanitize_text(e.summary)}"[:56]
                c.drawString(margin + 6, y, line)
                y -= 11
                note = e.location or e.description
                if note and y >= margin + 20:
                    c.setFont(font, 7)
                    c.drawString(margin + 14, y, sanitize_text(note)[:52])
                    y -= 10
                    c.setFont(font, 8)
        y -= 8

    c.save()


def write_ci_config(path: Path) -> None:
    """Build config.toml from env vars (GitHub Actions)."""
    import os

    urls = [u.strip() for u in os.environ.get("ICS_URLS", "").split("|") if u.strip()]
    single = os.environ.get("ICS_URL", "").strip()
    if single:
        urls.insert(0, single)
    if not urls:
        raise SystemExit("Set ICS_URL or ICS_URLS env var for CI")
    # Public feeds (holidays, etc.) come from a variable, not a secret.
    urls += [u.strip() for u in os.environ.get("ICS_URLS_PUBLIC", "").split("|") if u.strip()]
    tz = os.environ.get("TIMEZONE", "America/Argentina/Buenos_Aires")
    days = os.environ.get("CALENDAR_DAYS", "14")
    extras = os.environ.get("EXTRAS_URL", "").strip()
    weather_lat = os.environ.get("WEATHER_LAT", "-31.4241")
    weather_lon = os.environ.get("WEATHER_LON", "-64.4978")
    weather_place = os.environ.get("WEATHER_PLACE", "Carlos Paz, Cordoba")
    # Must match the framebuffer fbink reports. PW1/PW2 = 758x1024,
    # Touch/K4 = 600x800, PW3/PW4 = 1072x1448.
    png_w = os.environ.get("PNG_WIDTH", "758")
    png_h = os.environ.get("PNG_HEIGHT", "1024")
    # 90 = landscape view for a Kindle stood on its right edge.
    png_rot = os.environ.get("PNG_ROTATE", "90")
    lines = [
        "ics_urls = [",
        *[f'  "{u.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}",' for u in urls],
        "]",
        f'timezone = "{tz}"',
        f"days = {days}",
        f"schedule_days = {os.environ.get('SCHEDULE_DAYS', '5')}",
        f"start_hour = {os.environ.get('START_HOUR', '0')}",
        f"end_hour = {os.environ.get('END_HOUR', '24')}",
        f"compress_night = {os.environ.get('COMPRESS_NIGHT', 'true').lower()}",
        f"core_start_hour = {os.environ.get('CORE_START_HOUR', '7')}",
        f"core_end_hour = {os.environ.get('CORE_END_HOUR', '23')}",
        'output = "output/calendar.pdf"',
        'png_output = "output/calendar.png"',
        "insecure_ssl = false",
        f'extras_url = "{extras.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"',
        f"weather_lat = {weather_lat}",
        f"weather_lon = {weather_lon}",
        f'weather_place = "{weather_place.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"',
        "[screen]",
        "width_in = 3.58",
        "height_in = 4.82",
        f"png_width = {png_w}",
        f"png_height = {png_h}",
        f"png_rotate = {png_rot}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Kindle calendar PDF+PNG from Google ICS.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("config.toml"),
        help="Path to config.toml",
    )
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="Write config from ICS_URL / ICS_URLS / TIMEZONE env vars (CI)",
    )
    args = parser.parse_args()
    if args.from_env:
        args.config.parent.mkdir(parents=True, exist_ok=True)
        write_ci_config(args.config)
        print(f"Wrote CI config {args.config}")
    if not args.config.is_file():
        example = args.config.with_name("config.example.toml")
        raise SystemExit(
            f"Missing {args.config}. Copy {example.name} to config.toml and add your ICS URL(s)."
        )

    cfg = load_config(args.config)
    tz = ZoneInfo(cfg.timezone)
    blobs: list[bytes] = []
    failed_feeds = 0
    if cfg.ics_urls:
        print(f"Fetching {len(cfg.ics_urls)} calendar URL(s)...")
        for i, u in enumerate(cfg.ics_urls, 1):
            try:
                blobs.append(fetch_ics(u, cfg.insecure_ssl))
            except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the build
                failed_feeds += 1
                # Don't log the URL: it is a secret address.
                print(f"WARNING: calendar #{i} failed ({exc}). Check that secret iCal URL.")
    for f in cfg.ics_files:
        print(f"Reading {f}...")
        blobs.append(f.read_bytes())
    if not blobs:
        raise SystemExit("No calendar data: every ICS source failed. Check ICS_URL / ICS_URLS.")
    cal = merge_calendars(blobs)
    start = local_today(tz)
    month_start = start.replace(day=1)
    if start.month == 12:
        month_last = date(start.year, 12, 31)
    else:
        month_last = date(start.year, start.month + 1, 1) - timedelta(days=1)
    end = max(start + timedelta(days=cfg.days + 40), month_last + timedelta(days=1))
    events = collect_events(cal, month_start, end, tz)
    print(f"Parsed {len(events)} event instances in window.")
    tasks, birthdays = fetch_extras(cfg)
    events.extend(birthdays)
    generated = datetime.now(tz)

    import boards

    weather = boards.fetch_weather(cfg)
    draw_png(cfg, events, start, tasks, birthdays, generated, failed_feeds)
    print(f"Wrote {cfg.png_output}")
    today_path = boards.draw_today_png(cfg, events, start, tasks, birthdays, generated, failed_feeds, weather)
    print(f"Wrote {today_path}")
    weather_path = boards.draw_weather_png(cfg, weather, generated)
    print(f"Wrote {weather_path}")
    month_path = boards.draw_month_png(cfg, events, start, generated, failed_feeds)
    print(f"Wrote {month_path}")
    draw_pdf(cfg, events, start)
    print(f"Wrote {cfg.output}")


if __name__ == "__main__":
    main()
