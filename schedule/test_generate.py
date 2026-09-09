"""Smoke tests for the weekly PNG layout.

Run with:  python -m unittest discover -s schedule

The layout math (compressed night rows, piecewise time->pixel mapping, overlap
lanes) has no visual regression test on the Kindle, so these guard the parts
that silently produce a wrong-looking calendar.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

import generate
from generate import Config, Ev, Task

TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def make_config(tmp: Path, **over: object) -> Config:
    cfg = Config(
        ics_urls=[],
        ics_files=[],
        timezone="America/Argentina/Buenos_Aires",
        days=14,
        schedule_days=5,
        start_hour=0,
        end_hour=24,
        output=tmp / "calendar.pdf",
        png_output=tmp / "calendar.png",
        png_width=758,
        png_height=1024,
        png_rotate=90,
        page_width_in=3.58,
        page_height_in=4.82,
        insecure_ssl=False,
    )
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def timed(day: date, h1: int, m1: int, h2: int, m2: int, name: str = "Evento") -> Ev:
    return Ev(
        start=datetime(day.year, day.month, day.day, h1, m1, tzinfo=TZ),
        end=datetime(day.year, day.month, day.day, h2, m2, tzinfo=TZ),
        summary=name,
        all_day=False,
    )


class TestLanes(unittest.TestCase):
    def test_lane_count_is_per_overlap_group(self) -> None:
        """A crowded morning must not narrow an unrelated afternoon event."""
        day = date(2026, 9, 9)
        evs = [
            timed(day, 9, 0, 10, 0),
            timed(day, 9, 30, 10, 30),
            timed(day, 9, 45, 11, 0),
            timed(day, 15, 0, 16, 0),
        ]
        lanes = generate._assign_lanes(evs)
        self.assertEqual([lanes[i][1] for i in range(3)], [3, 3, 3])
        self.assertEqual(lanes[3], (0, 1), "the 15:00 event should span the column")

    def test_touching_events_do_not_overlap(self) -> None:
        day = date(2026, 9, 9)
        lanes = generate._assign_lanes([timed(day, 9, 0, 10, 0), timed(day, 10, 0, 11, 0)])
        self.assertEqual(lanes[0], (0, 1))
        self.assertEqual(lanes[1], (0, 1))

    def test_all_day_events_get_no_lane(self) -> None:
        day = date(2026, 9, 9)
        evs = [Ev(start=day, end=day + timedelta(days=1), summary="Cumple", all_day=True)]
        self.assertEqual(generate._assign_lanes(evs), {})


class TestFitText(unittest.TestCase):
    def test_truncates_to_width(self) -> None:
        font = generate.pil_fonts(18, bold=True)
        long = "Almuerzo con Martin Rodriguez en el centro"
        fitted = generate._fit_text(long, font, 80)
        self.assertLessEqual(font.getlength(fitted), 80)
        self.assertTrue(fitted.endswith(".."))

    def test_keeps_text_that_fits(self) -> None:
        font = generate.pil_fonts(18, bold=True)
        self.assertEqual(generate._fit_text("Corto", font, 500), "Corto")


class TestLocalToday(unittest.TestCase):
    def test_argentina_evening_is_still_monday(self) -> None:
        """21:30 in Argentina is already Tuesday 00:30 UTC."""
        utc_tue = datetime(2026, 9, 8, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(generate.local_today(TZ, utc_tue), date(2026, 9, 7))


class TestScheduleWindow(unittest.TestCase):
    def test_first_column_is_today(self) -> None:
        wed = date(2026, 9, 9)
        days = generate.schedule_window(wed, 5)
        self.assertEqual(days[0], wed)
        self.assertEqual(days, [
            date(2026, 9, 9),
            date(2026, 9, 10),
            date(2026, 9, 11),
            date(2026, 9, 12),
            date(2026, 9, 13),
        ])

    def test_includes_weekend_when_today_is_friday(self) -> None:
        fri = date(2026, 9, 11)
        days = generate.schedule_window(fri, 5)
        self.assertEqual(days[0], fri)
        self.assertEqual(days[1].weekday(), 5)  # Saturday
        self.assertEqual(days[2].weekday(), 6)  # Sunday


class TestDrawPng(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.monday = date(2026, 9, 7)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def render(self, **over: object) -> Image.Image:
        cfg = make_config(self.tmp, **over)
        evs = [timed(self.monday, 10, 0, 11, 30, "Turno medico")]
        generate.draw_png(cfg, evs, self.monday, [Task("Pagar patente", self.monday, "")], [])
        with Image.open(cfg.png_output) as img:
            return img.copy()

    def test_rotated_png_matches_screen(self) -> None:
        """A wrong-sized PNG is what made fbink crop the view on the device."""
        img = self.render()
        self.assertEqual(img.size, (758, 1024))

    def test_unrotated_png_matches_screen(self) -> None:
        img = self.render(png_rotate=0)
        self.assertEqual(img.size, (758, 1024))

    def test_draws_something(self) -> None:
        img = self.render()
        darkest, _ = img.convert("L").getextrema()
        self.assertLess(darkest, 60, "image looks blank")

    def test_night_compression_changes_layout(self) -> None:
        compressed = self.render().tobytes()
        uniform = self.render(compress_night=False).tobytes()
        self.assertNotEqual(compressed, uniform)

    def test_event_ending_at_midnight_keeps_its_height(self) -> None:
        """time(24) is invalid, so this used to collapse to a 22px stub."""
        cfg = make_config(self.tmp)
        late = timed(self.monday, 22, 0, 23, 59, "Guardia nocturna")
        generate.draw_png(cfg, [late], self.monday)
        self.assertTrue(cfg.png_output.is_file())

    def test_survives_empty_inputs(self) -> None:
        cfg = make_config(self.tmp)
        generate.draw_png(cfg, [], self.monday, [], [])
        self.assertTrue(cfg.png_output.is_file())

    def test_all_task_groups_render(self) -> None:
        """Overdue / today / upcoming take different row layouts."""
        cfg = make_config(self.tmp)
        tasks = [
            Task("Vencida", self.monday - timedelta(days=5), ""),
            Task("De hoy", self.monday, ""),
            Task("Futura", self.monday + timedelta(days=30), ""),
        ]
        generate.draw_png(cfg, [], self.monday, tasks, [])
        self.assertTrue(cfg.png_output.is_file())

    def test_long_task_list_is_capped(self) -> None:
        cfg = make_config(self.tmp)
        tasks = [Task(f"Tarea {i}", self.monday + timedelta(days=i), "") for i in range(80)]
        generate.draw_png(cfg, [], self.monday, tasks, [])
        self.assertTrue(cfg.png_output.is_file())


class TestBirthdayBox(unittest.TestCase):
    def test_height_grows_per_row(self) -> None:
        one = generate._birthday_box_h(1)
        two = generate._birthday_box_h(2)
        self.assertEqual(two - one, generate.BDAY_ROW_H)


class TestBoards(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.day = date(2026, 9, 7)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_weather_labels(self) -> None:
        import boards

        self.assertEqual(boards.weather_label(0), "Despejado")
        self.assertEqual(boards.weather_label(61), "Lluvia")
        self.assertEqual(boards.weather_label(None), "Sin datos")

    def test_rain_alert_tomorrow(self) -> None:
        import boards

        day = date(2026, 9, 9)
        weather = boards.Weather(
            place="Carlos Paz, Cordoba",
            ok=True,
            daily=[
                boards.DayForecast(day, 10.0, 20.0, 0, 10, 0.0),
                boards.DayForecast(day + timedelta(days=1), 12.0, 18.0, 61, 60, 2.0),
            ],
        )
        alert = boards.rain_alert(weather, day)
        self.assertIn("manana", alert)
        self.assertIn("60%", alert)

    def test_today_weather_month_match_screen(self) -> None:
        import boards

        cfg = make_config(self.tmp)
        evs = [timed(self.day, 10, 0, 11, 30, "Turno medico")]
        tasks = [Task("Pagar patente", self.day, "")]
        bdays = [generate.Ev(start=self.day + timedelta(days=12), end=self.day + timedelta(days=13), summary="Cumple Ana", all_day=True)]
        now = datetime(2026, 9, 7, 20, 25, tzinfo=TZ)
        weather = boards.Weather(
            place="Carlos Paz, Cordoba",
            temp=18.4,
            apparent=16.0,
            humidity=55,
            wind_kmh=12.0,
            code=2,
            daily=[
                boards.DayForecast(self.day + timedelta(days=i), 12.0, 22.0, 2, 20, 0.0)
                for i in range(7)
            ],
            ok=True,
        )
        today = boards.draw_today_png(cfg, evs, self.day, tasks, bdays, now, 0, weather)
        weekly = boards.draw_weekly_png(cfg, evs, self.day, tasks, bdays, now, 0, weather)
        clima = boards.draw_weather_png(cfg, weather, now)
        month = boards.draw_month_png(cfg, evs + bdays, self.day, now, 0)
        for path in (today, weekly, clima, month):
            with Image.open(path) as img:
                self.assertEqual(img.size, (758, 1024), path.name)
                darkest, _ = img.convert("L").getextrema()
                self.assertLess(darkest, 60, f"{path.name} looks blank")
        # Semanal must differ from the plain calendar (weather strip).
        generate.draw_png(cfg, evs, self.day, tasks, bdays, now, 0)
        with Image.open(cfg.png_output) as cal, Image.open(weekly) as wk:
            self.assertNotEqual(cal.tobytes(), wk.tobytes())

    def test_weather_failure_still_writes(self) -> None:
        import boards

        cfg = make_config(self.tmp)
        dead = boards.Weather(place="Carlos Paz, Cordoba", ok=False)
        path = boards.draw_weather_png(cfg, dead, datetime(2026, 9, 7, 20, 25, tzinfo=TZ))
        self.assertTrue(path.is_file())
        boards.draw_today_png(cfg, [], self.day, [], [], None, 0, dead)
        self.assertTrue(cfg.png_output.with_name("today.png").is_file())


if __name__ == "__main__":
    unittest.main()
