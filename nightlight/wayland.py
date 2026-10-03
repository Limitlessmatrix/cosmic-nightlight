"""Minimal Wayland client speaking the wire protocol directly.

Only the handful of requests and events needed to put a tinted
overlay on every output are implemented. No third-party packages.
"""

import array
import os
import socket
import struct


class WaylandError(Exception):
    pass


def _pad(n):
    return (n + 3) & ~3


def _string(s):
    data = s.encode() + b"\0"
    return struct.pack("<I", len(data)) + data + b"\0" * (_pad(len(data)) - len(data))


class Proxy:
    """A protocol object. `events` maps opcode -> (signature, handler)."""

    def __init__(self, conn, oid, interface):
        self.conn = conn
        self.id = oid
        self.interface = interface
        self.handlers = {}

    def on(self, opcode, signature, handler):
        self.handlers[opcode] = (signature, handler)

    def request(self, opcode, payload=b"", fds=()):
        self.conn.send(self.id, opcode, payload, fds)


class Connection:
    def __init__(self, display=None):
        name = display or os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        path = name if name.startswith("/") else os.path.join(os.environ["XDG_RUNTIME_DIR"], name)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.objects = {}
        self.free_ids = []
        self.next_id = 2
        self.buf = b""
        self.display = Proxy(self, 1, "wl_display")
        self.objects[1] = self.display
        self.display.on(0, "osus", self._on_error)
        self.display.on(1, "u", self._on_delete_id)

    # object management -------------------------------------------------
    def new(self, interface):
        oid = self.free_ids.pop() if self.free_ids else self._alloc()
        proxy = Proxy(self, oid, interface)
        self.objects[oid] = proxy
        return proxy

    def _alloc(self):
        oid = self.next_id
        self.next_id += 1
        return oid

    def _on_error(self, obj_id, code, message):
        iface = self.objects[obj_id].interface if obj_id in self.objects else "?"
        raise WaylandError(f"{iface}@{obj_id}: error {code}: {message}")

    def _on_delete_id(self, oid):
        self.objects.pop(oid, None)
        self.free_ids.append(oid)

    # wire I/O ------------------------------------------------------------
    def send(self, oid, opcode, payload, fds=()):
        header = struct.pack("<II", oid, ((8 + len(payload)) << 16) | opcode)
        anc = []
        if fds:
            anc = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))]
        self.sock.sendmsg([header + payload], anc)

    def fileno(self):
        return self.sock.fileno()

    def read_events(self):
        """Read whatever is available and dispatch complete messages."""
        data = self.sock.recv(65536)
        if not data:
            raise WaylandError("compositor closed the connection")
        self.buf += data
        while len(self.buf) >= 8:
            oid, word = struct.unpack_from("<II", self.buf)
            size, opcode = word >> 16, word & 0xFFFF
            if len(self.buf) < size:
                break
            body, self.buf = self.buf[8:size], self.buf[size:]
            obj = self.objects.get(oid)
            if obj and opcode in obj.handlers:
                signature, handler = obj.handlers[opcode]
                handler(*self._decode(signature, body))

    @staticmethod
    def _decode(signature, body):
        args, pos = [], 0
        for t in signature:
            if t in "uon":
                args.append(struct.unpack_from("<I", body, pos)[0])
                pos += 4
            elif t == "i":
                args.append(struct.unpack_from("<i", body, pos)[0])
                pos += 4
            elif t == "s":
                n = struct.unpack_from("<I", body, pos)[0]
                args.append(body[pos + 4 : pos + 4 + n - 1].decode(errors="replace"))
                pos += 4 + _pad(n)
            elif t == "a":
                n = struct.unpack_from("<I", body, pos)[0]
                args.append(body[pos + 4 : pos + 4 + n])
                pos += 4 + _pad(n)
        return args

    def roundtrip(self):
        done = []
        cb = self.new("wl_callback")
        cb.on(0, "u", lambda _: done.append(True))
        self.display.request(0, struct.pack("<I", cb.id))
        while not done:
            self.read_events()


# request helpers -----------------------------------------------------------

def u32(*vals):
    return struct.pack("<" + "I" * len(vals), *vals)


def i32(*vals):
    return struct.pack("<" + "i" * len(vals), *vals)


def string(s):
    return _string(s)


def bind(registry, name, interface, version):
    proxy = registry.conn.new(interface)
    registry.request(0, u32(name) + string(interface) + u32(version, proxy.id))
    return proxy
