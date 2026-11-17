"""PNG scorecard images drawn with the standard library only (no Pillow needed).

Text uses the embedded DejaVu bitmap font in `_font_data.py`. `render_scorecard_png`
takes a plain "view" dictionary (see `bot.scorecard_view`) and returns PNG bytes.
"""

from __future__ import annotations

import base64
import struct
import zlib

from ._font_data import FONT_DATA

WIDTH = 1040
MARGIN = 30

BG = (13, 20, 36)
PANEL = (22, 33, 56)
ROW_A = (27, 40, 66)
ROW_B = (22, 33, 56)
TEXT = (236, 241, 250)
MUTED = (140, 156, 184)
GOLD = (255, 200, 64)
GREEN = (72, 205, 130)
RED = (240, 88, 88)
BLUE = (72, 156, 255)
ORANGE = (255, 150, 66)
PURPLE = (176, 120, 255)
ACCENTS = (BLUE, ORANGE, PURPLE, PURPLE)


class Font:
    """A decoded bitmap font (one weight and size)."""

    _cache: dict[str, "Font"] = {}

    def __init__(self, key: str):
        data = FONT_DATA[key]
        self.ascent = data["ascent"]
        self.line = data["line"]
        self.glyphs = data["glyphs"]
        self.blob = zlib.decompress(base64.b64decode(data["blob"]))

    @classmethod
    def get(cls, key: str) -> "Font":
        if key not in cls._cache:
            cls._cache[key] = cls(key)
        return cls._cache[key]

    def glyph(self, char: str) -> list:
        return self.glyphs.get(ord(char)) or self.glyphs[ord("?")]

    def width(self, text: str) -> float:
        return sum(self.glyph(char)[0] for char in text)

    def fit(self, text: str, max_width: float) -> str:
        if self.width(text) <= max_width:
            return text
        while text and self.width(text + "...") > max_width:
            text = text[:-1]
        return text + "..."


class Canvas:
    """An RGB canvas. In `dry` mode nothing is drawn; only the layout is measured."""

    def __init__(self, width: int, height: int, background=BG, dry: bool = False):
        self.width = width
        self.height = height
        self.dry = dry
        self.pixels = None if dry else bytearray(bytes(background) * (width * height))

    def rect(self, x: int, y: int, w: int, h: int, color) -> None:
        if self.dry:
            return
        x0, x1 = max(0, int(x)), min(self.width, int(x + w))
        y0, y1 = max(0, int(y)), min(self.height, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            start = (yy * self.width + x0) * 3
            self.pixels[start:start + len(row)] = row

    def text(self, x: float, y: float, text: str, font_key: str, color, align: str = "l",
             max_width: float | None = None) -> float:
        font = Font.get(font_key)
        if max_width is not None:
            text = font.fit(text, max_width)
        width = font.width(text)
        if align == "r":
            x -= width
        elif align == "c":
            x -= width / 2
        if self.dry:
            return width
        red, green, blue = color
        baseline = int(y) + font.ascent
        pen = x
        pixels, blob = self.pixels, font.blob
        for char in text:
            advance, left, top, glyph_w, glyph_h, offset = font.glyph(char)
            if glyph_w:
                gx = int(round(pen + left))
                gy = baseline + top
                for row in range(glyph_h):
                    py = gy + row
                    if py < 0 or py >= self.height:
                        continue
                    source = offset + row * glyph_w
                    index = (py * self.width + gx) * 3
                    for col in range(glyph_w):
                        alpha = blob[source + col]
                        px = gx + col
                        if alpha and 0 <= px < self.width:
                            i = index + col * 3
                            if alpha == 255:
                                pixels[i] = red
                                pixels[i + 1] = green
                                pixels[i + 2] = blue
                            else:
                                inverse = 255 - alpha
                                pixels[i] = (pixels[i] * inverse + red * alpha) // 255
                                pixels[i + 1] = (pixels[i + 1] * inverse + green * alpha) // 255
                                pixels[i + 2] = (pixels[i + 2] * inverse + blue * alpha) // 255
            pen += advance
        return width

    def to_png(self) -> bytes:
        stride = self.width * 3
        raw = bytearray()
        for row in range(self.height):
            raw.append(0)
            raw += self.pixels[row * stride:(row + 1) * stride]

        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b"")
        )


def _overs(balls: int) -> str:
    return f"{balls // 6}.{balls % 6}"


