from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk


class ProgressPage(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=760)
        clamp.set_hexpand(True)
        clamp.set_vexpand(True)

        status = Adw.StatusPage(
            title="Progress", description="hope to implement this eventually"
        )
        clamp.set_child(status)
        self.append(clamp)
