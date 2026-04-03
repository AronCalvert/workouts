from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GObject, Gtk

from ..db import Database
from ..models import ExercisePlan, SetPlan, WorkoutPlan, SessionPerformedLine
from ..prefs import Preferences
from ..widgets.timer_widget import CountdownTimer
from ..ui_utils import *


def _format_set_detail(line: SessionPerformedLine) -> str:
    if line.exercise_type == "timed":
        sec = line.duration_seconds if line.duration_seconds is not None else 0
        return f"{sec}s hold"
    parts: list[str] = []
    if line.reps is not None:
        parts.append(f"{line.reps} reps")
    if line.weight_kg is not None:
        parts.append(f"{line.weight_kg:g} kg")
    return ", ".join(parts) if parts else "\u2014"


class WorkoutRunPage(Adw.NavigationPage):
    """
    Active workout session page.

    Three mutually exclusive states:
      - active: user fills in the current set
      - resting: countdown between sets; inputs hidden
      - complete: session summary
    """

    __gtype_name__ = "GnomeWorkoutsWorkoutRunPage"

    __gsignals__ = {
        "finished": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, *, db: Database, plan: WorkoutPlan, session_id: int, prefs: Preferences) -> None:
        super().__init__(title="In Progress")
        self.set_can_pop(False)
        self._db = db
        self._plan = plan
        self._session_id = session_id
        self._prefs = prefs

        self._exercise_index = 0
        self._set_index = 0
        self._reps_row: Adw.SpinRow | None = None
        self._weight_row: Adw.SpinRow | None = None

        # ── Header ──────────────────────────────────────────────────────────
        header = Adw.HeaderBar()

        header_title_label = Gtk.Label(label=plan.workout.name)
        header_title_label.add_css_class("title")
        header.set_title_widget(header_title_label)

        finish_btn = Gtk.Button(label="Finish")
        finish_btn.add_css_class("flat")
        finish_btn.set_tooltip_text("End this session early")
        finish_btn.connect("clicked", self._on_finish_clicked)
        header.pack_start(finish_btn)
        self._finish_btn = finish_btn

        # ── Scroll + clamp ───────────────────────────────────────────────────
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        clamp = Adw.Clamp(maximum_size=560, tightening_threshold=560)
        clamp.set_hexpand(True)
        clamp.set_vexpand(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        set_margins(outer, top=32, bottom=32, start=18, end=18)
        clamp.set_child(outer)
        scroll.set_child(clamp)

        # ── State: active set ────────────────────────────────────────────────
        self._active_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        name_block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self._headline = Gtk.Label()
        self._headline.add_css_class("title-1")
        self._headline.set_halign(Gtk.Align.CENTER)
        self._headline.set_wrap(True)
        self._headline.set_justify(Gtk.Justification.CENTER)
        name_block.append(self._headline)

        self._progress_label = Gtk.Label()
        self._progress_label.add_css_class("dim-label")
        self._progress_label.set_halign(Gtk.Align.CENTER)
        name_block.append(self._progress_label)

        self._active_section.append(name_block)

        self._set_list = create_boxed_listbox()
        self._active_section.append(self._set_list)

        active_btns = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        active_btns.set_halign(Gtk.Align.CENTER)

        self._complete_btn = Gtk.Button(label="Save Set")
        self._complete_btn.add_css_class("suggested-action")
        self._complete_btn.add_css_class("pill")
        self._complete_btn.set_tooltip_text("Log this set and continue")
        self._complete_btn.connect("clicked", self._on_complete_clicked)
        active_btns.append(self._complete_btn)

        self._skip_btn = Gtk.Button(label="Skip Set")
        self._skip_btn.add_css_class("flat")
        self._skip_btn.set_tooltip_text("Skip without logging")
        self._skip_btn.connect("clicked", self._on_skip_set_clicked)
        active_btns.append(self._skip_btn)

        self._active_section.append(active_btns)
        outer.append(self._active_section)

        # ── State: resting ───────────────────────────────────────────────────
        self._rest_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._rest_section.set_visible(False)

        rest_title = Gtk.Label(label="Resting")
        rest_title.add_css_class("title-1")
        rest_title.set_halign(Gtk.Align.CENTER)
        self._rest_section.append(rest_title)

        self._rest_next_label = Gtk.Label()
        self._rest_next_label.add_css_class("dim-label")
        self._rest_next_label.set_halign(Gtk.Align.CENTER)
        self._rest_section.append(self._rest_next_label)

        self._rest_timer = CountdownTimer(pill=True, show_reset=False)
        set_accessible_label(self._rest_timer, "Rest timer")
        self._rest_timer.connect("finished", self._on_rest_finished)
        self._rest_section.append(self._rest_timer)

        skip_rest_btn = Gtk.Button(label="Skip Rest")
        skip_rest_btn.add_css_class("flat")
        skip_rest_btn.set_tooltip_text("End the rest period early")
        skip_rest_btn.connect("clicked", self._on_skip_rest_clicked)
        skip_rest_btn.set_halign(Gtk.Align.CENTER)
        self._rest_section.append(skip_rest_btn)

        outer.append(self._rest_section)

        # ── State: complete ──────────────────────────────────────────────────
        self._complete_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._complete_section.set_visible(False)

        complete_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        complete_header.set_halign(Gtk.Align.CENTER)

        complete_icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
        complete_icon.set_pixel_size(64)
        complete_icon.add_css_class("dim-label")
        complete_header.append(complete_icon)

        complete_title = Gtk.Label(label="Workout Complete")
        complete_title.add_css_class("title-2")
        complete_title.set_halign(Gtk.Align.CENTER)
        complete_header.append(complete_title)

        complete_desc = Gtk.Label(label="Here\u2019s what you logged today.")
        complete_desc.add_css_class("dim-label")
        complete_desc.set_halign(Gtk.Align.CENTER)
        complete_header.append(complete_desc)

        self._complete_section.append(complete_header)

        self._summary_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._complete_section.append(self._summary_container)

        done_btn = Gtk.Button(label="Done")
        done_btn.add_css_class("suggested-action")
        done_btn.add_css_class("pill")
        done_btn.set_tooltip_text("Return to the workout list")
        done_btn.connect("clicked", self._on_done_clicked)
        done_btn.set_halign(Gtk.Align.CENTER)
        self._complete_section.append(done_btn)

        outer.append(self._complete_section)

        # ── Assemble ─────────────────────────────────────────────────────────
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(scroll)
        self.set_child(toolbar)

        self._render_current()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _current_exercise(self) -> ExercisePlan | None:
        if self._exercise_index < 0 or self._exercise_index >= len(self._plan.exercises):
            return None
        return self._plan.exercises[self._exercise_index]

    def _current_set(self, ex: ExercisePlan) -> SetPlan | None:
        sets = self._plan.sets_by_exercise_id.get(ex.id, [])
        if self._set_index < 0 or self._set_index >= len(sets):
            return None
        return sets[self._set_index]

    def _advance(self, ex: ExercisePlan) -> None:
        """Increment set/exercise indices."""
        sets = self._plan.sets_by_exercise_id.get(ex.id, [])
        self._set_index += 1
        if self._set_index >= len(sets):
            self._exercise_index += 1
            self._set_index = 0

    def _show_section(self, section: Gtk.Widget) -> None:
        for s in (self._active_section, self._rest_section, self._complete_section):
            s.set_visible(s is section)

    # ── Render ───────────────────────────────────────────────────────────────

    def _render_current(self) -> None:
        """Populate and display the active-set state; skips empty exercises."""
        while True:
            clear_container(self._set_list)
            self._reps_row = None
            self._weight_row = None

            ex = self._current_exercise()
            if ex is None:
                self._end_session()
                return

            sets = self._plan.sets_by_exercise_id.get(ex.id, [])
            cur_set = self._current_set(ex)
            if not sets or cur_set is None:
                self._exercise_index += 1
                self._set_index = 0
                continue

            total_ex = len(self._plan.exercises)
            total_sets = len(sets)
            self._headline.set_label(ex.name)
            self._progress_label.set_label(
                f"Set {self._set_index + 1} of {total_sets}"
                f"\u2002\u00b7\u2002"
                f"Exercise {self._exercise_index + 1} of {total_ex}"
            )

            if ex.exercise_type == "timed":
                seconds = ex.timed_seconds or 0
                row = Adw.ActionRow(title="Hold Duration")
                row.set_subtitle(f"{seconds} seconds")
                self._set_list.append(row)
            else:
                reps_adj = Gtk.Adjustment(value=float(cur_set.target_reps or 0), lower=0, upper=999, step_increment=1)
                reps = Adw.SpinRow(title="Reps completed", adjustment=reps_adj, digits=0)

                weight_adj = Gtk.Adjustment(
                    value=self._prefs.kg_to_display(float(cur_set.target_weight_kg or 0.0)),
                    lower=0.0,
                    upper=self._prefs.weight_max,
                    step_increment=self._prefs.weight_step,
                )
                weight = Adw.SpinRow(title=f"Weight ({self._prefs.weight_label})", adjustment=weight_adj, digits=1)
                weight.set_subtitle("Use 0 for bodyweight")
                weight.set_subtitle_lines(2)
                self._reps_row = reps
                self._weight_row = weight
                self._set_list.append(reps)
                self._set_list.append(weight)

            self._show_section(self._active_section)
            return

    def _start_rest(self, seconds: int, next_name: str) -> None:
        self._rest_next_label.set_label(f"Next up: {next_name}")
        self._rest_timer.set_duration(seconds)
        self._rest_timer.start()
        self._show_section(self._rest_section)

    def _end_session(self) -> None:
        self._rest_timer.set_duration(0)
        self._db.finish_session(self._session_id)
        self._populate_summary()
        self._show_section(self._complete_section)
        self._finish_btn.set_visible(False)

    def _populate_summary(self) -> None:
        clear_container(self._summary_container)
        lines = self._db.get_session_performed_lines(self._session_id)

        if not lines:
            empty_list = create_boxed_listbox()
            row = Adw.ActionRow(title="No sets logged")
            row.set_subtitle("No sets were completed during this session.")
            empty_list.append(row)
            self._summary_container.append(empty_list)
            return

        groups: list[tuple[str, list[SessionPerformedLine]]] = []
        for line in lines:
            if groups and groups[-1][0] == line.exercise_name:
                groups[-1][1].append(line)
            else:
                groups.append((line.exercise_name, [line]))

        for ex_name, ex_lines in groups:
            group_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

            label = Gtk.Label(label=ex_name)
            label.add_css_class("heading")
            label.set_halign(Gtk.Align.START)
            group_box.append(label)

            set_list = create_boxed_listbox()
            for line in ex_lines:
                row = Adw.ActionRow(title=f"Set {line.set_number}")
                row.set_subtitle(_format_set_detail(line))
                set_list.append(row)
            group_box.append(set_list)

            self._summary_container.append(group_box)

    # ── Signal handlers ──────────────────────────────────────────────────────

    def _on_complete_clicked(self, _btn: Gtk.Button) -> None:
        ex = self._current_exercise()
        if ex is None:
            return
        cur_set = self._current_set(ex)
        if cur_set is None:
            return

        reps: int | None = None
        weight: float | None = None
        duration: int | None = None

        if ex.exercise_type == "timed":
            duration = int(ex.timed_seconds or 0)
        else:
            if self._reps_row is None or self._weight_row is None:
                return
            reps = int(self._reps_row.get_value())
            w = float(self._weight_row.get_value())
            weight = None if w <= 0.0 else self._prefs.display_to_kg(w)

        self._db.set_performed_set(
            session_id=self._session_id,
            exercise_id=ex.id,
            set_id=cur_set.id,
            order_index=cur_set.order_index,
            completed=True,
            reps=reps,
            weight_kg=weight,
            duration_seconds=duration,
        )

        rest_seconds = ex.rest_seconds
        self._advance(ex)

        next_ex = self._current_exercise()
        if next_ex is None:
            self._end_session()
        elif rest_seconds > 0:
            self._start_rest(rest_seconds, next_ex.name)
        else:
            self._render_current()

    def _on_skip_set_clicked(self, _btn: Gtk.Button) -> None:
        ex = self._current_exercise()
        if ex is None or self._current_set(ex) is None:
            return
        self._advance(ex)
        self._render_current()

    def _on_rest_finished(self, _timer: CountdownTimer) -> None:
        self._render_current()

    def _on_skip_rest_clicked(self, _btn: Gtk.Button) -> None:
        self._rest_timer.set_duration(0)
        self._render_current()

    def _on_finish_clicked(self, _btn: Gtk.Button) -> None:
        self._end_session()

    def _on_done_clicked(self, _btn: Gtk.Button) -> None:
        self.emit("finished")
