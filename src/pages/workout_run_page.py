from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GObject, Gtk

from ..db import Database
from ..models import ExercisePlan, SetPlan, WorkoutPlan, SessionPerformedLine
from ..prefs import Preferences
from ..widgets.timer_widget import CountdownTimer
from .. import sound
from ..ui_utils import (
    clear_container,
    create_boxed_listbox,
    format_set_detail,
    group_session_lines,
    present_dialog,
    set_accessible_label,
    set_margins,
)


@dataclass(frozen=True, slots=True)
class _WorkoutStep:
    exercise: ExercisePlan
    set_plan: SetPlan
    rest_after: int  # seconds; 0 = go directly to next step (superset partner)
    group_index: int  # 0-indexed position of this group in the workout
    total_groups: int  # total number of non-empty groups
    round_number: int  # 1-indexed round/set number within this group
    total_rounds: int  # total rounds for this group
    in_superset: bool  # True when part of a superset
    superset_pos: int  # 1-indexed position within superset (1 for solo)
    superset_size: int  # total exercises in superset (1 for solo)


def _build_steps(plan: WorkoutPlan) -> list[_WorkoutStep]:
    ordered_groups: list[list[ExercisePlan]] = []
    seen_groups: set[int] = set()
    for ex in plan.exercises:
        if ex.superset_group is None:
            ordered_groups.append([ex])
        elif ex.superset_group not in seen_groups:
            seen_groups.add(ex.superset_group)
            cluster = [
                e for e in plan.exercises if e.superset_group == ex.superset_group
            ]
            ordered_groups.append(cluster)

    non_empty = [
        g
        for g in ordered_groups
        if max((len(plan.sets_by_exercise_id.get(ex.id, [])) for ex in g), default=0)
        > 0
    ]

    total_groups = len(non_empty)
    steps: list[_WorkoutStep] = []

    for group_idx, group in enumerate(non_empty):
        is_superset = len(group) > 1
        all_sets = [plan.sets_by_exercise_id.get(ex.id, []) for ex in group]
        max_rounds = max(len(s) for s in all_sets)

        group_rest = group[-1].rest_seconds

        for round_idx in range(max_rounds):
            round_entries: list[tuple[ExercisePlan, SetPlan, int]] = []
            for ex_pos, ex in enumerate(group):
                ex_sets = plan.sets_by_exercise_id.get(ex.id, [])
                if round_idx < len(ex_sets):
                    round_entries.append((ex, ex_sets[round_idx], ex_pos))

            for i, (ex, s, ex_pos) in enumerate(round_entries):
                is_last_in_round = i == len(round_entries) - 1
                if not is_last_in_round:
                    rest = 0
                elif is_superset and len(round_entries) == 1:
                    rest = ex.rest_seconds
                else:
                    rest = group_rest
                steps.append(
                    _WorkoutStep(
                        exercise=ex,
                        set_plan=s,
                        rest_after=rest,
                        group_index=group_idx,
                        total_groups=total_groups,
                        round_number=round_idx + 1,
                        total_rounds=max_rounds,
                        in_superset=is_superset,
                        superset_pos=ex_pos + 1,
                        superset_size=len(group),
                    )
                )

    return steps


