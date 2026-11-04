"""Builds the animated pictures on the README (docs/readme/*.svg).

    python tools/readme_art.py

One design system for every picture: same canvas, card, type and motion.
- Entrances play once, eased out, and stay put.
- Ambient motion loops with no seam: every loop ends in the state it starts in.
- GitHub shows these through <img>, so CSS and SMIL only: no scripts, no web fonts.
- prefers-reduced-motion freezes each picture on its first frame.

GitHub caches README images for a while. When a picture changes in a way people
must see right away, give it a new file name and update README.md.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "readme"
W = 1200

# Colours mirror ui/theme.py, so the README looks like the app.
INK, MUTED, SOFT = "#F1F5F7", "#93A4AE", "#C4D0D6"
CARD, CARD_HI, LINE, FREE = "#162029", "#1C2933", "#27353F", "#2A3843"
ICE, ICE2, OK, WARN, HOT, WARM, ON_ACCENT = ("#8ED8EE", "#B4E7F5", "#6FD08C", "#E9C04C",
                                             "#EF6F5E", "#F0B37E", "#0C2430")
FONT = '"Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif'
EASE_OUT = "cubic-bezier(.22,1,.36,1)"
EASE_IO = "cubic-bezier(.65,0,.35,1)"

FLAKE = ('<g id="flake" fill="none" stroke-linecap="round">'
         '<path d="M0-11V11M-9.5-5.5 9.5 5.5M-9.5 5.5 9.5-5.5" stroke-width="2.4"/>'
         '<path d="M-3-8 0-5 3-8M-3 8 0 5 3 8M-9.9-1.2-6.1-2.6-7.2-6.4M9.9 1.2 6.1 2.6 7.2 6.4'
         'M-9.9 1.2-6.1 2.6-7.2 6.4M9.9-1.2 6.1-2.6 7.2-6.4" stroke-width="1.6"/></g>')

BASE_CSS = f"""
text {{ font-family: {FONT}; }}
.in   {{ animation: in .9s {EASE_OUT} both; }}
.chip-in {{ animation: chipin .6s {EASE_OUT} both; }}
@keyframes in     {{ from {{ opacity: 0; transform: translateY(16px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes chipin {{ from {{ opacity: 0; transform: translateY(6px); }}  to {{ opacity: 1; transform: none; }} }}
.loop {{ animation-timing-function: {EASE_IO}; animation-iteration-count: infinite; }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
"""


def tw(s: str, px: float, caps: bool = False, spacing: float = 0) -> float:
    """Rough rendered width of a string in the font stack above."""
    return len(s) * (px * (.6 if caps else .53) + spacing)


def svg(h: int, label: str, title: str, css: str, body: str, defs: str = "") -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img" aria-label="{escape(label)}">
<title>{escape(title)}</title>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0D151B"/><stop offset="1" stop-color="#121D25"/></linearGradient>
  <radialGradient id="aura" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{ICE}" stop-opacity=".13"/><stop offset="1" stop-color="{ICE}" stop-opacity="0"/></radialGradient>
  <linearGradient id="card" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{CARD_HI}"/><stop offset="1" stop-color="{CARD}"/></linearGradient>
  <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".07"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <filter id="shadow" x="-10%" y="-20%" width="120%" height="150%"><feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#000" flood-opacity=".38"/></filter>
  <filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="10"/></filter>
  {FLAKE}
  {defs}
</defs>
<style>{BASE_CSS}{css}</style>
<rect width="{W}" height="{h}" rx="24" fill="url(#bg)"/>
<ellipse cx="180" cy="20" rx="560" ry="300" fill="url(#aura)"/>
<ellipse cx="1080" cy="{h}" rx="420" ry="220" fill="url(#aura)" opacity=".6"/>
<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="23.5" fill="none" stroke="{LINE}"/>
{body}
</svg>
"""


def heading(eyebrow: str, title: str, sub: str = "", x: int = 48, y: int = 54) -> str:
    sub_x = x + tw(title, 26) + 16
    return f"""<g class="in">
  <text x="{x}" y="{y}" fill="{ICE}" font-size="13" font-weight="700" letter-spacing="2.4">{escape(eyebrow)}</text>
  <text x="{x}" y="{y + 34}" fill="{INK}" font-size="26" font-weight="700">{escape(title)}</text>
  {f'<text x="{sub_x:.0f}" y="{y + 34}" fill="{MUTED}" font-size="15">{escape(sub)}</text>' if sub else ''}
</g>"""


def card(w: float, h: float, rx: int = 18) -> str:
    return (f'<rect width="{w}" height="{h}" rx="{rx}" fill="url(#card)" filter="url(#shadow)"/>'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{rx - .5}" fill="none" stroke="{LINE}"/>')


def chip(text: str, px: float = 14, pad: float = 24) -> tuple[str, float]:
    w = round(tw(text, px) + pad)
    return (f'<rect width="{w}" height="32" rx="16" fill="#111A21" stroke="{LINE}"/>'
            f'<text x="{w / 2}" y="21.5" text-anchor="middle" fill="{SOFT}" font-size="{px}">{escape(text)}</text>', w)


# ---------------------------------------------------------------- team cards
TEAM = [
    dict(ini="NG", name="Nassime Gharib", role="UI · VOICE · DEMO", color=ICE, grad=("#BDEBF7", "#4A7BD0"),
         sub="What you see and say", chips=["tray & gauge", "consent card", "push-to-talk", "demo video"]),
    dict(ini="AK", name="Aymane Idrissi Khamlichi", role="AGENT · AI SAFETY", color=OK, grad=("#CFF3DA", "#3B9E61"),
         sub="Plans every freeze, and can't be tricked",
         chips=["agent loop", "Muse Spark planner", "injection defense", "eval"]),
    dict(ini="YD", name="Yahya Dadsi", role="POLICY · SECURITY", color=WARN, grad=("#F8EBB8", "#C3931C"),
         sub="What must never freeze", chips=["deny list", "threat model", "red-team", "audit log"]),
    dict(ini="YB", name="Yassine Belaidi", role="SYSTEMS", color=WARM, grad=("#F9D9BA", "#D9604C"),
         sub="What freezes and thaws", chips=["actuator", "ledger", "watchdog", "pressure guardian"]),
]


def team() -> str:
    cw, ch, gap, x0, y0 = 548, 204, 24, 40, 116
    h = y0 + 2 * ch + gap + 40
    cycle = 2.4 * len(TEAM)          # each card takes a 2.4 s turn in the spotlight
    defs = [f'<clipPath id="cc"><rect width="{cw}" height="{ch}" rx="18"/></clipPath>']
    css = [f"""
.halo {{ transform-box: fill-box; transform-origin: center; animation: halo 5s {EASE_IO} infinite alternate; }}
@keyframes halo {{ from {{ transform: scale(1); opacity: .10; }} to {{ transform: scale(1.12); opacity: .22; }} }}
.ring {{ fill: none; stroke-width: 2.5; stroke-linecap: round; stroke-dasharray: 70 245;
         transform-box: fill-box; transform-origin: center; animation: spin 9s linear infinite; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.sheen {{ animation: sheen {cycle}s {EASE_IO} infinite; }}
@keyframes sheen {{ 0% {{ transform: translateX(0); }} 22% {{ transform: translateX({cw + 520}px); }} 100% {{ transform: translateX({cw + 520}px); }} }}
"""]
    body = [heading("THE TEAM", "Who built what", "four people, one 4 GB laptop")]
    for i, p in enumerate(TEAM):
        a, b = p["grad"]
        defs.append(f'<linearGradient id="av{i}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient>')
        defs.append(f'<linearGradient id="ac{i}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{p["color"]}"/><stop offset=".6" stop-color="{p["color"]}" stop-opacity=".25"/><stop offset="1" stop-color="{p["color"]}" stop-opacity="0"/></linearGradient>')
        css.append(f"""
.edge{i} {{ animation: edge{i} {cycle}s {EASE_IO} infinite; }}
@keyframes edge{i} {{ 0%,100% {{ stroke: {LINE}; }} 8%,16% {{ stroke: {p["color"]}; stroke-opacity: .7; }} 26% {{ stroke: {LINE}; stroke-opacity: 1; }} }}""")
        x = x0 + (i % 2) * (cw + gap)
        y = y0 + (i // 2) * (ch + gap)
        d = .15 + i * .12
        turn = 1.2 + i * 2.4
        role_w = tw(p["role"], 12, caps=True, spacing=1.6) + 24
        chips, cx = [], 28
        for j, c in enumerate(p["chips"]):
            g, w = chip(c)
            chips.append(f'<g transform="translate({cx} 150)"><g class="chip-in" style="animation-delay:{d + .4 + j * .07:.2f}s">{g}</g></g>')
            cx += w + 8
        assert cx - 8 <= cw - 28, (p["name"], cx)
        assert 150 + tw(p["name"], 26) <= cw - 24, p["name"]
        assert 150 + tw(p["sub"], 15.5) <= cw - 24, p["sub"]
        body.append(f"""
<!-- {escape(p["name"])} -->
<g transform="translate({x} {y})">
  <g class="in" style="animation-delay:{d:.2f}s">
    {card(cw, ch)}
    <rect class="edge{i}" style="animation-delay:{turn:.1f}s" x=".5" y=".5" width="{cw - 1}" height="{ch - 1}" rx="17.5" fill="none" stroke="{LINE}" stroke-width="1.5"/>
    <g clip-path="url(#cc)">
      <rect width="{cw}" height="3" fill="url(#ac{i})"/>
      <rect class="sheen" style="animation-delay:{turn:.1f}s" x="-300" y="0" width="240" height="{ch}" fill="url(#sheen)"/>
    </g>
    <g transform="translate(84 92)">
      <circle class="halo" style="animation-delay:-{i * 1.2:.1f}s" r="56" fill="{p["color"]}"/>
      <circle r="44" fill="url(#av{i})"/>
      <circle class="ring" style="animation-delay:-{i * 2.2:.1f}s" r="51" stroke="{p["color"]}"/>
      <text y="10" text-anchor="middle" fill="{ON_ACCENT}" font-size="28" font-weight="800">{p["ini"]}</text>
    </g>
    <g transform="translate(150 36)">
      <rect width="{role_w:.0f}" height="24" rx="12" fill="{p["color"]}" fill-opacity=".13"/>
      <text x="12" y="16.5" fill="{p["color"]}" font-size="12" font-weight="700" letter-spacing="1.6">{escape(p["role"])}</text>
    </g>
    <text x="150" y="96" fill="{INK}" font-size="26" font-weight="700">{escape(p["name"])}</text>
    <text x="150" y="122" fill="{MUTED}" font-size="15.5">{escape(p["sub"])}</text>
    {"".join(chips)}
  </g>
</g>""")
    label = "Team: " + "; ".join(f'{p["name"]}, {p["role"].title().replace(" · ", ", ")}' for p in TEAM)
    return svg(h, label, "The Focus Freeze team", "".join(css), "\n".join(body), "\n  ".join(defs))


# ---------------------------------------------------------------- hero banner
APPS = [  # (name, letter, colour, reason, freezes)
    ("Thesis.docx", "W", "#4A7BD0", "your task", False),
    ("Heat islands.pdf", "PDF", "#C9473B", "idle 40 min", False),
    ("Discord", "D", "#5865D9", "unrelated to thesis", True),
    ("Steam", "S", "#2A475E", "game launcher", True),
    ("Teams", "T", "#6264A7", "no meeting now", True),
    ("Slack", "S", "#4A154B", "background chat", True),
]


def kf(name: str, frames: dict[str, str]) -> str:
    return f"@keyframes {name} {{ " + " ".join(f"{k} {{ {v} }}" for k, v in frames.items()) + " }"


def hero() -> str:
    T = 12  # one loop: busy -> voice -> plan -> freeze -> calm -> "I'm done" -> thaw
    h = 460
    css = [f"""
.T {{ animation-duration: {T}s; }}
.bar  {{ transform-box: fill-box; transform-origin: left center; transform: scaleX(.9); fill: {HOT}; animation-name: bar; }}
.n90  {{ animation-name: n90; }} .n55 {{ opacity: 0; animation-name: n55; }}
.m1 {{ animation-name: m1; }} .m2, .m3, .m4 {{ opacity: 0; }}
.m2 {{ animation-name: m2; }} .m3 {{ animation-name: m3; }} .m4 {{ animation-name: m4; }}
.toast1 {{ opacity: 0; animation-name: toast1; }} .toast2 {{ opacity: 0; animation-name: toast2; }}
.tag  {{ opacity: 0; animation-name: tag; }}
.keep {{ opacity: 0; animation-name: keep; }} .idle {{ animation-name: idle; }}
.dim  {{ animation-name: dim; }}
.frost {{ opacity: 0; animation-name: frost; }}
.fl   {{ opacity: 0; transform-box: fill-box; transform-origin: center; animation-name: fl; }}
.wave rect {{ transform-box: fill-box; transform-origin: center; animation: wv 1s {EASE_IO} infinite; }}
.wave rect:nth-child(2) {{ animation-delay: .15s; }} .wave rect:nth-child(3) {{ animation-delay: .3s; }}
.wave rect:nth-child(4) {{ animation-delay: .45s; }} .wave rect:nth-child(5) {{ animation-delay: .6s; }}
@keyframes wv {{ 0%,100% {{ transform: scaleY(.35); }} 50% {{ transform: scaleY(1); }} }}
.mote {{ animation: mote 6s {EASE_IO} infinite alternate; }}
@keyframes mote {{ from {{ opacity: .1; transform: translateY(0); }} to {{ opacity: .8; transform: translateY(-10px); }} }}
""",
        kf("bar", {"0%,44%": f"transform: scaleX(.9); fill: {HOT};", "50%": f"fill: {WARN};",
                   "56%,82%": f"transform: scaleX(.55); fill: {OK};", "87%": f"fill: {WARN};",
                   "92%,100%": f"transform: scaleX(.9); fill: {HOT};"}),
        kf("n90", {"0%,44%": "opacity: 1; transform: none;", "49%": "opacity: 0; transform: translateY(-10px);",
                   "86%": "opacity: 0; transform: translateY(10px);", "91%,100%": "opacity: 1; transform: none;"}),
        kf("n55", {"0%,47%": "opacity: 0; transform: translateY(10px);", "53%,82%": "opacity: 1; transform: none;",
                   "87%,100%": "opacity: 0; transform: translateY(-10px);"}),
        kf("m1", {"0%,10%": "opacity: 1; transform: none;", "14%": "opacity: 0; transform: translateY(-6px);",
                  "96%": "opacity: 0; transform: translateY(6px);", "100%": "opacity: 1; transform: none;"}),
        kf("m2", {"0%,14%": "opacity: 0; transform: translateY(6px);", "18%,40%": "opacity: 1; transform: none;",
                  "44%,100%": "opacity: 0; transform: translateY(-6px);"}),
        kf("m3", {"0%,44%": "opacity: 0; transform: translateY(6px);", "48%,75%": "opacity: 1; transform: none;",
                  "79%,100%": "opacity: 0; transform: translateY(-6px);"}),
        kf("m4", {"0%,84%": "opacity: 0; transform: translateY(6px);", "88%,93%": "opacity: 1; transform: none;",
                  "97%,100%": "opacity: 0; transform: translateY(-6px);"}),
        kf("toast1", {"0%,12%": "opacity: 0; transform: translateY(8px);", "16%,29%": "opacity: 1; transform: none;",
                      "33%,100%": "opacity: 0; transform: translateY(8px);"}),
        kf("toast2", {"0%,75%": "opacity: 0; transform: translateY(8px);", "79%,86%": "opacity: 1; transform: none;",
                      "90%,100%": "opacity: 0; transform: translateY(8px);"}),
        kf("tag", {"0%,24%": "opacity: 0;", "29%,41%": "opacity: 1;", "46%,100%": "opacity: 0;"}),
        kf("keep", {"0%,24%": "opacity: 0;", "29%,84%": "opacity: 1;", "89%,100%": "opacity: 0;"}),
        kf("idle", {"0%,24%": "opacity: 1;", "29%,84%": "opacity: 0;", "89%,100%": "opacity: 1;"}),
        kf("dim", {"0%,43%": "opacity: 1;", "50%,82%": "opacity: .4;", "89%,100%": "opacity: 1;"}),
        kf("frost", {"0%,43%": "opacity: 0;", "50%,82%": "opacity: 1;", "89%,100%": "opacity: 0;"}),
        kf("fl", {"0%,43%": "opacity: 0; transform: scale(.5) rotate(-40deg);",
                  "51%,82%": "opacity: 1; transform: scale(1) rotate(0);",
                  "89%,100%": "opacity: 0; transform: scale(.5) rotate(40deg);"}),
    ]
    defs = f"""<linearGradient id="frostg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{ICE2}" stop-opacity=".42"/><stop offset=".55" stop-color="{ICE}" stop-opacity=".14"/><stop offset="1" stop-color="{ICE2}" stop-opacity=".36"/></linearGradient>
  <clipPath id="win"><rect width="560" height="388" rx="16"/></clipPath>"""

    def L(cls: str, delay: float = 0) -> str:
        return f'class="{cls} T loop"' + (f' style="animation-delay:{delay:.2f}s"' if delay else "")

    msgs = [("m1", HOT, "RAM at 90%. Everything stutters."),
            ("m2", WARN, "Muse Spark: 4 apps to freeze, 2 to keep"),
            ("m3", ICE, "Frozen. RAM paged to disk, windows open"),
            ("m4", WARM, "Thawed, each app right where you left it")]
    status = "".join(f'<g {L(c)}><circle cx="22" cy="24" r="5" fill="{col}"/><text x="38" y="29.5" fill="{INK}" font-size="16.5">{escape(t)}</text></g>'
                     for c, col, t in msgs)
    tiles = []
    fz = 0
    for k, (name, letter, col, reason, freezes) in enumerate(APPS):
        tx, ty = 14 + (k % 3) * 182, 100 + (k // 3) * 118
        d = fz * .12
        icon = f'<rect x="14" y="14" width="34" height="34" rx="9" fill="{col}"/><text x="31" y="37" text-anchor="middle" fill="{INK}" font-size="{14 if len(letter) > 1 else 17}" font-weight="700">{letter}</text>'
        if name.endswith(".pdf"):
            meta = (f'<text {L("idle")} x="14" y="92" fill="{MUTED}" font-size="13">{reason}</text>'
                    f'<text {L("keep")} x="14" y="92" fill="{ICE}" font-size="13" font-weight="700">AI keeps it: your source</text>')
        else:
            meta = f'<text x="14" y="92" fill="{MUTED}" font-size="13">{reason}</text>'
        inner = (f'<rect width="168" height="104" rx="12" fill="{CARD_HI}" stroke="{LINE}"/>{icon}'
                 f'<text x="14" y="72" fill="{INK}" font-size="16" font-weight="600">{escape(name)}</text>{meta}')
        if freezes:
            tiles.append(f"""<g transform="translate({tx} {ty})">
      <g {L("dim", d)}>{inner}</g>
      <rect {L("frost", d)} width="168" height="104" rx="12" fill="url(#frostg)" stroke="{ICE}" stroke-width="1.5"/>
      <g transform="translate(140 30)"><use {L("fl", d)} href="#flake" stroke="{ICE2}"/></g>
      <g {L("tag", d)}><rect x="100" y="14" width="56" height="22" rx="11" fill="{ICE}" fill-opacity=".1" stroke="{ICE}" stroke-dasharray="4 3"/><text x="128" y="29" text-anchor="middle" fill="{ICE}" font-size="12">freeze</text></g>
    </g>""")
            fz += 1
        else:
            tiles.append(f'<g transform="translate({tx} {ty})">{inner}</g>')

    body = f"""
<g fill="{ICE2}">
  <circle class="mote" cx="96" cy="70" r="2"/><circle class="mote" style="animation-delay:-2s" cx="520" cy="96" r="1.6"/>
  <circle class="mote" style="animation-delay:-4s" cx="452" cy="404" r="2.2"/><circle class="mote" style="animation-delay:-1s" cx="60" cy="350" r="1.4"/>
</g>

<g transform="translate(56 0)"><g class="in">
  <g transform="translate(0 52)">
    <rect width="{tw('META GLOBAL AI DEV HACKATHON · 2026', 11.5, True, 1.4) + 24:.0f}" height="26" rx="13" fill="{ICE}" fill-opacity=".1" stroke="{ICE}" stroke-opacity=".35"/>
    <text x="12" y="17.5" fill="{ICE}" font-size="11.5" font-weight="700" letter-spacing="1.4">META GLOBAL AI DEV HACKATHON · 2026</text>
  </g>
  <use href="#flake" stroke="{ICE}" transform="translate(24 140) scale(1.9)"/>
  <text x="62" y="160" fill="{INK}" font-size="56" font-weight="700" letter-spacing="-1">Focus Freeze</text>
  <text x="0" y="208" fill="{MUTED}" font-size="20.5">Tell it what you're working on.</text>
  <text x="0" y="238" fill="{MUTED}" font-size="20.5">It freezes the apps you don't need,</text>
  <text x="0" y="268" fill="{MUTED}" font-size="20.5">and thaws them, state intact, when you're done.</text>
  <g transform="translate(0 300)">
    <rect width="468" height="48" rx="12" fill="url(#card)" stroke="{LINE}"/>
    {status}
  </g>
  <g transform="translate(0 376)" font-size="13">
    <rect width="148" height="28" rx="14" fill="#111A21" stroke="{LINE}"/><circle cx="16" cy="14" r="4" fill="{ICE}"/><text x="28" y="18.5" fill="{SOFT}">muse-spark-1.3</text>
    <rect x="158" width="214" height="28" rx="14" fill="#111A21" stroke="{LINE}"/><circle cx="174" cy="14" r="4" fill="{ICE}"/><text x="186" y="18.5" fill="{SOFT}">muse-voice-transcribe-1.0</text>
  </g>
</g></g>

<g transform="translate(600 36)">
  <g class="in" style="animation-delay:.15s">
    {card(560, 388, 16)}
    <g clip-path="url(#win)">
      <rect width="560" height="36" fill="#1E2B35"/>
      <circle cx="22" cy="18" r="5" fill="{LINE}"/><circle cx="38" cy="18" r="5" fill="{LINE}"/><circle cx="54" cy="18" r="5" fill="{LINE}"/>
      <text x="280" y="23" text-anchor="middle" fill="{MUTED}" font-size="13.5">4 GB laptop · a normal day</text>
      <g transform="translate(14 56)">
        <text x="0" y="16" fill="{MUTED}" font-size="15">Memory</text>
        <rect x="76" y="4" width="390" height="16" rx="8" fill="{FREE}"/>
        <rect {L("bar")} x="76" y="4" width="390" height="16" rx="8"/>
        <g font-size="22" font-weight="700" text-anchor="end">
          <text {L("n90")} x="532" y="21" fill="{HOT}">90%</text>
          <text {L("n55")} x="532" y="21" fill="{OK}">55%</text>
        </g>
      </g>
      {"".join(tiles)}
    </g>
    <g transform="translate(280 352)">
      <g {L("toast1")}>
        <rect x="-150" y="-17" width="300" height="34" rx="17" fill="{ICE}"/>
        <g class="wave" transform="translate(-128 -9)" fill="{ON_ACCENT}"><rect width="3.5" height="18" rx="1.75"/><rect x="7" width="3.5" height="18" rx="1.75"/><rect x="14" width="3.5" height="18" rx="1.75"/><rect x="21" width="3.5" height="18" rx="1.75"/><rect x="28" width="3.5" height="18" rx="1.75"/></g>
        <text x="14" y="5.5" text-anchor="middle" fill="{ON_ACCENT}" font-size="15" font-weight="600">“I'm writing my thesis.”</text>
      </g>
      <g {L("toast2")}>
        <rect x="-96" y="-17" width="192" height="34" rx="17" fill="{WARM}"/>
        <g class="wave" transform="translate(-76 -9)" fill="{ON_ACCENT}"><rect width="3.5" height="18" rx="1.75"/><rect x="7" width="3.5" height="18" rx="1.75"/><rect x="14" width="3.5" height="18" rx="1.75"/><rect x="21" width="3.5" height="18" rx="1.75"/><rect x="28" width="3.5" height="18" rx="1.75"/></g>
        <text x="20" y="5.5" text-anchor="middle" fill="{ON_ACCENT}" font-size="15" font-weight="600">“I'm done.”</text>
      </g>
    </g>
  </g>
</g>"""
    return svg(h, "Focus Freeze: tell it your task, it freezes the apps you don't need (RAM 90% to 55%), "
                  "then thaws them when you're done", "Focus Freeze", "".join(css), body, defs)


# ---------------------------------------------------------------- pipeline
NODES = [  # (title, line 1, line 2, icon)
    ("Planner", "Muse Spark 1.3", "a reason per app", "spark"),
    ("Policy", "deny list runs after", "the model, and wins", "shield"),
    ("You say yes", "consent card,", "untick anything", "check"),
    ("Freeze", "suspend + page", "RAM to disk", "flake"),
    ("Audit log", "every action,", "tamper-evident", "log"),
]
ICONS = {
    "spark": f'<path d="M0-10C1 -3 3-1 10 0 3 1 1 3 0 10-1 3-3 1-10 0-3-1-1-3 0-10Z" fill="{ICE}"/>',
    "shield": f'<path d="M0-10 8-7V-1C8 5 4 8 0 10-4 8-8 5-8-1V-7Z" fill="none" stroke="{ICE}" stroke-width="2"/><path d="M-3.5 0-.5 3 4-2" stroke="{ICE}" stroke-width="2" fill="none" stroke-linecap="round"/>',
    "check": f'<circle r="9" fill="none" stroke="{ICE}" stroke-width="2"/><path d="M-4 0-1 3 4-3" stroke="{ICE}" stroke-width="2.2" fill="none" stroke-linecap="round"/>',
    "flake": f'<use href="#flake" stroke="{ICE}" transform="scale(.8)"/>',
    "log": f'<path d="M-7-6H7M-7 0H7M-7 6H3" stroke="{ICE}" stroke-width="2.2" stroke-linecap="round"/>',
}


def pipeline() -> str:
    h = 380
    nx0, nw, ngap, ny, nh = 240, 156, 32, 126, 132
    cy = ny + nh / 2
    curve, run = 50, (nx0 + 5 * nw + 4 * ngap) - nx0
    speed = (curve + run) / 6.0
    css = [f"""
.glow {{ opacity: 0; animation: glow 3s {EASE_IO} infinite; }}
@keyframes glow {{ 0% {{ opacity: 0; }} 6%,28% {{ opacity: 1; }} 44%,100% {{ opacity: 0; }} }}
.flow {{ stroke-dasharray: 2 12; animation: dash 1.4s linear infinite; }}
@keyframes dash {{ to {{ stroke-dashoffset: -28; }} }}
.wave rect {{ transform-box: fill-box; transform-origin: center; animation: wv 1s {EASE_IO} infinite; }}
.wave rect:nth-child(2) {{ animation-delay: .15s; }} .wave rect:nth-child(3) {{ animation-delay: .3s; }}
.wave rect:nth-child(4) {{ animation-delay: .45s; }} .wave rect:nth-child(5) {{ animation-delay: .6s; }}
@keyframes wv {{ 0%,100% {{ transform: scaleY(.35); }} 50% {{ transform: scaleY(1); }} }}
.breathe {{ animation: breathe 2.4s {EASE_IO} infinite alternate; }}
@keyframes breathe {{ from {{ opacity: .35; }} to {{ opacity: 1; }} }}
"""]
    vy, sy = 154, 230
    p_voice = f"M200 {vy} C222 {vy} 218 {cy} {nx0} {cy} H{nx0 + run}"
    p_sensor = f"M200 {sy} C222 {sy} 218 {cy} {nx0} {cy} H{nx0 + run}"
    nodes = []
    for j, (title, l1, l2, icon) in enumerate(NODES):
        x = nx0 + j * (nw + ngap)
        t_in = (curve + x - nx0) / speed - .05
        nodes.append(f"""<g transform="translate({x} {ny})">
    <g class="in" style="animation-delay:{.3 + j * .1:.2f}s">
      <rect class="glow" style="animation-delay:{t_in:.2f}s" x="-6" y="-6" width="{nw + 12}" height="{nh + 12}" rx="22" fill="{ICE}" fill-opacity=".22" filter="url(#blur)"/>
      {card(nw, nh, 16)}
      <rect class="glow" style="animation-delay:{t_in:.2f}s" x=".75" y=".75" width="{nw - 1.5}" height="{nh - 1.5}" rx="15.25" fill="none" stroke="{ICE}" stroke-width="1.5"/>
      <g transform="translate(36 36)"><circle r="20" fill="{ICE}" fill-opacity=".12"/>{ICONS[icon]}</g>
      <text x="18" y="82" fill="{INK}" font-size="17" font-weight="700">{escape(title)}</text>
      <text x="18" y="102" fill="{MUTED}" font-size="13.5">{escape(l1)}</text>
      <text x="18" y="120" fill="{MUTED}" font-size="13.5">{escape(l2)}</text>
    </g>
  </g>""")
    dot = lambda path, begin: f"""<g>
    <circle r="12" fill="{ICE}" opacity=".25" filter="url(#blur)"/><circle r="5" fill="{ICE2}"/>
    <animateMotion dur="6s" begin="{begin}" repeatCount="indefinite" path="{path}"/>
    <animate attributeName="opacity" dur="6s" begin="{begin}" repeatCount="indefinite" values="0;1;1;0" keyTimes="0;.04;.94;1"/>
  </g>"""
    inputs = f"""
  <g transform="translate(40 124)"><g class="in" style="animation-delay:.2s">
    {card(160, 60, 14)}
    <g class="wave" transform="translate(18 21)" fill="{ICE}"><rect width="4" height="18" rx="2"/><rect x="8" width="4" height="18" rx="2"/><rect x="16" width="4" height="18" rx="2"/><rect x="24" width="4" height="18" rx="2"/><rect x="32" width="4" height="18" rx="2"/></g>
    <text x="64" y="28" fill="{INK}" font-size="16" font-weight="700">Voice</text>
    <text x="64" y="46" fill="{MUTED}" font-size="12.5">Muse Voice</text>
  </g></g>
  <g transform="translate(40 200)"><g class="in" style="animation-delay:.25s">
    {card(160, 60, 14)}
    <g transform="translate(18 17)" fill="none" stroke="{MUTED}" stroke-width="2"><rect width="34" height="26" rx="4"/><path d="M0 7H34"/></g>
    <text x="64" y="28" fill="{INK}" font-size="16" font-weight="700">Sensor</text>
    <text x="64" y="46" fill="{MUTED}" font-size="12.5">open windows</text>
  </g></g>"""
    body = f"""{heading("HOW IT WORKS", "Nothing freezes without your yes")}
<g fill="none" stroke-width="2">
  <path d="{p_voice}" stroke="{LINE}"/><path d="{p_sensor}" stroke="{LINE}"/>
  <path class="flow" d="{p_voice}" stroke="{ICE}" stroke-opacity=".5" stroke-linecap="round"/>
  <path class="flow" d="{p_sensor}" stroke="{ICE}" stroke-opacity=".5" stroke-linecap="round"/>
</g>
{dot(p_voice, "0s")}
{dot(p_sensor, "3s")}
{inputs}
{"".join(nodes)}
<g class="in" style="animation-delay:.9s" font-size="15">
  <circle class="breathe" cx="{nx0 + 6}" cy="309" r="5" fill="{WARM}"/>
  <text x="{nx0 + 20}" y="314" fill="{MUTED}"><tspan fill="{INK}" font-weight="600">Watchdog.</tspan> If the app crashes, a separate process thaws everything.</text>
  <circle class="breathe" style="animation-delay:-1.2s" cx="{nx0 + 6}" cy="339" r="5" fill="{ICE}"/>
  <text x="{nx0 + 20}" y="344" fill="{MUTED}"><tspan fill="{INK}" font-weight="600">“I'm done.”</tspan> Every frozen app thaws, state intact.</text>
</g>"""
    return svg(h, "How it works: voice and the window sensor feed the Muse Spark planner, then the policy deny list, "
                  "then your consent, then the freeze, and every action goes to a tamper-evident log",
               "How Focus Freeze works", "".join(css), body)


# ---------------------------------------------------------------- results
BARS = [  # (label, sub, share, value, colour)
    ("Focus Freeze", "Muse Spark 1.3", 1.0, "88 / 88", ICE),
    ("Keyword table", "", .66, "66%", "#A5B4BD"),
    ("Idle timer", "", .57, "57%", WARM),
]


def results() -> str:
    h = 340
    bx, bw = 250, 560
    css = [f"""
.grow {{ transform-box: fill-box; transform-origin: left center; animation: grow 1.4s {EASE_OUT} both; }}
@keyframes grow {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
.val {{ animation: val .7s {EASE_OUT} both; }}
@keyframes val {{ from {{ opacity: 0; transform: translateX(-8px); }} to {{ opacity: 1; transform: none; }} }}
.sheen2 {{ animation: sheen2 5s {EASE_IO} infinite; }}
@keyframes sheen2 {{ 0% {{ transform: translateX(0); }} 30% {{ transform: translateX({bw + 200}px); }} 100% {{ transform: translateX({bw + 200}px); }} }}
.halo {{ transform-box: fill-box; transform-origin: center; animation: halo 2.6s {EASE_IO} infinite alternate; }}
@keyframes halo {{ from {{ transform: scale(1); opacity: .12; }} to {{ transform: scale(1.25); opacity: .28; }} }}
"""]
    rows = []
    for i, (label, sub, share, value, col) in enumerate(BARS):
        y = 132 + i * 62
        w = round(bw * share)
        d = .35 + i * .15
        sheen = (f'<g clip-path="url(#b0)"><rect class="sheen2" style="animation-delay:{d + 1.6:.2f}s" x="{bx - 120}" y="{y}" width="100" height="22" fill="#fff" fill-opacity=".35"/></g>'
                 if i == 0 else "")
        rows.append(f"""<g class="in" style="animation-delay:{d - .2:.2f}s">
  <text x="48" y="{y + 16}" fill="{INK}" font-size="17" font-weight="600">{escape(label)}</text>
  {f'<text x="48" y="{y + 36}" fill="{MUTED}" font-size="13">{escape(sub)}</text>' if sub else ''}
  <rect x="{bx}" y="{y}" width="{bw}" height="22" rx="11" fill="{FREE}"/>
</g>
<rect class="grow" style="animation-delay:{d:.2f}s" x="{bx}" y="{y}" width="{w}" height="22" rx="11" fill="{col}"/>
{sheen}
<text class="val" style="animation-delay:{d + 1:.2f}s" x="{bx + w + 16}" y="{y + 18}" fill="{col}" font-size="20" font-weight="700">{value}</text>""")
    defs = (f'<clipPath id="b0"><rect x="{bx}" y="132" width="{bw}" height="22" rx="11"/></clipPath>'
            f'<linearGradient id="sh2" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".6"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    rows[0] = rows[0].replace('fill="#fff" fill-opacity=".35"', 'fill="url(#sh2)"')
    body = f"""{heading("RESULTS", "Which apps does your task need?", "blind test set, never tuned on")}
{"".join(rows)}
<g transform="translate(916 112)"><g class="in" style="animation-delay:.6s">
  {card(244, 96, 16)}
  <g transform="translate(40 48)">
    <circle class="halo" r="24" fill="{OK}"/>
    <path d="M0-15 12-10V-2C12 7 6 12 0 15-6 12-12 7-12-2V-10Z" fill="{OK}" fill-opacity=".18" stroke="{OK}" stroke-width="2"/>
    <path d="M-5 0-1 4 6-4" stroke="{OK}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
  </g>
  <text x="80" y="48" fill="{OK}" font-size="28" font-weight="700">0 / 270</text>
  <text x="80" y="72" fill="{MUTED}" font-size="13.5">unsafe freezes, attack runs</text>
</g></g>
<g transform="translate(916 222)"><g class="in" style="animation-delay:.75s">
  {card(244, 96, 16)}
  <g transform="translate(40 48)"><circle class="halo" style="animation-delay:-1.3s" r="24" fill="{ICE}"/><text y="8" text-anchor="middle" fill="{ICE}" font-size="22" font-weight="700">$</text></g>
  <text x="80" y="48" fill="{INK}" font-size="28" font-weight="700">~$0.002</text>
  <text x="80" y="72" fill="{MUTED}" font-size="13.5">per plan</text>
</g></g>"""
    return svg(h, "Results: Focus Freeze gets 88 of 88 on the blind test set, a keyword table 66% and an idle timer 57%; "
                  "0 unsafe freezes in 270 attack runs; about $0.002 per plan",
               "Focus Freeze results", "".join(css), body, defs)


PICTURES = {"banner.svg": hero, "flow.svg": pipeline, "numbers.svg": results, "team-cards.svg": team}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in PICTURES.items():
        (OUT / name).write_text(build(), encoding="utf-8", newline="\n")
        print(f"wrote docs/readme/{name}")
