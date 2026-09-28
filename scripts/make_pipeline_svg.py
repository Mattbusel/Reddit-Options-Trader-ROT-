"""Draw docs/img/pipeline-{light,dark}.svg: the stages PipelineRunner.run_once() runs.

The stage list and the rules in each box come from src/rot/app/runner.py,
trend/trend_engine.py, market/gates.py and market/trade_builder.py. The counts
are what `python examples/demo.py` printed for its second pass; pass them in
with --counts if the demo output changes.

    python scripts/make_pipeline_svg.py
"""
from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'Cascadia Mono',Consolas,Menlo,monospace"
THEMES = {
    "light": dict(bg="#F7F7F4", card="#FFFFFF", ink="#16181D", ink2="#44474F", muted="#6B6E76",
                  rule="#D5D6D0", acc="#E4572E", acc2="#1F7A8C", ok="#2E7D32", dot="#E4572E"),
    "dark": dict(bg="#0F1115", card="#171A21", ink="#ECEDEF", ink2="#B8BBC2", muted="#8C9099",
                 rule="#2C313B", acc="#FF7A4D", acc2="#4FB3C8", ok="#6CC070", dot="#FF7A4D"),
}
W = 900

STAGES = [
    ("1", "Ingest", "Reddit (PRAW) + RSS feeds", "posts"),
    ("2", "Trend", "upvotes/s + 2 x comments/s >= 0.01", "trending"),
    ("3", "Tickers (NLP)", "$cashtags, bare tickers, aliases", "with a ticker"),
    ("4", "Event", "type, stance, horizon", "events"),
    ("5", "Validate + enrich", "real ticker? price, market cap", "priced"),
    ("6", "Credibility", "flair, subreddit, votes, pump words", "scored 0 to 1"),
    ("7", "Suppress", "categories with a poor track record", "kept"),
    ("8", "Reason (LLM)", "OpenAI / Anthropic / DeepSeek, or stub", "reasoned"),
    ("9", "Trade idea", "spread / straddle, or a reason not to", "records, {trades} with legs"),
]


def text(x, y, s, t, size=16, fill=None, family=SANS, anchor="start", weight=400):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'fill="{fill or t["ink"]}" text-anchor="{anchor}" font-weight="{weight}">{escape(s)}</text>')


def draw(theme: str, counts: list[int], trades: int) -> str:
    t = THEMES[theme]
    cw, ch, gx, gy, x0, y0 = 256, 118, 26, 40, 44, 120
    rows = 3
    H = y0 + rows * ch + (rows - 1) * gy + 170
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">',
         '<title id="t">How ROT turns a Reddit post into an options trade idea</title>',
         '<desc id="d">Nine stages run by PipelineRunner: ingest, trend, tickers, event, validate and enrich, '
         'credibility, suppress, reason, trade idea. Each box shows how many of the demo\'s 5 sample posts '
         'reached it on the second pass.</desc>',
         f'<rect width="{W}" height="{H}" rx="14" fill="{t["bg"]}"/>',
         text(x0, 56, "From a Reddit post to an options trade idea", t, size=27, weight=700),
         text(x0, 88, "The nine stages in PipelineRunner.run_once(). Numbers: the demo's 5 sample posts.",
              t, size=17, fill=t["ink2"])]
    centers = []
    for i, (num, name, rule, unit) in enumerate(STAGES):
        r, c = divmod(i, 3)
        if r % 2 == 1:
            c = 2 - c                       # snake: row 2 runs right to left
        x, y = x0 + c * (cw + gx), y0 + r * (ch + gy)
        centers.append((x + cw / 2, y + ch / 2, x, y))
        s.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="10" fill="{t["card"]}" stroke="{t["rule"]}"/>')
        s.append(f'<circle cx="{x + 26}" cy="{y + 28}" r="14" fill="{t["acc2"]}"/>')
        s.append(text(x + 26, y + 33, num, t, size=15, fill=t["card"], anchor="middle", weight=700))
        s.append(text(x + 50, y + 34, name, t, size=19, weight=700))
        s.append(text(x + 16, y + 64, rule, t, size=14, fill=t["ink2"]))
        n = counts[i]
        unit = unit.format(trades=trades)
        s.append(text(x + 16, y + 100, str(n), t, size=26, family=MONO, fill=t["acc"], weight=700))
        s.append(text(x + 16 + 20 * len(str(n)) + 4, y + 99, unit, t, size=15, fill=t["muted"]))
    # connectors and a moving dot along the snake
    path = []
    for i, (cx, cy, x, y) in enumerate(centers):
        path.append(("M" if i == 0 else "L") + f"{cx:.1f},{cy:.1f}")
    d = " ".join(path)
    s.insert(5, f'<path d="{d}" fill="none" stroke="{t["rule"]}" stroke-width="3" stroke-dasharray="2 6" stroke-linecap="round"/>')
    s.append(f'<circle r="7" fill="{t["dot"]}"><animateMotion dur="9s" repeatCount="indefinite" path="{d}"/></circle>')
    fy = y0 + rows * ch + (rows - 1) * gy + 40
    s.append(text(x0, fy, "Why the demo's three events end with no trade:", t, size=17, weight=700))
    for k, line in enumerate(["Earnings rumours are clamped to confidence 0.25, below the 0.30 bar.",
                              "An unknown stance never trades, and weekends block every trade.",
                              "Stub reasoning (no LLM key) keeps the heuristic confidence."]):
        s.append(text(x0, fy + 28 + 24 * k, line, t, size=16, fill=t["ink2"]))
    s.append(text(x0, fy + 108, "Rules from market/trade_builder.py and market/gates.py. Research only, not financial advice.",
                  t, size=14, fill=t["muted"]))
    s.append("</svg>")
    return "\n".join(s)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counts", default="5,4,3,3,3,3,3,3,3",
                    help="posts reaching each of the 9 stages (demo pass 2)")
    ap.add_argument("--trades", type=int, default=0, help="trade ideas with option legs")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "img")
    a = ap.parse_args()
    counts = [int(v) for v in a.counts.split(",")]
    assert len(counts) == 9
    a.out.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (a.out / f"pipeline-{theme}.svg").write_text(draw(theme, counts, a.trades), encoding="utf-8")
    print(f"wrote pipeline-light.svg and pipeline-dark.svg to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
