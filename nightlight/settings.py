"""Small GTK 4 settings window: a warmth slider and a mode switch."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import schedule as sch  # noqa: E402
from .__main__ import daemon_running, describe_schedule, notify_daemon, target_level  # noqa: E402

APP_ID = "io.github.cosmicnightlight.Settings"
PREVIEW_SECONDS = 4

CSS = b"""
.section-title { font-weight: bold; }
.dim { opacity: 0.7; }
.warning { color: #c0392b; }
"""


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Night Light")
        self.set_default_size(440, -1)
        self.set_resizable(False)
        self.cfg = sch.load_config()
        self._save_id = 0

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(24)
        self.set_child(box)

        # Warmth slider
        box.append(self._title("How red at night"))
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_value(self.cfg.warmth)
        self.scale.set_draw_value(True)
        self.scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.scale.set_digits(0)
        self.scale.add_mark(0, Gtk.PositionType.BOTTOM, "Mild")
        self.scale.add_mark(50, Gtk.PositionType.BOTTOM, None)
        self.scale.add_mark(100, Gtk.PositionType.BOTTOM, "Very red")
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self._on_warmth)
        box.append(self.scale)
        box.append(self._note("Moving the slider shows full strength for a few seconds."))

        # Mode
        box.append(self._title("When"))
        modes = Gtk.Box(spacing=0, css_classes=["linked"], homogeneous=True)
        self.mode_buttons = {}
        first = None
        for mode, label in (("auto", "On schedule"), ("on", "Always on"), ("off", "Off")):
            btn = Gtk.ToggleButton(label=label)
            if first:
                btn.set_group(first)
            first = first or btn
            btn.set_active(sch.read_mode() == mode)
            btn.connect("toggled", self._on_mode, mode)
            modes.append(btn)
            self.mode_buttons[mode] = btn
        box.append(modes)

        sched = describe_schedule(self.cfg)
        text = sched[0].capitalize()
        if len(sched) > 1:
            text += "\nExcept " + "; ".join(sched[1:])
        box.append(self._note(text))

        self.now_label = self._note("")
        box.append(self.now_label)

        open_btn = Gtk.Button(label="Edit schedule…")
        open_btn.set_halign(Gtk.Align.START)
        open_btn.connect("clicked", self._open_config)
        box.append(open_btn)

        self._refresh_status()
        GLib.timeout_add_seconds(5, self._refresh_status)

    def _title(self, text):
        return Gtk.Label(label=text, xalign=0, css_classes=["section-title"])

    def _note(self, text):
        return Gtk.Label(label=text, xalign=0, wrap=True, css_classes=["dim"])

    def _on_warmth(self, scale):
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(120, self._save_warmth)

    def _save_warmth(self):
        self._save_id = 0
        self.cfg.warmth = sch.set_warmth(round(self.scale.get_value()))
        sch.start_preview(PREVIEW_SECONDS)
        notify_daemon(quiet=True)
        return False

    def _on_mode(self, btn, mode):
        if btn.get_active():
            sch.write_mode(mode)
            notify_daemon(quiet=True)
            self._refresh_status()

    def _open_config(self, _btn):
        Gio.AppInfo.launch_default_for_uri(sch.CONFIG_FILE.as_uri(), None)

    def _refresh_status(self):
        if not daemon_running():
            self.now_label.set_label("The background service isn't running. "
                                     "Run: systemctl --user start cosmic-nightlight")
            self.now_label.set_css_classes(["warning"])
        else:
            pct = round(sch.night_level(self.cfg) * 100) if sch.read_mode() == "auto" \
                else round(target_level(self.cfg, sch.read_mode()) * 100)
            self.now_label.set_label(f"Right now: {pct}% of full night")
            self.now_label.set_css_classes(["dim"])
        return True


def main():
    app = Gtk.Application(application_id=APP_ID)

    def activate(app):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = app.get_active_window() or SettingsWindow(app)
        win.present()

    app.connect("activate", activate)
    return app.run([])
