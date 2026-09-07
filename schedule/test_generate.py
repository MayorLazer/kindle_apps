"""Smoke tests for the weekly PNG layout.

Run with:  python -m unittest discover -s schedule

The layout math (compressed night rows, piecewise time->pixel mapping, overlap
lanes) has no visual regression test on the Kindle, so these guard the parts
that silently produce a wrong-looking calendar.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta
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


if __name__ == "__main__":
    unittest.main()
