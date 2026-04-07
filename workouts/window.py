from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk

from .pages.main_page import MainPage
from .pages.workout_detail_page import WorkoutDetailPage
from .pages.workout_run_page import WorkoutRunPage


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app)
        self.set_title("Workouts")
        self.set_default_size(980, 720)
        self.set_size_request(360, 320)

        self._nav = Adw.NavigationView()
        self.set_content(self._nav)

        self._main_page = MainPage(app)
        self._main_page.connect("workout-activated", self._on_workout_activated)
        self._nav.push(self._main_page)

    @property
    def db(self):
        return self.get_application().db

    def _on_workout_activated(self, _page: MainPage, workout_id: int) -> None:
        if self.db.get_workout_plan(workout_id) is None:
            return

        detail = WorkoutDetailPage(self.get_application(), workout_id)
        detail.connect("begin-workout", self._on_begin_workout)
        self._nav.push(detail)

    def _on_begin_workout(self, _page: WorkoutDetailPage, workout_id: int) -> None:
        plan = self.db.get_workout_plan(workout_id)
        if plan is None:
            return
        session_id = self.db.start_session(workout_id)
        run = WorkoutRunPage(
            db=self.db,
            plan=plan,
            session_id=session_id,
            prefs=self.get_application().prefs,
        )
        run.connect("finished", self._on_run_finished)
        self._nav.push(run)

    def _on_run_finished(self, _page: WorkoutRunPage) -> None:
        self._nav.pop_to_page(self._main_page)
        self._main_page.refresh()
