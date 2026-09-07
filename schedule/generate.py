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
    page_width_in: float
    page_height_in: float
    insecure_ssl: bool


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
        page_width_in=float(screen.get("width_in", 3.58)),
        page_height_in=float(screen.get("height_in", 4.82)),
        insecure_ssl=bool(data.get("insecure_ssl", False)),
    )


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
        if ch in "·•●∙":
            out.append("-")
            continue
        if ch in "—–―":
            out.append("-")
            continue
        if ch == "…":
            out.append("...")
            continue
        if ch in "“”„":
            out.append('"')
            continue
        if ch in "‘’":
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
    """Map event index -> (lane, lane_count) for overlapping timed events."""
    timed = [(i, e) for i, e in enumerate(day_events) if not e.all_day and isinstance(e.start, datetime)]
    timed.sort(key=lambda t: (t[1].start, t[1].end))
    lane_end: list[datetime] = []
    assigned: dict[int, int] = {}
    for i, e in timed:
        assert isinstance(e.start, datetime) and isinstance(e.end, datetime)
        lane = 0
        while lane < len(lane_end) and e.start < lane_end[lane]:
            lane += 1
        if lane == len(lane_end):
            lane_end.append(e.end)
        else:
            lane_end[lane] = e.end
        assigned[i] = lane
    # lane_count = max concurrent approx = max lane+1 seen
    max_lane = max(assigned.values(), default=0) + 1
    # Better: per-event, count how many share overlap group - use global max for simplicity
    return {i: (assigned[i], max_lane) for i in assigned}


def draw_png(cfg: Config, events: list[Ev], start: date) -> None:
    """Weekly timetable view (kindle_schedule-style) for PW4 / KUAL."""
    w, h = cfg.png_width, cfg.png_height
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)

    footer_h = 72
    margin_l = 52  # hour labels
    margin_r = 16
    margin_t = 16
    header_h = 70
    allday_h = 0

    f_day = pil_fonts(20, bold=True)
    f_day_num = pil_fonts(28, bold=True)
    f_hour = pil_fonts(16, bold=False)
    f_title = pil_fonts(18, bold=True)
    f_meta = pil_fonts(14, bold=False)
    f_chip = pil_fonts(13, bold=True)
    f_foot = pil_fonts(18, bold=True)
    f_hint = pil_fonts(15, bold=False)

    # Week starts Monday of current week
    week_start = start - timedelta(days=start.weekday())
    n_days = max(1, min(cfg.schedule_days, 7))
    days = [week_start + timedelta(days=i) for i in range(n_days)]

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
    grid_w = grid_right - grid_left
    col_w = grid_w / n_days

    start_h = cfg.start_hour
    end_h = cfg.end_hour
    if end_h <= start_h:
        end_h = start_h + 12
    hours = end_h - start_h
    hour_h = (grid_bottom - grid_top) / hours

    def y_for(dt: datetime) -> float:
        mins = (dt.hour - start_h) * 60 + dt.minute
        mins = max(0, min(hours * 60, mins))
        return grid_top + (mins / 60.0) * hour_h

    # Day headers
    for i, day in enumerate(days):
        x = grid_left + i * col_w
        label = WEEKDAYS_ES[day.weekday()].capitalize()
        d.text((x + col_w / 2, margin_t + 4), label, font=f_day, fill=0, anchor="ma")
        d.text((x + col_w / 2, margin_t + 30), f"{day.day:02d}", font=f_day_num, fill=0, anchor="ma")
        if day == start:
            d.rectangle([x + 8, margin_t, x + col_w - 8, margin_t + header_h - 8], outline=0, width=2)

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
                txt = e.summary
                if len(txt) > 16:
                    txt = txt[:14] + ".."
                d.text((x + col_w / 2, cy + 3), txt, font=f_chip, fill=0, anchor="ma")
                cy += 26

    # Hour lines + labels
    for hi in range(hours + 1):
        hour = start_h + hi
        y = grid_top + hi * hour_h
        shade = 180 if hi % 2 == 0 else 210
        d.line([grid_left, y, grid_right, y], fill=shade, width=1)
        if hi < hours:
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
            y0 = y_for(s)
            y1 = y_for(en)
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
            max_c = max(6, int((x1 - x0) / 9))
            if len(title) > max_c:
                title = title[: max_c - 2] + ".."
            d.text((tx, ty), title, font=f_title, fill=ink)
            ty += 18
            if y1 - y0 >= 40:
                when = f"{e.start.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
                d.text((tx, ty), when, font=f_meta, fill=ink)
                ty += 16
            if y1 - y0 >= 56:
                note = e.location or e.description
                if note:
                    if len(note) > max_c:
                        note = note[: max_c - 2] + ".."
                    d.text((tx, ty), note, font=f_meta, fill=ink)

    # Footer exit
    d.rectangle([0, h - footer_h, w, h], fill=0)
    d.text((w // 2, h - footer_h + 18), "SALIR", font=f_foot, fill=255, anchor="ma")
    d.text(
        (w // 2, h - footer_h + 44),
        "Boton power  |  KUAL > Calendario > Salir",
        font=f_hint,
        fill=255,
        anchor="ma",
    )

    cfg.png_output.parent.mkdir(parents=True, exist_ok=True)
    img.save(cfg.png_output, format="PNG", optimize=True)


def draw_pdf(cfg: Config, events: list[Ev], start: date) -> None:
    """PDF: page 1 = same weekly timetable as PNG; following pages = agenda list."""
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
    tz = os.environ.get("TIMEZONE", "America/Argentina/Buenos_Aires")
    days = os.environ.get("CALENDAR_DAYS", "14")
    # Must match the device framebuffer. PW1/PW2 = 758x1024, PW3/PW4 = 1072x1448.
    png_w = os.environ.get("PNG_WIDTH", "758")
    png_h = os.environ.get("PNG_HEIGHT", "1024")
    lines = [
        "ics_urls = [",
        *[f'  "{u.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}",' for u in urls],
        "]",
        f'timezone = "{tz}"',
        f"days = {days}",
        "schedule_days = 5",
        "start_hour = 8",
        "end_hour = 22",
        'output = "output/calendar.pdf"',
        'png_output = "output/calendar.png"',
        "insecure_ssl = false",
        "[screen]",
        "width_in = 3.58",
        "height_in = 4.82",
        f"png_width = {png_w}",
        f"png_height = {png_h}",
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
    if cfg.ics_urls:
        print(f"Fetching {len(cfg.ics_urls)} calendar URL(s)...")
        blobs.extend(fetch_ics(u, cfg.insecure_ssl) for u in cfg.ics_urls)
    for f in cfg.ics_files:
        print(f"Reading {f}...")
        blobs.append(f.read_bytes())
    if not blobs:
        raise SystemExit("No calendar data")
    cal = merge_calendars(blobs)
    start = date.today()
    end = start + timedelta(days=cfg.days + 40)
    events = collect_events(cal, start, end, tz)
    print(f"Parsed {len(events)} event instances in window.")
    draw_png(cfg, events, start)
    print(f"Wrote {cfg.png_output}")
    draw_pdf(cfg, events, start)
    print(f"Wrote {cfg.output}")


if __name__ == "__main__":
    main()