class WorkoutRunPage(Adw.NavigationPage):
    __gtype_name__ = "GnomeWorkoutsWorkoutRunPage"

    __gsignals__ = {
        "finished": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(
        self, *, db: Database, plan: WorkoutPlan, session_id: int, prefs: Preferences
    ) -> None:
        super().__init__(title="In Progress")
        self.set_can_pop(False)
        self._db = db
        self._plan = plan
        self._session_id = session_id
        self._prefs = prefs

        self._steps = _build_steps(plan)
        self._step_index = 0
        self._reps_row: Adw.SpinRow | None = None
        self._weight_row: Adw.SpinRow | None = None
        self._notes_row: Adw.EntryRow | None = None
        self._last_logged: dict[int, tuple[int, float | None]] = {}

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

        self._active_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        name_block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self._headline = Gtk.Label()
        self._headline.add_css_class("title-1")
        self._headline.set_halign(Gtk.Align.CENTER)
        self._headline.set_wrap(True)
        self._headline.set_justify(Gtk.Justification.CENTER)
        name_block.append(self._headline)

        self._superset_label = Gtk.Label()
        self._superset_label.add_css_class("caption")
        self._superset_label.add_css_class("accent")
        self._superset_label.set_halign(Gtk.Align.CENTER)
        self._superset_label.set_visible(False)
        name_block.append(self._superset_label)

        self._progress_label = Gtk.Label()
        self._progress_label.add_css_class("dim-label")
        self._progress_label.set_halign(Gtk.Align.CENTER)
        name_block.append(self._progress_label)

        self._active_section.append(name_block)

        self._set_list = create_boxed_listbox()
        self._active_section.append(self._set_list)

        self._last_label = Gtk.Label()
        self._last_label.add_css_class("dim-label")
        self._last_label.add_css_class("caption")
        self._last_label.set_halign(Gtk.Align.CENTER)
        self._last_label.set_wrap(True)
        self._last_label.set_justify(Gtk.Justification.CENTER)
        self._last_label.set_visible(False)
        self._active_section.append(self._last_label)

        self._hold_timer = CountdownTimer(pill=True, show_reset=False, play_ticks=True)
        set_accessible_label(self._hold_timer, "Hold timer")
        self._hold_timer.connect("finished", self._on_hold_finished)
        self._hold_timer.set_visible(False)
        self._active_section.append(self._hold_timer)

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

        self._active_btns = active_btns
        self._active_section.append(active_btns)

        self._skip_hold_btn = Gtk.Button(label="Skip Hold")
        self._skip_hold_btn.add_css_class("flat")
        self._skip_hold_btn.set_tooltip_text("Skip this hold without logging")
        self._skip_hold_btn.set_halign(Gtk.Align.CENTER)
        self._skip_hold_btn.set_visible(False)
        self._skip_hold_btn.connect("clicked", self._on_skip_hold_clicked)
        self._active_section.append(self._skip_hold_btn)
        outer.append(self._active_section)

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

        self._rest_timer = CountdownTimer(pill=True, show_reset=False, play_ticks=True)
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

        self._complete_section = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=18
        )
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

        self._summary_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=18
        )
        self._complete_section.append(self._summary_container)

        done_btn = Gtk.Button(label="Done")
        done_btn.add_css_class("suggested-action")
        done_btn.add_css_class("pill")
        done_btn.set_tooltip_text("Return to the workout list")
        done_btn.connect("clicked", self._on_done_clicked)
        done_btn.set_halign(Gtk.Align.CENTER)
        self._complete_section.append(done_btn)

        outer.append(self._complete_section)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(scroll)
        self.set_child(toolbar)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        self._render_current()

    def _show_section(self, section: Gtk.Widget) -> None:
        for s in (self._active_section, self._rest_section, self._complete_section):
            s.set_visible(s is section)

    def _render_current(self) -> None:
        clear_container(self._set_list)
        self._reps_row = None
        self._weight_row = None
        self._notes_row = None

        if self._step_index >= len(self._steps):
            self._end_session()
            return

        step = self._steps[self._step_index]
        ex = step.exercise
        cur_set = step.set_plan

        self._headline.set_label(ex.name)

        if step.in_superset:
            self._superset_label.set_label(
                f"Superset \u00b7 {step.superset_pos} of {step.superset_size}"
            )
            self._superset_label.set_visible(True)
            self._progress_label.set_label(
                f"Round {step.round_number} of {step.total_rounds}"
                f"\u2002\u00b7\u2002"
                f"Group {step.group_index + 1} of {step.total_groups}"
            )
        else:
            self._superset_label.set_visible(False)
            self._progress_label.set_label(
                f"Set {step.round_number} of {step.total_rounds}"
                f"\u2002\u00b7\u2002"
                f"Exercise {step.group_index + 1} of {step.total_groups}"
            )

        if ex.exercise_type == "timed":
            self._set_list.set_visible(False)
            self._active_btns.set_visible(False)
            self._last_label.set_visible(False)
            self._hold_timer.set_duration(ex.timed_seconds or 0)
            self._hold_timer.set_visible(True)
            self._skip_hold_btn.set_visible(True)
            self._hold_timer.start()
        else:
            self._set_list.set_visible(True)
            self._active_btns.set_visible(True)
            self._hold_timer.set_visible(False)
            self._skip_hold_btn.set_visible(False)
            last = self._last_logged.get(ex.id)
            default_reps = last[0] if last is not None else (cur_set.target_reps or 0)
            default_weight_kg = (
                (last[1] or 0.0)
                if last is not None
                else (cur_set.target_weight_kg or 0.0)
            )

            reps_adj = Gtk.Adjustment(
                value=float(default_reps),
                lower=0,
                upper=999,
                step_increment=1,
            )
            reps = Adw.SpinRow(title="Reps completed", adjustment=reps_adj, digits=0)

            weight_adj = Gtk.Adjustment(
                value=self._prefs.kg_to_display(float(default_weight_kg)),
                lower=0.0,
                upper=self._prefs.weight_max,
                step_increment=self._prefs.weight_step,
            )
            weight = Adw.SpinRow(
                title=f"Weight ({self._prefs.weight_label})",
                adjustment=weight_adj,
                digits=1,
            )
            weight.set_subtitle("Use 0 for bodyweight")
            weight.set_subtitle_lines(2)
            self._reps_row = reps
            self._weight_row = weight
            self._set_list.append(reps)
            self._set_list.append(weight)

            prior = self._db.get_last_performed_sets(ex.id, self._session_id)
            if prior:
                self._last_label.set_label("Previous:  " + self._format_last_sets(prior))
                self._last_label.set_visible(True)
            else:
                self._last_label.set_visible(False)

        notes_row = Adw.EntryRow(title="Notes (optional)")
        self._notes_row = notes_row
        self._set_list.append(notes_row)

        self._show_section(self._active_section)

    def _start_rest(self, seconds: int, next_name: str) -> None:
        self._rest_next_label.set_label(f"Next up: {next_name}")
        self._rest_timer.set_duration(seconds)
        self._rest_timer.start()
        self._show_section(self._rest_section)

    def _end_session(self) -> None:
        self._hold_timer.reset()
        self._rest_timer.reset()
        self._db.finish_session(self._session_id)
        sound.play("complete")
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

        groups = group_session_lines(lines)

        for ex_name, ex_lines in groups:
            group_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

            label = Gtk.Label(label=ex_name)
            label.add_css_class("heading")
            label.set_halign(Gtk.Align.START)
            group_box.append(label)

            set_list = create_boxed_listbox()
            for line in ex_lines:
                row = Adw.ActionRow(title=f"Set {line.set_number}")
                row.set_subtitle(format_set_detail(line, self._prefs))
                set_list.append(row)
            group_box.append(set_list)

            self._summary_container.append(group_box)

        total_kg = sum(
            (line.reps or 0) * line.weight_kg
            for line in lines
            if line.exercise_type == "reps"
            and line.weight_kg is not None
            and line.weight_kg > 0
        )
        if total_kg > 0:
            vol_display = self._prefs.kg_to_display(total_kg)
            vol_list = create_boxed_listbox()
            vol_row = Adw.ActionRow(title="Total Volume")
            vol_row.set_subtitle(f"{vol_display:g} {self._prefs.weight_label}")
            vol_list.append(vol_row)
            self._summary_container.append(vol_list)

    def _on_hold_finished(self, _timer: CountdownTimer) -> None:
        if self._step_index >= len(self._steps):
            return
        step = self._steps[self._step_index]
        ex = step.exercise
        cur_set = step.set_plan

        sound.play("complete")

        self._db.set_performed_set(
            session_id=self._session_id,
            exercise_id=ex.id,
            set_id=cur_set.id,
            order_index=cur_set.order_index,
            completed=True,
            reps=None,
            weight_kg=None,
            duration_seconds=int(ex.timed_seconds or 0),
            notes=None,
        )

        rest = step.rest_after
        self._step_index += 1

        if self._step_index >= len(self._steps):
            self._end_session()
        elif rest > 0:
            next_step = self._steps[self._step_index]
            self._start_rest(rest, next_step.exercise.name)
        else:
            self._render_current()

    def _on_skip_hold_clicked(self, _btn: Gtk.Button) -> None:
        self._hold_timer.reset()
        if self._step_index >= len(self._steps):
            return
        self._step_index += 1
        self._render_current()

    def _on_complete_clicked(self, _btn: Gtk.Button) -> None:
        if self._step_index >= len(self._steps):
            return
        step = self._steps[self._step_index]
        ex = step.exercise
        cur_set = step.set_plan

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
            self._last_logged[ex.id] = (reps, weight)

        notes_text = self._notes_row.get_text().strip() if self._notes_row else ""
        self._db.set_performed_set(
            session_id=self._session_id,
            exercise_id=ex.id,
            set_id=cur_set.id,
            order_index=cur_set.order_index,
            completed=True,
            reps=reps,
            weight_kg=weight,
            duration_seconds=duration,
            notes=notes_text if notes_text else None,
        )

        rest = step.rest_after
        self._step_index += 1

        if self._step_index >= len(self._steps):
            self._end_session()
        elif rest > 0:
            next_step = self._steps[self._step_index]
            self._start_rest(rest, next_step.exercise.name)
        else:
            self._render_current()

    def _on_skip_set_clicked(self, _btn: Gtk.Button) -> None:
        if self._step_index >= len(self._steps):
            return
        self._step_index += 1
        self._render_current()

    def _on_rest_finished(self, _timer: CountdownTimer) -> None:
        sound.play("complete")
        self._render_current()

    def _on_skip_rest_clicked(self, _btn: Gtk.Button) -> None:
        self._rest_timer.set_duration(0)
        self._render_current()

    def _on_finish_clicked(self, _btn: Gtk.Button) -> None:
        self._hold_timer.pause()
        self._rest_timer.pause()
        dialog = Adw.AlertDialog()
        dialog.set_heading("Finish Workout?")
        dialog.set_body("Any remaining sets will not be logged. This cannot be undone.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("finish", "Finish")
        dialog.set_response_appearance("finish", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d: Adw.AlertDialog, r: str) -> None:
            if r == "finish":
                self._end_session()
            else:
                self._hold_timer.resume()
                self._rest_timer.resume()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)

    def _format_last_sets(self, sets: list[tuple[int | None, float | None]]) -> str:
        parts = []
        for reps, weight_kg in sets:
            if reps is None:
                continue
            if weight_kg:
                w = self._prefs.kg_to_display(weight_kg)
                parts.append(f"{reps} × {w:g} {self._prefs.weight_label}")
            else:
                parts.append(f"{reps} reps")
        return "  ·  ".join(parts)

    def _on_key_pressed(
        self, _ctrl: Gtk.EventControllerKey, keyval: int, _keycode: int, _state: Gdk.ModifierType
    ) -> bool:
        if self._active_section.get_visible():
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                if not self._hold_timer.get_visible():
                    self._on_complete_clicked(None)
                return True
            if keyval in (Gdk.KEY_s, Gdk.KEY_S):
                if not self._hold_timer.get_visible():
                    self._on_skip_set_clicked(None)
                return True
        if self._rest_section.get_visible():
            if keyval in (Gdk.KEY_r, Gdk.KEY_R, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self._on_skip_rest_clicked(None)
                return True
        return False

    def _on_done_clicked(self, _btn: Gtk.Button) -> None:
        self.emit("finished")
