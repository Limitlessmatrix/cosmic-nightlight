"""nightlight: blue-light filter for the COSMIC desktop.

Usage:
  nightlight run                 start the overlay daemon (systemd does this)
  nightlight on | off | auto     force on, force off, or follow the schedule
  nightlight toggle              flip between on and off
  nightlight warmth [0-100]      show or set how red it gets
  nightlight settings            open the settings window with the warmth slider
  nightlight reload              re-read the config file
  nightlight status              show mode, schedule, and current level
  nightlight preview [SECONDS]   show full-strength tint briefly (default 10)
"""

import os
import select
import signal
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from . import schedule as sch

PID_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "cosmic-nightlight.pid"
TRANSITION_SECONDS = 2.0   # smooth fade when switching modes by hand
FRAME = 1 / 30


def target_level(cfg, mode):
    if time.time() < sch.preview_until():
        return 1.0
    if mode == "on":
        return 1.0
    if mode == "off":
        return 0.0
    return sch.night_level(cfg)


def run():
    from .overlay import OverlayManager

    mgr = OverlayManager()
    PID_FILE.write_text(str(os.getpid()))

    reload_r, reload_w = os.pipe()
    os.set_blocking(reload_w, False)
    signal.signal(signal.SIGUSR1, lambda *_: os.write(reload_w, b"x"))
    signal.signal(signal.SIGTERM, lambda *_: os.write(reload_w, b"q"))

    cfg, mode = sch.load_config(), sch.read_mode()
    level = 0.0             # what is on screen now, 0.0-1.0
    anim = None             # (from_level, start_time) during a manual transition
    shown = None            # (level, warmth) last drawn

    def apply(lvl):
        alpha = cfg.strength * lvl
        mgr.set_tint(sch.tint_for(cfg.temperature, alpha), alpha)

    try:
        while True:
            goal = target_level(cfg, mode)
            if anim:
                frm, t0 = anim
                p = min(1.0, (time.monotonic() - t0) / TRANSITION_SECONDS)
                new = frm + (goal - frm) * p
                if p >= 1.0:
                    anim = None
            else:
                new = goal
            if (shown is None or abs(new - shown[0]) > 0.002
                    or (new == 0.0) != (shown[0] == 0.0) or cfg.warmth != shown[1]):
                level = new
                apply(level)
                shown = (level, cfg.warmth)

            # Wake fast while animating, otherwise twice a minute is plenty
            # (a 30-minute fade changes under 2% per 30 seconds).
            timeout = FRAME if anim else 30
            remaining = sch.preview_until() - time.time()
            if remaining > 0:
                timeout = min(timeout, remaining + 0.05)
            ready, _, _ = select.select([mgr, reload_r], [], [], timeout)
            if mgr in ready:
                mgr.dispatch()
            if reload_r in ready:
                cmds = os.read(reload_r, 64)
                if b"q" in cmds:
                    break
                try:
                    cfg = sch.load_config()
                except Exception as e:   # keep running on a bad edit
                    print(f"config not reloaded: {e}", file=sys.stderr)
                mode = sch.read_mode()
                if target_level(cfg, mode) != level:
                    anim = (level, time.monotonic())
            elif anim is None and level != target_level(cfg, mode) and remaining > -1:
                # A preview just ended: fade back instead of snapping.
                anim = (level, time.monotonic())
    finally:
        mgr.set_tint((0, 0, 0), 0.0)
        mgr.conn.roundtrip()
        PID_FILE.unlink(missing_ok=True)


def notify_daemon(quiet=False):
    try:
        os.kill(int(PID_FILE.read_text()), signal.SIGUSR1)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError):
        if not quiet:
            print("The nightlight daemon isn't running. Start it with:\n"
                  "  systemctl --user start cosmic-nightlight", file=sys.stderr)
        return False


def daemon_running():
    try:
        os.kill(int(PID_FILE.read_text()), 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False


def describe_schedule(cfg):
    """One line per distinct night window, e.g. 'Thu: 23:00 to 08:00'."""
    monday = date(2026, 1, 5)
    lines = []
    for i, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        s, e = cfg.window(monday + timedelta(days=i))
        lines.append((name, f"{s:%H:%M} to {e:%H:%M}"))
    default = f"{cfg.start:%H:%M} to {cfg.end:%H:%M}"
    out = [f"every night {default}"]
    out += [f"{name} night {span}" for name, span in lines if span != default]
    return out


def status():
    cfg, mode = sch.load_config(), sch.read_mode()
    lvl = target_level(cfg, mode)
    print(f"daemon:      {'running' if daemon_running() else 'not running'}")
    print(f"mode:        {mode}")
    sched = describe_schedule(cfg)
    print(f"schedule:    {sched[0]}, {cfg.fade_minutes} min fades")
    for extra in sched[1:]:
        print(f"             except {extra}")
    print(f"warmth:      {cfg.warmth} of 100")
    print(f"right now:   {lvl * 100:.0f}% of full night")
    print(f"config:      {sch.CONFIG_FILE}")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "run":
        run()
    elif cmd in sch.MODES:
        sch.write_mode(cmd)
        notify_daemon()
    elif cmd == "toggle":
        cfg = sch.load_config()
        active = target_level(cfg, sch.read_mode()) > 0
        sch.write_mode("off" if active else "on")
        notify_daemon()
        print("Night light", "off" if active else "on")
    elif cmd == "warmth":
        if len(argv) > 2:
            value = sch.set_warmth(int(argv[2]))
            sch.start_preview(4)
            notify_daemon()
            print(f"Warmth set to {value}")
        else:
            print(sch.load_config().warmth)
    elif cmd == "settings":
        from .settings import main as settings_main
        return settings_main()
    elif cmd == "reload":
        sch.load_config()   # fail here, loudly, if the TOML is broken
        notify_daemon()
    elif cmd == "status":
        status()
    elif cmd == "preview":
        secs = float(argv[2]) if len(argv) > 2 else 10
        sch.start_preview(secs)
        notify_daemon()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
