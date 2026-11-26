#!/usr/bin/env python3
"""The Daily Globe — 26 November 2026, one-page newspaper image.

Renders 45 verified news stories (lead + 7 regions) plus a numbers band
into a single 1024x1024 PNG, using only the Python standard library and
the prebuilt glyph atlas in atlas.bin. No network access. Deterministic:
two runs produce byte-identical output.
"""

import os
import struct
import sys
import zlib

PAGE_W = 1024
PAGE_H = 1024
PAPER = (250, 246, 236)
INK = (24, 22, 20)
RED = (158, 28, 22)
GREY = (110, 105, 96)
RULE = (40, 36, 32)

ATLAS_MAGIC = b"GLYF1\x00\x00\x00"


# ---------------------------------------------------------------- atlas

class GlyphSet:
    """One bitmap font from atlas.bin: codepoint -> (adv, bx, by, w, h, off, n)."""

    def __init__(self, name, px, glyphs):
        self.name = name
        self.px = px
        self.glyphs = glyphs
        # Cap height proxy: the tallest bearing_y in the set (capitals sit
        # this far below the top of their bitmap; the baseline is that far
        # below the top of the em box).
        self.ascent = max(g[2] for g in glyphs.values())

    def width_of(self, text):
        total = 0
        for ch in text:
            g = self.glyphs.get(ord(ch))
            if g is not None:
                total += g[0]
        return total