def _strike_rate(runs: int, balls: int) -> str:
    return f"{runs * 100 / balls:.1f}" if balls else "-"


def _economy(runs: int, balls: int) -> str:
    return f"{runs * 6 / balls:.2f}" if balls else "-"


def _draw_header(canvas: Canvas, view: dict, y: int) -> int:
    canvas.rect(0, y, WIDTH, 168, PANEL)
    canvas.rect(0, y, WIDTH, 6, GOLD)
    canvas.text(MARGIN, y + 22, view["title"].upper(), "b36", TEXT, max_width=WIDTH - 2 * MARGIN - 150)
    status = view.get("status", "")
    if status:
        color = RED if status == "LIVE" else GREEN
        width = Font.get("b16").width(status) + 28
        canvas.rect(WIDTH - MARGIN - width, y + 28, width, 30, color)
        canvas.text(WIDTH - MARGIN - width / 2, y + 33, status, "b16", BG, align="c")
    if view.get("subtitle"):
        canvas.text(MARGIN, y + 76, view["subtitle"], "r16", MUTED, max_width=WIDTH - 2 * MARGIN)
    if view.get("result"):
        canvas.text(MARGIN, y + 112, view["result"], "b22", GOLD, max_width=WIDTH - 2 * MARGIN)
    return y + 168 + 18


def _draw_innings(canvas: Canvas, innings: dict, index: int, y: int) -> int:
    accent = ACCENTS[min(index, len(ACCENTS) - 1)]
    left, right = MARGIN, WIDTH - MARGIN

    # Title bar: label, team and score.
    canvas.rect(left, y, right - left, 56, accent)
    canvas.text(left + 16, y + 8, innings["label"], "r13", BG)
    canvas.text(left + 16, y + 24, innings["team"].upper(), "b22", BG, max_width=520)
    score = f"{innings['score']}/{innings['wickets']}"
    canvas.text(right - 16, y + 6, score, "b36", BG, align="r")
    detail = f"{_overs(innings['balls'])}/{innings['overs_limit']} ov"
    if innings["balls"]:
        detail += f"   RR {innings['score'] * 6 / innings['balls']:.2f}"
    canvas.text(right - 16 - Font.get("b36").width(score) - 18, y + 30, detail, "r16", BG, align="r")
    y += 56

    # Batting table.
    canvas.rect(left, y, right - left, 28, PANEL)
    canvas.text(left + 14, y + 6, "BATTING", "b13", MUTED)
    for edge, label in ((760, "R"), (830, "B"), (890, "4s"), (950, "6s"), (1000, "SR")):
        canvas.text(edge, y + 6, label, "b13", MUTED, align="r")
    y += 28
    for row_number, batter in enumerate(innings["batters"]):
        canvas.rect(left, y, right - left, 28, ROW_A if row_number % 2 == 0 else ROW_B)
        not_out = not batter["out"]
        name_color = GREEN if not_out else TEXT
        name = batter["name"] + ("*" if not_out else "")
        canvas.text(left + 14, y + 5, name, "b16", name_color, max_width=300)
        status = batter.get("how_out") or ("not out" if not_out else "out")
        canvas.text(350, y + 6, status, "r13", MUTED, max_width=370)
        runs_color = GOLD if batter["runs"] >= 50 else TEXT
        canvas.text(760, y + 5, str(batter["runs"]), "b16", runs_color, align="r")
        canvas.text(830, y + 6, str(batter["balls"]), "r16", TEXT, align="r")
        canvas.text(890, y + 6, str(batter["fours"]), "r16", TEXT, align="r")
        canvas.text(950, y + 6, str(batter["sixes"]), "r16", TEXT, align="r")
        canvas.text(1000, y + 6, _strike_rate(batter["runs"], batter["balls"]), "r13", MUTED, align="r")
        y += 28
    extras = innings.get("extras") or {}
    extras_total = sum(extras.values())
    canvas.rect(left, y, right - left, 28, ROW_A)
    canvas.text(left + 14, y + 5, "Extras", "b16", MUTED)
    parts = [f"{label} {extras[key]}" for key, label in (("wd", "wd"), ("nb", "nb"), ("b", "b")) if extras.get(key)]
    canvas.text(350, y + 6, ", ".join(parts), "r13", MUTED)
    canvas.text(760, y + 5, str(extras_total), "b16", TEXT, align="r")
    y += 28
    if innings.get("did_not_bat"):
        canvas.text(left + 14, y + 6, "Did not bat: " + ", ".join(innings["did_not_bat"]), "r13", MUTED, max_width=right - left - 28)
        y += 26
    y += 8

    # Bowling table.
    canvas.rect(left, y, right - left, 28, PANEL)
    canvas.text(left + 14, y + 6, "BOWLING", "b13", MUTED)
    for edge, label in ((560, "O"), (650, "R"), (740, "W"), (850, "ECON")):
        canvas.text(edge, y + 6, label, "b13", MUTED, align="r")
    y += 28
    for row_number, bowler in enumerate(innings["bowlers"]):
        canvas.rect(left, y, right - left, 28, ROW_A if row_number % 2 == 0 else ROW_B)
        canvas.text(left + 14, y + 5, bowler["name"], "b16", TEXT, max_width=400)
        canvas.text(560, y + 6, _overs(bowler["balls"]), "r16", TEXT, align="r")
        canvas.text(650, y + 6, str(bowler["runs"]), "r16", TEXT, align="r")
        wicket_color = GOLD if bowler["wickets"] >= 3 else TEXT
        canvas.text(740, y + 5, str(bowler["wickets"]), "b16", wicket_color, align="r")
        canvas.text(850, y + 6, _economy(bowler["runs"], bowler["balls"]), "r13", MUTED, align="r")
        y += 28
    if not innings["bowlers"]:
        canvas.text(left + 14, y + 6, "No balls bowled yet", "r13", MUTED)
        y += 28
    y += 8

    # Fall of wickets.
    if innings.get("fow"):
        text = "Fall of wickets: " + ", ".join(
            f"{item['score']}-{item['wicket']} ({item['batter']})" for item in innings["fow"]
        )
        canvas.text(left + 14, y + 2, text, "r13", MUTED, max_width=right - left - 28)
        y += 26

    # Runs per over mini chart.
    over_log = innings.get("over_log") or []
    if over_log:
        chart_h = 78
        canvas.rect(left, y, right - left, chart_h + 34, PANEL)
        canvas.text(left + 14, y + 6, "RUNS PER OVER", "b13", MUTED)
        slots = max(innings["overs_limit"], len(over_log))
        slot_w = (right - left - 28) / slots
        top = max(12, max(item["runs"] for item in over_log))
        baseline = y + 24 + chart_h
        for number, item in enumerate(over_log):
            bar_h = max(2, int(chart_h * item["runs"] / top))
            x = left + 14 + number * slot_w
            canvas.rect(x + 3, baseline - bar_h, max(4, slot_w - 6), bar_h, accent)
            if item.get("wickets"):
                canvas.rect(x + 3, baseline - bar_h - 6, max(4, slot_w - 6), 5, RED)
            if slot_w >= 22:
                canvas.text(x + slot_w / 2, baseline + 4, str(number + 1), "r13", MUTED, align="c")
        y += chart_h + 34
    return y + 22


