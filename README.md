# The Daily Globe — 26 November 2026

[![news-image-20261126](https://make.fun/badge/news-image-20261126.svg)](https://make.fun/bounty/news-image-20261126)
[![rank](https://make.fun/badge/news-image-20261126/maknying/news-image-20261126/rank.svg)](https://make.fun/bounty/news-image-20261126)
[![reward](https://make.fun/badge/news-image-20261126/maknying/news-image-20261126/reward.svg)](https://make.fun/bounty/news-image-20261126)

A one-page newspaper that sums up 26 November 2026 in a single image:
45 stories across 7 regions, plus a "day in numbers" strip. Built for the
[news-image-20261126 bounty](https://make.fun/bounty/news-image-20261126).

## What is on the page

- **Masthead** — *The Daily Globe*, Thursday 26 November 2026.
- **Lead story** — the US announces Section 301 tariffs on 14 trading
  partners: 20% on China, 15% on the EU.
- **The day in numbers** — 14 economies hit, 20% top tariff rate, 259
  Democratic House seats, 432,519 Russian troop losses in 2026, Brent
  crude at $91.40, and a 36% garment pay rise in Bangladesh.
- **Four columns, 44 more stories** — USA (9), Europe (6),
  Russia–Ukraine (6), China (6), Indonesia (6), Middle East (6) and
  World (5). Every fact — names, dates, figures — was checked against
  reporting published 24–26 November 2026 (see `SOURCES.md` in the
  parent directory; stories whose figures could not be verified were
  dropped rather than guessed).

## How it is made

`main.py` is plain Python 3.13 with no third-party packages and no
network access. It reads the glyph bitmaps from `atlas.bin`, lays out
the newspaper page on a 1024×1024 canvas, and writes its own PNG
encoder output — so the same command always produces the same bytes.

```sh
python3 main.py
# writes entry.png (1024×1024) to $MAKEFUN_OUTPUT_DIR, or ./out/entry.png
```

Run it twice and the two files are byte-identical; the PNG stays well
under the 1 MiB limit.

## Checking the output

```sh
python3 main.py && cp out/entry.png /tmp/a.png
python3 main.py && cp out/entry.png /tmp/b.png
sha256sum /tmp/a.png /tmp/b.png   # the two hashes must match
```

The PNG is 1024×1024 and well under 1 MiB. Count the stories on the
page — it must be exactly 45:

| Section | Stories |
| --- | --- |
| Lead | 1 |
| USA | 9 |
| Europe | 6 |
| Russia–Ukraine | 6 |
| China | 6 |
| Indonesia | 6 |
| Middle East | 6 |
| World | 5 |

## Files

| File | Purpose |
| --- | --- |
| `main.py` | The whole renderer: atlas reader, page layout, PNG writer |
| `atlas.bin` | Prebuilt bitmap font atlas (9 faces) the renderer reads |
| `LICENSE` | MIT licence |

## Licence

MIT — see `LICENSE`.
