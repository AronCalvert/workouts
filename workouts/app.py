from __future__ import annotations

import sys

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio

from .db import open_default_db
from .prefs import Preferences, default_prefs_path
from .window import MainWindow


APP_ID = "io.github.AronCalvert.Workouts"


class WorkoutApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        self._db = None
        self._prefs: Preferences | None = None

    @property
    def prefs(self) -> Preferences:
        if self._prefs is None:
            self._prefs = Preferences(default_prefs_path(APP_ID))
        return self._prefs

    @property
    def db(self):
        if self._db is None:
            self._db = open_default_db(APP_ID)
        return self._db

    def do_activate(self) -> None:
        win = self.props.active_window
        if win is None:
            win = MainWindow(self)
        win.present()

    def do_shutdown(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
        Adw.Application.do_shutdown(self)


def main(argv: list[str] | None = None) -> int:
    Adw.init()
    app = WorkoutApp()
    return app.run(argv if argv is not None else sys.argv)
