"""Config, schedule math, and color conversion. No Wayland code here."""

import math
import os
import re
import time as _time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cosmic-nightlight"
CONFIG_FILE = CONFIG_DIR / "config.toml"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "cosmic-nightlight"
MODE_FILE = STATE_DIR / "mode"
PREVIEW_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "cosmic-nightlight.preview"
MODES = ("auto", "on", "off")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

DEFAULT_CONFIG = """\
# cosmic-nightlight settings. Run `nightlight reload` after editing by hand.

# How red the screen gets at night: 0 is barely warm, 100 is very red.
warmth = 50

# Night window in 24-hour local time. It may cross midnight.
start = "22:00"
end = "08:00"

# Minutes to fade in after `start` and fade out before `end`.
fade_minutes = 30

# Changes for the night that begins on a given day.
# Keys are mon tue wed thu fri sat sun; give start, end, or both.
[days]
thu = { start = "23:00" }
"""


@dataclass
class Config:
    warmth: int = 50
    start: time = time(22, 0)
    end: time = time(8, 0)
    fade_minutes: int = 30
    days: dict = field(default_factory=dict)   # weekday 0-6 -> (start, end)

    @property
    def temperature(self):
        """Kelvin: 4500 at warmth 0 down to 2000 at warmth 100."""
        return 4500 - 25 * self.warmth

    @property
    def strength(self):
        """Overlay opacity: 0.15 at warmth 0 up to 0.6 at warmth 100."""
        return 0.15 + 0.0045 * self.warmth

    def window(self, day):
        """(start, end) datetimes of the night that begins on `day`."""
        start, end = self.days.get(day.weekday(), (self.start, self.end))
        s = datetime.combine(day, start)
        e = datetime.combine(day, end)
        if e <= s:
            e += timedelta(days=1)
        return s, e


def _parse_time(s):
    h, m = s.split(":")
    return time(int(h), int(m))


def load_config():
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(DEFAULT_CONFIG)
    data = tomllib.loads(CONFIG_FILE.read_text())
    cfg = Config()
    cfg.warmth = int(max(0, min(100, data.get("warmth", cfg.warmth))))
    cfg.start = _parse_time(data.get("start", "22:00"))
    cfg.end = _parse_time(data.get("end", "08:00"))
    cfg.fade_minutes = int(max(0, data.get("fade_minutes", cfg.fade_minutes)))
    for key, override in data.get("days", {}).items():
        if key not in DAYS:
            raise ValueError(f"unknown day {key!r} in [days]; use one of {', '.join(DAYS)}")
        cfg.days[DAYS.index(key)] = (
            _parse_time(override.get("start", f"{cfg.start:%H:%M}")),
            _parse_time(override.get("end", f"{cfg.end:%H:%M}")),
        )
    return cfg


def set_warmth(value):
    """Change `warmth` in the config file, keeping comments and layout."""
    value = int(max(0, min(100, value)))
    load_config()   # creates the file if needed
    text = CONFIG_FILE.read_text()
    line = f"warmth = {value}"
    text, n = re.subn(r"(?m)^warmth\s*=.*$", line, text, count=1)
    if n == 0:
        text = line + "\n" + text
    CONFIG_FILE.write_text(text)
    return value


def read_mode():
    try:
        mode = MODE_FILE.read_text().strip()
    except FileNotFoundError:
        return "auto"
    return mode if mode in MODES else "auto"


def write_mode(mode):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MODE_FILE.write_text(mode + "\n")


def preview_until():
    """Unix time until which full strength is forced, or 0."""
    try:
        return float(PREVIEW_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return 0.0


def start_preview(seconds):
    PREVIEW_FILE.write_text(str(_time.time() + seconds))


def _level_in(now, start, end, fade):
    if not (start <= now < end):
        return 0.0
    if fade.total_seconds() == 0:
        return 1.0
    fade = min(fade, (end - start) / 2)
    return max(0.0, min((now - start) / fade, (end - now) / fade, 1.0))


def night_level(cfg, now=None):
    """0.0 during the day, 1.0 at full night, ramping during fades."""
    now = now or datetime.now()
    fade = timedelta(minutes=cfg.fade_minutes)
    # The night that began yesterday may still be running this morning.
    return max(_level_in(now, *cfg.window(now.date() - timedelta(days=d)), fade) for d in (1, 0))


def kelvin_to_rgb(kelvin):
    """Approximate white point of a black body (Tanner Helland's fit)."""
    t = kelvin / 100
    if t <= 66:
        r = 255
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
    if t >= 66:
        b = 255
    elif t <= 19:
        b = 0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307
    return tuple(max(0.0, min(255.0, c)) for c in (r, g, b))


def tint_for(temperature, alpha):
    """Overlay color that pulls white as close to `temperature` as alpha allows.

    Alpha blending gives out = a*c + (1-a)*src. For src = white we want
    out = target, so c = 255 - (255 - target) / a, clamped to 0-255.
    """
    if alpha <= 0:
        return (0, 0, 0)
    target = kelvin_to_rgb(temperature)
    return tuple(max(0.0, min(255.0, 255 - (255 - t) / alpha)) for t in target)