def _draw_awards(canvas: Canvas, awards: list[str], y: int) -> int:
    if not awards:
        return y
    canvas.rect(MARGIN, y, WIDTH - 2 * MARGIN, 34 + 28 * len(awards), PANEL)
    canvas.rect(MARGIN, y, 6, 34 + 28 * len(awards), GOLD)
    canvas.text(MARGIN + 20, y + 8, "MATCH AWARDS", "b16", GOLD)
    for number, line in enumerate(awards):
        canvas.text(MARGIN + 20, y + 36 + number * 28, line, "r16", TEXT, max_width=WIDTH - 2 * MARGIN - 40)
    return y + 34 + 28 * len(awards) + 22


def _layout(canvas: Canvas, view: dict) -> int:
    y = _draw_header(canvas, view, 0)
    for index, innings in enumerate(view["innings"]):
        y = _draw_innings(canvas, innings, index, y)
    y = _draw_awards(canvas, view.get("awards") or [], y)
    canvas.text(WIDTH / 2, y + 2, view.get("footer", "Cricket Simulator Bot"), "r13", MUTED, align="c")
    return y + 40


def render_scorecard_png(view: dict) -> bytes:
    """Draw the scorecard and return it as PNG bytes."""
    height = _layout(Canvas(WIDTH, 10, dry=True), view)
    canvas = Canvas(WIDTH, height)
    _layout(canvas, view)
    return canvas.to_png()
