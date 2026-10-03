"""Click-through, full-screen tint on every output via wlr-layer-shell.

The tint is a single-pixel buffer stretched across the output with
wp_viewporter, so it costs almost nothing to draw. When the tint is
fully transparent the surfaces are destroyed so fullscreen apps and
games can go back to direct scanout.
"""

from . import wayland as w

LAYER_OVERLAY = 3
ANCHOR_ALL = 1 | 2 | 4 | 8
U32_MAX = 0xFFFFFFFF


class OutputOverlay:
    def __init__(self, mgr, output):
        self.mgr = mgr
        self.output = output
        self.surface = None
        self.layer = None
        self.viewport = None
        self.size = None
        self.buffer = None

    @property
    def mapped(self):
        return self.surface is not None

    def create(self):
        m, conn = self.mgr, self.mgr.conn
        self.surface = conn.new("wl_surface")
        m.compositor.request(0, w.u32(self.surface.id))

        # An empty input region makes the overlay click-through.
        region = conn.new("wl_region")
        m.compositor.request(1, w.u32(region.id))
        self.surface.request(5, w.u32(region.id))
        region.request(0)

        self.viewport = conn.new("wp_viewport")
        m.viewporter.request(1, w.u32(self.viewport.id, self.surface.id))

        self.layer = conn.new("zwlr_layer_surface_v1")
        m.layer_shell.request(
            0,
            w.u32(self.layer.id, self.surface.id, self.output.id, LAYER_OVERLAY)
            + w.string("nightlight"),
        )
        self.layer.on(0, "uuu", self._on_configure)
        self.layer.on(1, "", self._on_closed)
        self.layer.request(1, w.u32(ANCHOR_ALL))      # set_anchor
        self.layer.request(2, w.i32(-1))              # set_exclusive_zone: ignore panels
        self.layer.request(4, w.u32(0))               # keyboard_interactivity: none
        self.surface.request(6)                       # initial commit, no buffer

    def _on_configure(self, serial, width, height):
        self.layer.request(6, w.u32(serial))          # ack_configure
        self.size = (width, height)
        self.viewport.request(2, w.i32(width, height))  # set_destination
        self.paint()

    def _on_closed(self):
        self.destroy()

    def paint(self):
        if not self.mapped or self.size is None:
            return
        old = self.buffer
        self.buffer = self.mgr.make_buffer()
        self.surface.request(1, w.u32(self.buffer.id) + w.i32(0, 0))   # attach
        self.surface.request(9, w.i32(0, 0, 1, 1))                     # damage_buffer
        self.surface.request(6)                                        # commit
        if old is not None:
            self._release_later(old)

    def _release_later(self, buf):
        # Destroy a replaced buffer once the compositor is done with it.
        buf.on(0, "", lambda: buf.request(0))

    def destroy(self):
        if not self.mapped:
            return
        self.layer.request(7)
        self.viewport.request(0)
        self.surface.request(0)
        if self.buffer is not None:
            self.buffer.request(0)
        self.surface = self.layer = self.viewport = self.buffer = None
        self.size = None


class OverlayManager:
    def __init__(self):
        self.conn = w.Connection()
        self.registry = self.conn.new("wl_registry")
        self.registry.on(0, "usu", self._on_global)
        self.registry.on(1, "u", self._on_global_remove)
        self.compositor = self.layer_shell = self.viewporter = self.pixels = None
        self.overlays = {}          # global name -> OutputOverlay
        self.rgba = (0, 0, 0, 0)    # premultiplied, 0.0-1.0
        self.conn.display.request(1, w.u32(self.registry.id))
        self.conn.roundtrip()
        missing = [n for n, v in [
            ("wl_compositor", self.compositor),
            ("zwlr_layer_shell_v1", self.layer_shell),
            ("wp_viewporter", self.viewporter),
            ("wp_single_pixel_buffer_manager_v1", self.pixels),
        ] if v is None]
        if missing:
            raise w.WaylandError("compositor is missing: " + ", ".join(missing))

    def _on_global(self, name, interface, version):
        r = self.registry
        if interface == "wl_compositor":
            self.compositor = w.bind(r, name, interface, min(version, 4))
        elif interface == "zwlr_layer_shell_v1":
            self.layer_shell = w.bind(r, name, interface, min(version, 4))
        elif interface == "wp_viewporter":
            self.viewporter = w.bind(r, name, interface, 1)
        elif interface == "wp_single_pixel_buffer_manager_v1":
            self.pixels = w.bind(r, name, interface, 1)
        elif interface == "wl_output":
            output = w.bind(r, name, interface, min(version, 4))
            self.overlays[name] = OutputOverlay(self, output)
            self._sync(self.overlays[name])

    def _on_global_remove(self, name):
        ov = self.overlays.pop(name, None)
        if ov:
            ov.destroy()
            if ov.output.interface == "wl_output":
                ov.output.request(0)    # release (v3+)

    def make_buffer(self):
        buf = self.conn.new("wl_buffer")
        r, g, b, a = (round(max(0.0, min(1.0, x)) * U32_MAX) for x in self.rgba)
        self.pixels.request(1, w.u32(buf.id, r, g, b, a))
        return buf

    def set_tint(self, rgb, alpha):
        """rgb: 0-255 straight color; alpha: 0.0-1.0 opacity."""
        self.rgba = tuple(c / 255 * alpha for c in rgb) + (alpha,)
        for ov in self.overlays.values():
            self._sync(ov)

    def _sync(self, ov):
        if self.layer_shell is None or self.compositor is None:
            return
        if self.rgba[3] <= 0.001:
            ov.destroy()
        elif not ov.mapped:
            ov.create()
        else:
            ov.paint()

    def fileno(self):
        return self.conn.fileno()

    def dispatch(self):
        self.conn.read_events()
