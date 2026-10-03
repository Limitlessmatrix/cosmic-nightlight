# cosmic-nightlight

A blue-light filter for the COSMIC desktop on Pop!_OS, with a schedule and gradual fades.

COSMIC doesn't ship a working night light yet, and its compositor doesn't support
`wlr-gamma-control`, so gammastep, wlsunset, and redshift can't run on it.
This tool draws a click-through amber layer over each screen using
`wlr-layer-shell` instead. It is plain Python 3.11+ with no dependencies, and it
talks to the compositor directly over the Wayland socket.

## Install

```sh
./install.sh
```

This adds a `nightlight` command to `~/.local/bin` and a systemd user service that
starts with your desktop session.

## Use

```sh
nightlight status          # mode, schedule, and current level
nightlight on              # full strength now, ignoring the schedule
nightlight off             # off now, ignoring the schedule
nightlight auto            # follow the schedule again
nightlight toggle          # flip on/off (good for a keyboard shortcut)
nightlight preview 10      # see full strength for 10 seconds
nightlight reload          # apply config changes
```

`on` and `off` stay in effect until you run `nightlight auto`.

To bind a key: **Settings → Keyboard → Keyboard shortcuts → Custom shortcuts → Add
shortcut**, with the command `nightlight toggle`.

## Configure

Open **Night Light** from the app launcher (or run `nightlight settings`) to change
how red it gets with a slider and switch between schedule, always on, and off.
Moving the slider shows full strength for a few seconds so you can judge it.
`nightlight warmth 70` does the same from a terminal.

For the schedule, edit `~/.config/cosmic-nightlight/config.toml`, then run
`nightlight reload`.

| Setting | Default | Meaning |
|---|---|---|
| `warmth` | `50` | How red it gets, 0 (barely warm) to 100 (very red). |
| `start` / `end` | `"22:00"` / `"08:00"` | Night window, local 24-hour time. May cross midnight. |
| `fade_minutes` | `30` | Fade in after `start`, fade out before `end`. |
| `[days]` | `thu = { start = "23:00" }` | Different times for the night that begins on that day. |

Example: later nights on weekends too.

```toml
[days]
thu = { start = "23:00" }
fri = { start = "23:30", end = "09:00" }
sat = { start = "23:30", end = "09:00" }
```

The schedule is based on the clock, so if the computer is turned on or wakes from
sleep during the night, the tint comes on within 30 seconds.

## Limits of the overlay approach

A real night light scales the display's color curves. An overlay can only blend a
color on top, so:

- **Dark areas pick up an amber haze.** Higher `strength` removes more blue from
  bright areas but lifts blacks more. Around 0.3 to 0.4 is a reasonable balance.
- **Screenshots and screen recordings include the tint.** Run `nightlight off`
  first if that matters.
- **Fullscreen games can lose direct scanout** while the tint is visible, which may
  cost a little performance. When the tint is fully off, the overlay is removed
  completely.

If COSMIC adds gamma control later, a gamma-based tool will give better results
than this one.
