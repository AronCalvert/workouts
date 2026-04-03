from __future__ import annotations

import time

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import GLib, GObject, Gtk


def _format_mmss(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    m, s = divmod(seconds, 60)
    return f"{m:d}:{s:02d}"


class CountdownTimer(Gtk.Box):

    __gtype_name__ = "GnomeWorkoutsCountdownTimer"

    __gsignals__ = {
        "finished": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, *, pill: bool = False, show_reset: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self._duration = 0
        self._running = False
        self._paused = False
        self._t_start = 0.0
        self._elapsed_before = 0.0
        self._tick_source: int | None = None

        self._time = Gtk.Label(label="0:00")
        self._time.add_css_class("title-1")
        self._time.set_xalign(0.5)

        self._hint = Gtk.Label(label="")
        self._hint.add_css_class("dim-label")
        self._hint.set_xalign(0.5)

        self._primary = Gtk.Button(label="Start")
        self._primary.add_css_class("suggested-action")
        if pill:
            self._primary.add_css_class("pill")
        self._primary.set_tooltip_text("Start, pause, or resume the rest countdown")
        self._primary.connect("clicked", self._on_primary_clicked)

        self._reset = Gtk.Button(label="Reset")
        self._reset.set_tooltip_text("Stop the timer and clear the countdown")
        self._reset.connect("clicked", self._on_reset_clicked)

        orientation = Gtk.Orientation.VERTICAL if pill else Gtk.Orientation.HORIZONTAL
        controls = Gtk.Box(orientation=orientation, spacing=6)
        controls.set_halign(Gtk.Align.CENTER)
        controls.append(self._primary)
        if show_reset:
            controls.append(self._reset)

        self.append(self._time)
        self.append(self._hint)
        self.append(controls)

    def set_hint(self, text: str) -> None:
        self._hint.set_label(text)
        self._hint.set_visible(bool(text))

    def set_duration(self, seconds: int) -> None:
        self._duration = max(0, int(seconds))
        self.reset()

    def is_running(self) -> bool:
        return self._running and not self._paused

    def remaining_seconds(self) -> int:
        elapsed = self._elapsed_before
        if self._running and not self._paused:
            elapsed += max(0.0, time.monotonic() - self._t_start)
        return max(0, int(round(self._duration - elapsed)))

    def start(self) -> None:
        if self._duration <= 0:
            self.reset()
            return
        self._running = True
        self._paused = False
        self._elapsed_before = 0.0
        self._t_start = time.monotonic()
        self._ensure_tick()
        self._update_ui()

    def pause(self) -> None:
        if not self._running or self._paused:
            return
        self._elapsed_before += max(0.0, time.monotonic() - self._t_start)
        self._paused = True
        self._update_ui()

    def resume(self) -> None:
        if not self._running or not self._paused:
            return
        self._paused = False
        self._t_start = time.monotonic()
        self._ensure_tick()
        self._update_ui()

    def reset(self) -> None:
        self._running = False
        self._paused = False
        self._elapsed_before = 0.0
        self._t_start = 0.0
        self._stop_tick()
        self._update_ui()

    def _ensure_tick(self) -> None:
        if self._tick_source is not None:
            return
        self._tick_source = GLib.timeout_add(200, self._on_tick)

    def _stop_tick(self) -> None:
        if self._tick_source is not None:
            GLib.source_remove(self._tick_source)
            self._tick_source = None

    def _on_tick(self) -> bool:
        self._update_ui()
        if not self._running:
            self._stop_tick()
            return False
        if self._paused:
            return True
        if self.remaining_seconds() <= 0:
            self._running = False
            self._paused = False
            self._update_ui()
            self._stop_tick()
            self.emit("finished")
            return False
        return True

    def _update_ui(self) -> None:
        self._time.set_label(_format_mmss(self.remaining_seconds()))
        if not self._running:
            self._primary.set_label("Start")
            self._primary.set_sensitive(self._duration > 0)
        elif self._paused:
            self._primary.set_label("Resume")
        else:
            self._primary.set_label("Pause")

        self._reset.set_sensitive(self._duration > 0)

    def _on_primary_clicked(self, _btn: Gtk.Button) -> None:
        if not self._running:
            self.start()
        elif self._paused:
            self.resume()
        else:
            self.pause()

    def _on_reset_clicked(self, _btn: Gtk.Button) -> None:
        self.reset()
