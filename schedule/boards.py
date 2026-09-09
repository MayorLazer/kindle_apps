"""Desk-board PNGs for the Kindle: Hoy, Semanal, Clima, Mes.

Calendar week grid stays in generate.draw_png. Semanal is that grid plus
weather; Hoy / Clima / Mes are glance views. Never fatal: a missing
forecast still writes a PNG.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image, ImageDraw, ImageFont

import generate as g


@dataclass
class DayForecast:
    day: date
    tmin: float | None
    tmax: float | None
    code: int | None
    pop: int | None  # precipitation probability 0-100
    precip: float | None


@dataclass
class Weather:
    place: str
    temp: float | None = None
    apparent: float | None = None
    humidity: int | None = None
    wind_kmh: float | None = None
    code: int | None = None
    daily: list[DayForecast] = field(default_factory=list)
    ok: bool = False


def weather_kind(code: int | None) -> str:
    if code is None:
        return "unknown"
    if code == 0:
        return "sun"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "cloud"


def weather_label(code: int | None) -> str:
    return {
        "sun": "Despejado",
        "partly": "Parcial",
        "cloud": "Nublado",
        "fog": "Niebla",
        "drizzle": "Llovizna",
        "rain": "Lluvia",
        "snow": "Nieve",
        "storm": "Tormenta",
        "unknown": "Sin datos",
    }[weather_kind(code)]


def _num(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_weather(cfg: g.Config) -> Weather:
    """Open-Meteo forecast. No API key. Failure returns ok=False."""
    place = (cfg.weather_place or "Carlos Paz, Cordoba").strip() or "Carlos Paz, Cordoba"
    empty = Weather(place=place, ok=False)
    qs = urlencode(
        {
            "latitude": f"{cfg.weather_lat:.4f}",
            "longitude": f"{cfg.weather_lon:.4f}",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
            "timezone": cfg.timezone,
            "forecast_days": 7,
            "wind_speed_unit": "kmh",
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{qs}"
    try:
        raw = g.fetch_ics(url, cfg.insecure_ssl)
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - weather must not stop the build
        print(f"WARNING: weather feed failed: {exc}")
        return empty

    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    days: list[DayForecast] = []
    dates = daily.get("time") or []
    for i, iso in enumerate(dates):
        try:
            day = date.fromisoformat(str(iso)[:10])
        except ValueError:
            continue
        codes = daily.get("weather_code") or []
        tmaxs = daily.get("temperature_2m_max") or []
        tmins = daily.get("temperature_2m_min") or []
        pops = daily.get("precipitation_probability_max") or []
        rains = daily.get("precipitation_sum") or []
        days.append(
            DayForecast(
                day=day,
                tmax=_num(tmaxs[i] if i < len(tmaxs) else None),
                tmin=_num(tmins[i] if i < len(tmins) else None),
                code=int(codes[i]) if i < len(codes) and codes[i] is not None else None,
                pop=int(pops[i]) if i < len(pops) and pops[i] is not None else None,
                precip=_num(rains[i] if i < len(rains) else None),
            )
        )

    w = Weather(
        place=place,
        temp=_num(cur.get("temperature_2m")),
        apparent=_num(cur.get("apparent_temperature")),
        humidity=int(cur["relative_humidity_2m"]) if cur.get("relative_humidity_2m") is not None else None,
        wind_kmh=_num(cur.get("wind_speed_10m")),
        code=int(cur["weather_code"]) if cur.get("weather_code") is not None else None,
        daily=days,
        ok=True,
    )
    print(f"Weather: {place} {fmt_temp(w.temp)} {weather_label(w.code)}, {len(days)} day(s).")
    return w


def fmt_temp(v: float | None) -> str:
    if v is None:
        return "--"
    return f"{int(round(v))} C"


def rain_alert(weather: Weather | None, today: date, threshold: int = 40) -> str:
    """Short footer warning when rain is likely today or tomorrow."""
    if weather is None or not weather.ok or not weather.daily:
        return ""
    by_day = {fc.day: fc for fc in weather.daily}
    parts: list[str] = []
    for label, day in (("hoy", today), ("manana", today + timedelta(days=1))):
        fc = by_day.get(day)
        if fc is None:
            continue
        pop = fc.pop if fc.pop is not None else 0
        wet = pop >= threshold or (fc.precip is not None and fc.precip >= 0.5)
        rainy = weather_kind(fc.code) in ("drizzle", "rain", "storm")
        if wet or rainy:
            if pop:
                parts.append(f"{label} {pop}%")
            else:
                parts.append(label)
    if not parts:
        return ""
    return "Lluvia " + " · ".join(parts)


def _new_canvas(cfg: g.Config) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int]:
    w, h = g.canvas_size(cfg)
    img = Image.new("L", (w, h), 255)
    return img, ImageDraw.Draw(img), w, h


def _draw_icon(d: ImageDraw.ImageDraw, box: tuple[float, float, float, float], code: int | None) -> None:
    """Small high-contrast weather glyph. No emoji — e-ink fonts miss them."""
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    s = min(x1 - x0, y1 - y0)
    r = s * 0.22
    kind = weather_kind(code)

    if kind == "sun":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=2)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (0.7, 0.7), (0.7, -0.7), (-0.7, 0.7), (-0.7, -0.7)):
            d.line([cx + dx * r * 1.35, cy + dy * r * 1.35, cx + dx * r * 1.85, cy + dy * r * 1.85], fill=0, width=2)
        return
    if kind == "partly":
        d.ellipse([cx - r * 1.15, cy - r * 1.25, cx - r * 0.15, cy - r * 0.25], outline=0, width=2)
        d.rounded_rectangle([cx - r * 1.1, cy - r * 0.15, cx + r * 1.2, cy + r * 0.95], radius=r * 0.7, outline=0, width=2, fill=255)
        return
    if kind == "fog":
        for i, yy in enumerate((-0.45, -0.05, 0.35)):
            d.line([cx - r * 1.3, cy + yy * s * 0.4, cx + r * 1.3, cy + yy * s * 0.4], fill=0, width=2)
        return
    if kind in ("drizzle", "rain", "storm", "snow", "cloud"):
        d.rounded_rectangle([cx - r * 1.15, cy - r * 0.7, cx + r * 1.15, cy + r * 0.45], radius=r * 0.65, outline=0, width=2, fill=230)
        if kind == "cloud":
            return
        if kind == "storm":
            d.line([cx + 2, cy - r * 0.2, cx - 6, cy + r * 0.7, cx + 8, cy + r * 0.7, cx, cy + r * 1.35], fill=0, width=2)
            return
        step = 5 if kind != "drizzle" else 6
        y_drop = cy + r * 0.55
        for i in range(-2, 3):
            x = cx + i * step
            if kind == "snow":
                d.ellipse([x - 2, y_drop, x + 2, y_drop + 4], outline=0, width=1)
            else:
                d.line([x, y_drop, x - 2, y_drop + r * 0.7], fill=0, width=1)
        return
    d.rectangle([cx - r, cy - r, cx + r, cy + r], outline=0, width=1)


def _header_bar(d: ImageDraw.ImageDraw, x0: float, y0: float, x1: float, title: str, font: ImageFont.ImageFont) -> None:
    d.rectangle([x0, y0, x1, y0 + 28], fill=0)
    d.text(((x0 + x1) / 2, y0 + 5), title, font=font, fill=255, anchor="ma")


def _event_lines(day_evs: list[g.Ev], limit: int) -> list[str]:
    lines: list[str] = []
    for e in day_evs:
        if e.all_day:
            lines.append(e.summary)
        elif isinstance(e.start, datetime):
            lines.append(f"{e.start.strftime('%H:%M')} {e.summary}")
        if len(lines) >= limit:
            break
    return lines


def draw_weekly_png(
    cfg: g.Config,
    events: list[g.Ev],
    start: date,
    tasks: list[g.Task] | None = None,
    birthdays: list[g.Ev] | None = None,
    generated: datetime | None = None,
    failed_feeds: int = 0,
    weather: Weather | None = None,
) -> Path:
    """Week timetable + tasks + birthdays + weather (Semanal board)."""
    wx = weather if weather is not None else Weather(place=cfg.weather_place, ok=False)
    return g.draw_png(
        cfg,
        events,
        start,
        tasks,
        birthdays,
        generated,
        failed_feeds,
        weather=wx,
        dest=g.sibling_png(cfg, "weekly.png"),
        footer_extra=rain_alert(wx, start),
    )


def draw_today_png(
    cfg: g.Config,
    events: list[g.Ev],
    start: date,
    tasks: list[g.Task] | None = None,
    birthdays: list[g.Ev] | None = None,
    generated: datetime | None = None,
    failed_feeds: int = 0,
    weather: Weather | None = None,
) -> Path:
    """One-screen blotter: date, weather line, today, tomorrow, tasks."""
    img, d, w, h = _new_canvas(cfg)
    footer_h = g.FOOTER_H
    margin = 16
    tasks = tasks or []
    bdays = sorted(birthdays or [], key=lambda e: e.start)

    f_wd = g.pil_fonts(40, bold=True)
    f_mon = g.pil_fonts(20, bold=False)
    f_temp = g.pil_fonts(40, bold=True)
    f_cond = g.pil_fonts(16, bold=False)
    f_head = g.pil_fonts(18, bold=True)
    f_row = g.pil_fonts(17, bold=True)
    f_meta = g.pil_fonts(14, bold=False)
    f_task = g.pil_fonts(12, bold=True)
    f_task_meta = g.pil_fonts(11, bold=False)

    wd = g.WEEKDAYS_ES[start.weekday()]
    d.text((margin, 10), f"{wd} {start.day}", font=f_wd, fill=0)
    d.text((margin, 56), f"{g.MONTHS_ES[start.month]} {start.year}", font=f_mon, fill=80)

    if weather and weather.ok:
        wx = w - margin
        d.text((wx, 12), fmt_temp(weather.temp), font=f_temp, fill=0, anchor="ra")
        d.text((wx, 56), weather_label(weather.code), font=f_cond, fill=80, anchor="ra")
        if weather.place:
            d.text((wx, 76), g._fit_text(weather.place, f_meta, 220), font=f_meta, fill=110, anchor="ra")
        _draw_icon(d, (wx - 210, 10, wx - 150, 70), weather.code)

    y0 = 100
    y1 = h - footer_h - 8
    gap = 10
    side_w = max(170.0, min(230.0, w * 0.24)) if (tasks or bdays) else 0.0
    left_x1 = w - margin - side_w - (gap if side_w else 0)
    left_x0 = margin

    today_evs = g.events_on_day(events, start)
    tomorrow = start + timedelta(days=1)
    tom_evs = g.events_on_day(events, tomorrow)

    # Tomorrow takes a compact strip; today gets the rest.
    tom_h = 28 + 8 + max(1, min(3, len(tom_evs) or 1)) * 22 + 8
    tom_h = min(tom_h, (y1 - y0) * 0.38)
    today_h = y1 - y0 - tom_h - gap

    def _event_panel(
        box: tuple[float, float, float, float],
        title: str,
        evs: list[g.Ev],
        empty: str,
    ) -> None:
        x0, yy0, x1, yy1 = box
        d.rectangle([x0, yy0, x1, yy1], outline=0, width=1, fill=250)
        _header_bar(d, x0, yy0, x1, title, f_head)
        y = yy0 + 36
        if not evs:
            d.text(((x0 + x1) / 2, y + 8), empty, font=f_meta, fill=120, anchor="ma")
            return
        shown = 0
        for e in evs:
            if y + 20 > yy1 - 8:
                break
            when = "todo el dia" if e.all_day else (e.start.strftime("%H:%M") if isinstance(e.start, datetime) else "")
            d.text((x0 + 10, y), when, font=f_meta, fill=90)
            title_x = x0 + 96
            d.text((title_x, y - 1), g._fit_text(e.summary, f_row, x1 - title_x - 10), font=f_row, fill=0)
            y += 20
            note = e.location
            if note and y + 14 < yy1 - 8:
                d.text((title_x, y - 2), g._fit_text(note, f_meta, x1 - title_x - 10), font=f_meta, fill=110)
                y += 14
            y += 4
            shown += 1
        if shown < len(evs):
            d.text(((x0 + x1) / 2, yy1 - 16), f"+{len(evs) - shown} mas", font=f_meta, fill=110, anchor="ma")

    _event_panel((left_x0, y0, left_x1, y0 + today_h), "HOY", today_evs, "sin eventos")
    tom_title = f"MANANA  {g.WEEKDAYS_ES_SHORT[tomorrow.weekday()]} {tomorrow.day}"
    _event_panel((left_x0, y0 + today_h + gap, left_x1, y1), tom_title, tom_evs, "sin eventos")

    if side_w:
        side_fonts = {"head": f_head, "task": f_task, "meta": f_task_meta}
        sx0 = w - margin - side_w
        sx1 = w - margin
        bday_h = 0.0
        rows = len(bdays)
        avail = y1 - y0 - (140.0 if tasks else 0.0)
        while rows > 0 and g._birthday_box_h(rows) > avail:
            rows -= 1
        hidden = len(bdays) - rows
        if hidden and rows:
            rows -= 1
            hidden += 1
        if rows:
            bday_h = g._birthday_box_h(rows + (1 if hidden else 0))
        if tasks:
            tasks_bottom = y1 - (bday_h + 10 if bday_h else 0)
            g._draw_task_sidebar(d, tasks, (sx0, y0, sx1, tasks_bottom), start, side_fonts)
        if bday_h:
            by0 = y1 - bday_h if tasks else y0
            g._draw_birthday_box(d, bdays[:rows], (sx0, by0, sx1, by0 + bday_h), side_fonts, hidden)

    extras: list[str] = []
    if weather is not None and not weather.ok:
        extras.append("SIN DATOS: clima")
    alert = rain_alert(weather, start)
    if alert:
        extras.append(alert)
    g.draw_exit_footer(d, w, h, generated, failed_feeds, "  -  ".join(extras))
    return g.save_kindle_png(cfg, img, g.sibling_png(cfg, "today.png"))


def draw_weather_png(
    cfg: g.Config,
    weather: Weather,
    generated: datetime | None = None,
) -> Path:
    img, d, w, h = _new_canvas(cfg)
    footer_h = g.FOOTER_H
    margin = 20

    f_place = g.pil_fonts(22, bold=True)
    f_temp = g.pil_fonts(84, bold=True)
    f_cond = g.pil_fonts(26, bold=True)
    f_meta = g.pil_fonts(16, bold=False)
    f_day = g.pil_fonts(16, bold=True)
    f_small = g.pil_fonts(14, bold=False)
    f_head = g.pil_fonts(18, bold=True)

    d.text((margin, 14), weather.place.upper(), font=f_place, fill=0)
    d.text((margin, 48), fmt_temp(weather.temp) if weather.ok else "-- C", font=f_temp, fill=0)
    d.text((margin, 148), weather_label(weather.code) if weather.ok else "Sin datos", font=f_cond, fill=0)

    bits: list[str] = []
    if weather.ok:
        if weather.apparent is not None:
            bits.append(f"ST {fmt_temp(weather.apparent)}")
        if weather.humidity is not None:
            bits.append(f"Hum {weather.humidity}%")
        if weather.wind_kmh is not None:
            bits.append(f"Viento {int(round(weather.wind_kmh))} km/h")
    d.text((margin, 184), "   ".join(bits), font=f_meta, fill=80)
    _draw_icon(d, (w - 150, 40, w - margin, 150), weather.code if weather.ok else None)

    cards_top = 220
    cards_bot = h - footer_h - 16
    days = weather.daily[:7]
    n = max(1, len(days))
    grid_w = w - 2 * margin
    col = grid_w / n
    for i, fc in enumerate(days):
        x0 = margin + i * col + 4
        x1 = margin + (i + 1) * col - 4
        d.rectangle([x0, cards_top, x1, cards_bot], outline=0, width=1, fill=250)
        label = f"{g.WEEKDAYS_ES_SHORT[fc.day.weekday()]} {fc.day.day:02d}"
        d.text(((x0 + x1) / 2, cards_top + 10), label, font=f_day, fill=0, anchor="ma")
        _draw_icon(d, (x0 + 8, cards_top + 36, x1 - 8, cards_top + 108), fc.code)
        d.text(((x0 + x1) / 2, cards_top + 118), fmt_temp(fc.tmax), font=f_head, fill=0, anchor="ma")
        d.text(((x0 + x1) / 2, cards_top + 142), fmt_temp(fc.tmin), font=f_small, fill=90, anchor="ma")
        cond = weather_label(fc.code)
        d.text(((x0 + x1) / 2, cards_top + 166), g._fit_text(cond, f_small, x1 - x0 - 8), font=f_small, fill=0, anchor="ma")
        rain_bits = []
        if fc.pop is not None:
            rain_bits.append(f"{fc.pop}%")
        if fc.precip is not None and fc.precip > 0:
            rain_bits.append(f"{fc.precip:.1f} mm")
        if rain_bits:
            d.text(((x0 + x1) / 2, cards_bot - 18), " ".join(rain_bits), font=f_small, fill=80, anchor="ma")

    if not days:
        d.text((w / 2, (cards_top + cards_bot) / 2), "sin pronostico", font=f_meta, fill=120, anchor="mm")

    extra = "" if weather.ok else "SIN DATOS: clima"
    g.draw_exit_footer(d, w, h, generated, 0, extra)
    return g.save_kindle_png(cfg, img, g.sibling_png(cfg, "weather.png"))


def draw_month_png(
    cfg: g.Config,
    events: list[g.Ev],
    start: date,
    generated: datetime | None = None,
    failed_feeds: int = 0,
) -> Path:
    """Month wall: Monday-first grid, today outlined, up to two event lines."""
    img, d, w, h = _new_canvas(cfg)
    footer_h = g.FOOTER_H
    margin = 14

    f_title = g.pil_fonts(28, bold=True)
    f_wd = g.pil_fonts(14, bold=True)
    f_num = g.pil_fonts(16, bold=True)
    f_ev = g.pil_fonts(11, bold=False)

    title = f"{g.MONTHS_ES[start.month]} {start.year}"
    d.text((w / 2, 10), title, font=f_title, fill=0, anchor="ma")

    # Build Monday-first weeks covering the month (including leading/trailing days).
    first = start.replace(day=1)
    lead = first.weekday()  # Monday=0
    cell0 = first - timedelta(days=lead)
    weeks = 6
    days = [cell0 + timedelta(days=i) for i in range(weeks * 7)]

    head_y = 48
    grid_top = 70
    grid_bot = h - footer_h - 8
    grid_left = margin
    grid_right = w - margin
    col_w = (grid_right - grid_left) / 7
    row_h = (grid_bot - grid_top) / weeks

    for i, label in enumerate(g.WD_SHORT):
        x = grid_left + i * col_w + col_w / 2
        fill = 80 if i >= 5 else 0
        d.text((x, head_y), label, font=f_wd, fill=fill, anchor="ma")

    for idx, day in enumerate(days):
        r, c = divmod(idx, 7)
        x0 = grid_left + c * col_w
        y0 = grid_top + r * row_h
        x1 = x0 + col_w
        y1 = y0 + row_h
        in_month = day.month == start.month
        fill = 255 if in_month else 242
        if c >= 5 and in_month:
            fill = 248
        d.rectangle([x0, y0, x1, y1], outline=200, width=1, fill=fill)
        ink = 0 if in_month else 160
        if day == start:
            d.rectangle([x0 + 1, y0 + 1, x1 - 1, y1 - 1], outline=0, width=2)
        d.text((x0 + 6, y0 + 3), f"{day.day}", font=f_num, fill=ink)
        if not in_month:
            continue
        lines = _event_lines(g.events_on_day(events, day), 3)
        ty = y0 + 22
        for line in lines:
            if ty + 12 > y1 - 3:
                break
            d.text((x0 + 5, ty), g._fit_text(line, f_ev, col_w - 10), font=f_ev, fill=0)
            ty += 13

    g.draw_exit_footer(d, w, h, generated, failed_feeds)
    return g.save_kindle_png(cfg, img, g.sibling_png(cfg, "month.png"))