def load_atlas(path):
    """Parse the GLYF1 container; returns (dict name -> GlyphSet, bitmap blob)."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:8] != ATLAS_MAGIC:
        raise ValueError("atlas.bin: bad magic")
    (nsets,) = struct.unpack_from("<I", blob, 8)
    pos = 12
    fonts = {}
    for _ in range(nsets):
        nlen = blob[pos]
        pos += 1
        name = blob[pos:pos + nlen].decode("ascii")
        pos += nlen
        px, nglyph = struct.unpack_from("<HH", blob, pos)
        pos += 4
        glyphs = {}
        for _ in range(nglyph):
            cp, adv, bx, by, w, h, off, n = struct.unpack_from("<IhhhHHII", blob, pos)
            pos += 22
            glyphs[cp] = (adv, bx, by, w, h, off, n)
        fonts[name] = GlyphSet(name, px, glyphs)
    return fonts, blob[pos:]


# ---------------------------------------------------------------- canvas

class Sheet:
    """An RGB raster page with simple filled-rect and glyph painting."""

    def __init__(self, w, h, colour):
        self.w = w
        self.h = h
        self.px = bytearray(colour * (w * h))

    def fill_rect(self, x, y, w, h, colour):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        r, g, b = colour
        for yy in range(y0, y1):
            base = (yy * self.w + x0) * 3
            span = (x1 - x0) * 3
            self.px[base:base + span] = bytes((r, g, b)) * (x1 - x0)

    def rule(self, x, y, w, thick, colour=RULE):
        self.fill_rect(x, y, w, thick, colour)

    def stamp(self, font, bitmap, text, x, baseline, colour):
        """Paint text with its baseline at (x, baseline); returns width painted.
        A glyph's bitmap top sits bearing_y pixels above the baseline."""
        cx = x
        for ch in text:
            g = font.glyphs.get(ord(ch))
            if g is None:
                continue
            adv, bx, by, gw, gh, off, n = g
            if gw and gh:
                for row in range(gh):
                    dy = baseline - by + row
                    if dy < 0 or dy >= self.h:
                        continue
                    src = bitmap[off + row * gw: off + (row + 1) * gw]
                    for col in range(gw):
                        a = src[col]
                        if not a:
                            continue
                        dx = cx + bx + col
                        if dx < 0 or dx >= self.w:
                            continue
                        i = (dy * self.w + dx) * 3
                        if a == 255:
                            self.px[i] = colour[0]
                            self.px[i + 1] = colour[1]
                            self.px[i + 2] = colour[2]
                        else:
                            inv = 255 - a
                            self.px[i] = (colour[0] * a + self.px[i] * inv) // 255
                            self.px[i + 1] = (colour[1] * a + self.px[i + 1] * inv) // 255
                            self.px[i + 2] = (colour[2] * a + self.px[i + 2] * inv) // 255
            cx += adv
        return cx - x

    def stamp_centred(self, font, bitmap, text, cx, baseline, colour):
        w = font.width_of(text)
        self.stamp(font, bitmap, text, cx - w // 2, baseline, colour)

    def text_top(self, font, bitmap, text, x, top, colour):
        """Paint text with the top of its em box at y=top."""
        return self.stamp(font, bitmap, text, x, top + font.ascent, colour)

    def text_top_centred(self, font, bitmap, text, cx, top, colour):
        w = font.width_of(text)
        return self.text_top(font, bitmap, text, cx - w // 2, top, colour)


# ---------------------------------------------------------------- text flow

def split_lines(font, text, max_w, max_lines=None):
    """Greedy word wrap; returns a list of lines (hard-truncated with …)."""
    words = text.split(" ")
    lines = []
    cur = ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if font.width_of(trial) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            if font.width_of(word) > max_w:  # single long word: chop it
                chunk = ""
                for ch in word:
                    if font.width_of(chunk + ch) > max_w:
                        lines.append(chunk)
                        chunk = ch
                    else:
                        chunk += ch
                cur = chunk
            else:
                cur = word
    if cur:
        lines.append(cur)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and font.width_of(last + "…") > max_w:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return lines


# ---------------------------------------------------------------- png out

def _chunk(kind, payload):
    out = struct.pack(">I", len(payload)) + kind + payload
    return out + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def write_png(sheet, path):
    raw = bytearray()
    stride = sheet.w * 3
    for yy in range(sheet.h):
        raw.append(0)
        raw += sheet.px[yy * stride:(yy + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", sheet.w, sheet.h, 8, 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n"
    data += _chunk(b"IHDR", ihdr)
    data += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    data += _chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# ---------------------------------------------------------------- content

LEAD_HEADLINE = "Trump hits 14 partners with new tariffs"
LEAD_DECK = (
    "China faces 20% and the EU 15% under the Section 301 excess-capacity "
    "probe, announced by USTR Jamieson Greer. The levies, which could take "
    "effect in January, revive the trade agenda the Supreme Court struck down."
)
LEAD_SOURCE = "Sources: Reuters, AP, CNN — 25 Nov 2026"

NUMBERS = [
    ("14", "partners hit by new US tariffs"),
    ("20%", "top tariff rate, on China"),
    ("259", "Democrats' House seats"),
    ("432,519", "Russian troop losses in 2026"),
    ("$91.40", "Brent crude, Tuesday close"),
    ("36%", "Bangladesh garment pay rise"),
]

# (region, headline, deck) — facts taken from SOURCES.md, wording my own.
STORIES = [
    ("USA", "Wall Street rout eases at close", "Nasdaq -0.62%, S&P 500 -0.25%, Dow +0.33%."),
    ("USA", "Nvidia falls 3.9% again", "S&P puts its debt on CreditWatch."),
    ("USA", "Democrats clinch House, 259 seats", "Largest majority since 1990."),
    ("USA", "Abrego Garcia leaves for Spain", "Hopes to return after Trump."),
    ("USA", "Army blows up 5 tons of lead azide", "Iowa blast called a success."),
    ("USA", "Macy's parade pushed to Saturday", "High winds force postponement."),
    ("USA", "Steelers release Aaron Rodgers", "QB, 42, cut after McCarthy row."),
    ("USA", "30-year mortgage eases to 7.21%", "Near the 2026 high."),
    ("USA", "Anthropic ends below IPO price", "Shares close under $83."),
    ("EUROPE", "Rutte meets Trump at Mar-a-Lago", "NATO chief urges max pressure."),
    ("EUROPE", "Poland sets no-fly zone at border", "After repeated Russian incursions."),
    ("EUROPE", "Germany Q3 growth cut to 0.1%", "Exports fell 1.0%."),
    ("EUROPE", "Poundland collapses; 12,000 jobs at risk", "600 UK and Irish stores hit."),
    ("EUROPE", "Von der Leyen: 100 chapters on track", "EU enlargement push in Brussels."),
    ("EUROPE", "Eurostar strike cancels 3 trains", "Paris walkout hits London route."),
    ("RUSSIA–UKRAINE", "Ukraine hits air base; 5 jets damaged", "MiG-31s and Su-34s knocked out."),
    ("RUSSIA–UKRAINE", "Zelenskyy: US delays Patriot missiles", "Four shipments held since Sept."),
    ("RUSSIA–UKRAINE", "Russian strikes cut power in 5 regions", "DTEK plant halts generation."),
    ("RUSSIA–UKRAINE", "Two Libyan officers die of wounds", "After Benghazi drone attack."),
    ("RUSSIA–UKRAINE", "Russia's 2026 losses hit record", "432,519 casualties, Kyiv says."),
    ("RUSSIA–UKRAINE", "US guarantees need Congress nod", "And Russia's approval, plan says."),
    ("CHINA", "Shenzhou-24 lifts off with Pakistani", "First foreigner aboard Tiangong."),
    ("CHINA", "Wang Yi presses Dutch on Nexperia", "Urges fair climate for firms."),
    ("CHINA", "Minerals export-ban pause extended", "Gallium curbs eased to 27 Jan."),
    ("CHINA", "PBOC lines up 800bn yuan MLF", "Net withdrawal of 200bn yuan."),
    ("CHINA", "China hits back at EU car curbs", "Vows to defend hybrid makers."),
    ("CHINA", "China plans digital-economy law", "2026–30 plan eyes data flows."),
    ("INDONESIA", "Eight bodies found in flooded mine", "18 miners still trapped in Bogor."),
    ("INDONESIA", "Airlangga: trade deal shields exports", "Signed pact caps US tariffs."),
    ("INDONESIA", "Prabowo summons Danantara, Garuda", "Two-hour talks on turnaround."),
    ("INDONESIA", "Prabowo names two VP candidates", "Amran, Sugiono put to MPR."),
    ("INDONESIA", "Rupiah slides to 18,295 per dollar", "Early European trading on 25 Nov."),
    ("INDONESIA", "Teacher incentive may rise to Rp1m", "Minister proposes jump from Rp400k."),
    ("MID-EAST", "Houthis claim Ras Tanura strike", "Fires reported at Saudi refinery."),
    ("MID-EAST", "Two tankers hit mines in Hormuz", "IRGC says vessels caught fire."),
    ("MID-EAST", "Hamas security chief killed in Gaza", "Strike hits Gaza City flat."),
    ("MID-EAST", "Saudi coalition strikes Hodeidah", "Port hit after Riyadh attack."),
    ("MID-EAST", "Iraq forces enter militia stronghold", "Kataib Hezbollah base raided."),
    ("MID-EAST", "Iran flogs singer Parastoo Ahmadi", "74 lashes for show without hijab."),
    ("WORLD", "RSF drones kill 19 in Sudan", "Blue Nile state attacks wound 20."),
    ("WORLD", "Bangladesh raises garment pay 36%", "Weeks of protests win rise."),
    ("WORLD", "Colombia frees supermarket hostages", "One captor killed in storming."),
    ("WORLD", "Egypt tanker fire kills 30", "Blaze on Cairo ring road."),
    ("WORLD", "Malaysia sues Google for $146m", "YouTube content row."),
]

# Column plan: balance the 44 region stories across four columns.
COLUMNS = [
    STORIES[0:11],    # USA 9 + Europe 2
    STORIES[11:21],   # Europe 4 + Russia–Ukraine 6
    STORIES[21:33],   # China 6 + Indonesia 6
    STORIES[33:44],   # Mid-East 6 + World 5
]

FOOTER = ("THE DAILY GLOBE — 26 NOVEMBER 2026 — SOURCES: REUTERS, AP, CNN, "
          "XINHUA, BLOOMBERG, ISW, JUST SECURITY")


# ---------------------------------------------------------------- layout

def build_page(fonts, bitmap):
    page = Sheet(PAGE_W, PAGE_H, PAPER)
    mast = fonts["serifb54"]
    lead_font = fonts["serifb30"]
    big_num = fonts["sansb26"]
    bold12 = fonts["sansb12"]
    bold11 = fonts["sansb11"]
    reg12 = fonts["sans12"]
    reg11 = fonts["sans11"]

    margin = 26
    inner = PAGE_W - 2 * margin
    cx_mid = PAGE_W // 2

    # --- masthead
    y = 22
    page.rule(margin, y, inner, 3)
    y += 8
    page.text_top_centred(mast, bitmap, "THE DAILY GLOBE", cx_mid, y, INK)
    y += 62
    page.rule(margin, y, inner, 1)
    y += 6
    page.text_top_centred(
        bold12, bitmap,
        "THURSDAY 26 NOVEMBER 2026   |   THE WORLD IN ONE PAGE   |   45 STORIES • 7 REGIONS",
        cx_mid, y, INK)
    y += 20
    page.rule(margin, y, inner, 3)
    y += 10

    # --- lead story
    page.text_top(bold11, bitmap, "LEAD  —  TRADE WAR RETURNS", margin, y, RED)
    y += 17
    for line in split_lines(lead_font, LEAD_HEADLINE, inner, 2):
        page.text_top(lead_font, bitmap, line, margin, y, INK)
        y += 36
    y += 2
    for line in split_lines(reg12, LEAD_DECK, inner, 2):
        page.text_top(reg12, bitmap, line, margin, y, INK)
        y += 16
    page.text_top(reg11, bitmap, LEAD_SOURCE, margin, y, GREY)
    y += 20
    page.rule(margin, y, inner, 2)
    y += 8

    # --- the day in numbers
    page.text_top(bold11, bitmap, "THE DAY IN NUMBERS", margin, y, RED)
    y += 16
    cell_w = inner // len(NUMBERS)
    num_top = y
    for i, (figure, label) in enumerate(NUMBERS):
        x = margin + i * cell_w
        if i:
            page.fill_rect(x - 1, num_top, 1, 44, (200, 192, 178))
        page.text_top_centred(big_num, bitmap, figure, x + cell_w // 2, num_top, RED)
        lab_y = num_top + 30
        for line in split_lines(reg11, label, cell_w - 12, 2):
            page.text_top_centred(reg11, bitmap, line, x + cell_w // 2, lab_y, INK)
            lab_y += 13
    y = num_top + 56
    page.rule(margin, y, inner, 2)
    y += 10

    # --- four columns of region stories
    gutter = 14
    col_w = (inner - 3 * gutter) // 4
    top = y
    bottom = PAGE_H - 34
    for ci, column in enumerate(COLUMNS):
        x = margin + ci * (col_w + gutter)
        cy = top
        for region, headline, deck in column:
            page.text_top(bold11, bitmap, region, x, cy, RED)
            cy += 12
            for line in split_lines(bold12, headline, col_w, 2):
                page.text_top(bold12, bitmap, line, x, cy, INK)
                cy += 14
            for line in split_lines(reg11, deck, col_w, 2):
                page.text_top(reg11, bitmap, line, x, cy, INK)
                cy += 12
            cy += 4
            if cy < bottom - 6:
                page.fill_rect(x, cy, col_w, 1, (214, 206, 192))
            cy += 4
        # column divider
        if ci < 3:
            page.fill_rect(x + col_w + gutter // 2 - 1, top, 1,
                           bottom - top, (214, 206, 192))

    # --- footer
    page.rule(margin, PAGE_H - 30, inner, 2)
    page.text_top_centred(reg11, bitmap, FOOTER, cx_mid, PAGE_H - 22, GREY)
    return page


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    fonts, bitmap = load_atlas(os.path.join(here, "atlas.bin"))
    page = build_page(fonts, bitmap)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or os.path.join(here, "out")
    out_path = os.path.join(out_dir, "entry.png")
    write_png(page, out_path)
    print(out_path)


if __name__ == "__main__":
    main()
