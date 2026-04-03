from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GObject, Gtk

from ..ui_utils import *


@dataclass
class _ExerciseForm:
    form: Gtk.Box
    name_row: Adw.EntryRow
    type_dd: Gtk.DropDown
    rest_adj: Gtk.Adjustment
    sets_adj: Gtk.Adjustment
    reps_adj: Gtk.Adjustment
    weight_adj: Gtk.Adjustment
    dur_adj: Gtk.Adjustment


class WorkoutDetailPage(Adw.NavigationPage):
    __gtype_name__ = "GnomeWorkoutsWorkoutDetailPage"

    __gsignals__ = {
        "begin-workout": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, app: Adw.Application, workout_id: int) -> None:
        super().__init__(title="Workout")
        self._app = app
        self._workout_id = workout_id

        header = Adw.HeaderBar()

        add_btn = create_header_button(
            "list-add-symbolic",
            tooltip="Add an exercise to this workout",
            accessible_name="Add Exercise",
        )
        add_btn.connect("clicked", self._on_add_exercise_clicked)
        header.pack_start(add_btn)

        self._body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        set_margins(self._body, all=18)

        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=760)
        clamp.set_hexpand(True)
        clamp.set_vexpand(True)
        clamp.set_child(self._body)

        self._empty_page = Adw.StatusPage(
            title="No Exercises Yet",
            description="Add your first exercise using the \u201c+\u201d button above.",
            icon_name="view-list-symbolic",
        )

        self._exercises_stack = Gtk.Stack()
        self._exercises_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._exercises_stack.set_vexpand(True)
        self._exercises_stack.add_named(clamp, "list")
        self._exercises_stack.add_named(self._empty_page, "empty")

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._exercises_stack)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._toast_overlay)
        self.set_child(toolbar)

        self._reload()

    @property
    def _db(self):
        return self._app.db

    def _show_error(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))

    def _reload(self) -> None:
        clear_container(self._body)
        plan = self._db.get_workout_plan(self._workout_id)
        if plan is None:
            self.set_title("Workout")
            label = Gtk.Label(label="This workout could not be loaded.")
            label.add_css_class("dim-label")
            self._body.append(label)
            return

        self._plan = plan
        self.set_title(plan.workout.name)

        if not plan.exercises:
            self._exercises_stack.set_visible_child_name("empty")
            return

        self._exercises_stack.set_visible_child_name("list")
        prefs = self._app.prefs
        total = len(plan.exercises)

        list_box = create_boxed_listbox()

        for i, ex in enumerate(plan.exercises):
            row = Adw.ActionRow(title=ex.name)
            sets = plan.sets_by_exercise_id.get(ex.id, [])

            row.set_activatable(True)
            row.connect(
                "activated", lambda _r, eid=ex.id: self._open_edit_exercise_dialog(eid)
            )

            if total > 1:
                up_btn = Gtk.Button()
                up_btn.set_icon_name("go-up-symbolic")
                up_btn.set_valign(Gtk.Align.CENTER)
                up_btn.set_sensitive(i > 0)
                if i > 0:
                    prev_id = plan.exercises[i - 1].id
                    up_btn.connect(
                        "clicked",
                        lambda _b, a=ex.id, b=prev_id: self._move_exercise(a, b),
                    )
                style_header_icon_button(
                    up_btn, tooltip="Move up", accessible_name=f"Move {ex.name} up"
                )
                row.add_suffix(up_btn)

                down_btn = Gtk.Button()
                down_btn.set_icon_name("go-down-symbolic")
                down_btn.set_valign(Gtk.Align.CENTER)
                down_btn.set_sensitive(i < total - 1)
                if i < total - 1:
                    next_id = plan.exercises[i + 1].id
                    down_btn.connect(
                        "clicked",
                        lambda _b, a=ex.id, b=next_id: self._move_exercise(a, b),
                    )
                style_header_icon_button(
                    down_btn,
                    tooltip="Move down",
                    accessible_name=f"Move {ex.name} down",
                )
                row.add_suffix(down_btn)

            del_btn = Gtk.Button()
            del_btn.set_icon_name("user-trash-symbolic")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.connect(
                "clicked", lambda _b, eid=ex.id: self._on_remove_exercise_clicked(eid)
            )
            style_header_icon_button(
                del_btn,
                tooltip=f"Remove \u201c{ex.name}\u201d from this workout",
                accessible_name=f"Remove {ex.name}",
            )
            row.add_suffix(del_btn)

            if ex.exercise_type == "timed" and ex.timed_seconds is not None:
                row.set_subtitle(
                    f"{len(sets)} set(s) \u2022 {ex.timed_seconds}s hold \u2022 rest {ex.rest_seconds}s"
                )
            else:
                first = sets[0] if sets else None
                parts = [f"{len(sets)} set(s)"]
                if first and first.target_reps is not None:
                    parts.append(f"{first.target_reps} reps")
                if (
                    first
                    and first.target_weight_kg is not None
                    and first.target_weight_kg > 0
                ):
                    parts.append(
                        f"{prefs.kg_to_display(first.target_weight_kg):g} {prefs.weight_label}"
                    )
                parts.append(f"rest {ex.rest_seconds}s")
                row.set_subtitle(" \u2022 ".join(parts))

            row.set_subtitle_lines(2)
            list_box.append(row)

        self._body.append(list_box)

        begin_btn = Gtk.Button(label="Begin Workout")
        begin_btn.add_css_class("suggested-action")
        begin_btn.connect("clicked", self._on_begin_clicked)
        begin_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        begin_row.set_halign(Gtk.Align.CENTER)
        set_margins(begin_row, top=12)
        begin_row.append(begin_btn)
        self._body.append(begin_row)

    # for building forms

    def _build_exercise_form(
        self,
        *,
        name: str = "",
        exercise_type: str = "reps",
        rest_seconds: int = 90,
        num_sets: int = 3,
        target_reps: int = 10,
        target_weight_display: float = 0.0,
        timed_seconds: int = 45,
    ) -> _ExerciseForm:
        prefs = self._app.prefs

        name_row = Adw.EntryRow(title="Name")
        name_row.set_text(name)

        type_model = Gtk.StringList()
        type_model.append("Reps")
        type_model.append("Timed")
        type_dd = Gtk.DropDown(model=type_model)
        type_dd.set_selected(0 if exercise_type == "reps" else 1)
        type_dd.set_hexpand(True)
        type_dd.set_valign(Gtk.Align.CENTER)
        set_accessible_label(type_dd, "Exercise type")
        type_row = Adw.ActionRow(title="Exercise Type")
        type_row.add_suffix(type_dd)

        rest_adj = Gtk.Adjustment(
            value=rest_seconds, lower=0, upper=600, step_increment=5
        )
        rest_row = Adw.SpinRow(
            title="Rest Between Sets (seconds)", adjustment=rest_adj, digits=0
        )

        sets_adj = Gtk.Adjustment(value=num_sets, lower=1, upper=20, step_increment=1)
        sets_row = Adw.SpinRow(title="Number of Sets", adjustment=sets_adj, digits=0)

        reps_adj = Gtk.Adjustment(
            value=target_reps, lower=0, upper=999, step_increment=1
        )
        reps_row = Adw.SpinRow(
            title="Target Reps per Set", adjustment=reps_adj, digits=0
        )

        weight_adj = Gtk.Adjustment(
            value=target_weight_display,
            lower=0,
            upper=prefs.weight_max,
            step_increment=prefs.weight_step,
        )
        weight_row = Adw.SpinRow(
            title=f"Target Weight ({prefs.weight_label})",
            adjustment=weight_adj,
            digits=1,
        )

        dur_adj = Gtk.Adjustment(
            value=timed_seconds, lower=1, upper=600, step_increment=1
        )
        timed_row = Adw.SpinRow(
            title="Hold Duration (seconds)", adjustment=dur_adj, digits=0
        )

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for widget in (
            name_row,
            type_row,
            rest_row,
            sets_row,
            reps_row,
            weight_row,
            timed_row,
        ):
            form.append(widget)

        def sync_type(*_args: object) -> None:
            is_reps = type_dd.get_selected() == 0
            reps_row.set_visible(is_reps)
            weight_row.set_visible(is_reps)
            timed_row.set_visible(not is_reps)

        type_dd.connect("notify::selected", sync_type)
        sync_type()

        return _ExerciseForm(
            form=form,
            name_row=name_row,
            type_dd=type_dd,
            rest_adj=rest_adj,
            sets_adj=sets_adj,
            reps_adj=reps_adj,
            weight_adj=weight_adj,
            dur_adj=dur_adj,
        )

    # handling

    def _on_begin_clicked(self, _btn: Gtk.Button) -> None:
        self.emit("begin-workout", int(self._workout_id))

    def _move_exercise(self, exercise_id_a: int, exercise_id_b: int) -> None:
        try:
            self._db.swap_exercise_order(self._workout_id, exercise_id_a, exercise_id_b)
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self._reload()

    def _on_remove_exercise_clicked(self, exercise_id: int) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading("Remove Exercise?")
        dialog.set_body(
            "This cannot be undone. Planned sets for this exercise will be removed from the workout."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Remove")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "delete":
                return
            try:
                self._db.delete_exercise_from_workout(self._workout_id, exercise_id)
            except ValueError as exc:
                self._show_error(str(exc))
                return
            self._reload()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)

    def _open_edit_exercise_dialog(self, exercise_id: int) -> None:
        details = self._db.get_exercise_details(exercise_id)
        if details is None:
            return
        exercise, sets = details
        prefs = self._app.prefs
        stored_kg = (
            sets[0].target_weight_kg
            if sets and sets[0].target_weight_kg is not None
            else 0.0
        )

        f = self._build_exercise_form(
            name=exercise.name,
            exercise_type=exercise.exercise_type,
            rest_seconds=exercise.rest_seconds,
            num_sets=len(sets),
            target_reps=sets[0].target_reps
            if sets and sets[0].target_reps is not None
            else 10,
            target_weight_display=prefs.kg_to_display(stored_kg),
            timed_seconds=exercise.timed_seconds
            if exercise.timed_seconds is not None
            else 45,
        )

        dialog = Adw.AlertDialog()
        dialog.set_heading("Edit Exercise")
        dialog.set_extra_child(f.form)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("save", bool(exercise.name.strip()))
        f.name_row.connect(
            "changed",
            lambda _r: dialog.set_response_enabled(
                "save", bool(f.name_row.get_text().strip())
            ),
        )

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "save":
                return
            typ = "reps" if f.type_dd.get_selected() == 0 else "timed"
            w_raw = float(f.weight_adj.get_value()) if typ == "reps" else None
            try:
                self._db.update_exercise(
                    exercise_id,
                    name=f.name_row.get_text().strip(),
                    exercise_type=typ,
                    rest_seconds=int(f.rest_adj.get_value()),
                    timed_seconds=int(f.dur_adj.get_value())
                    if typ == "timed"
                    else None,
                    num_sets=int(f.sets_adj.get_value()),
                    target_reps=int(f.reps_adj.get_value()) if typ == "reps" else None,
                    target_weight_kg=None
                    if (w_raw is None or w_raw <= 0.0)
                    else prefs.display_to_kg(w_raw),
                )
            except ValueError as exc:
                self._show_error(str(exc))
                return
            self._reload()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)

    def _on_add_exercise_clicked(self, _btn: Gtk.Button) -> None:
        prefs = self._app.prefs
        f = self._build_exercise_form()

        dialog = Adw.AlertDialog()
        dialog.set_heading("Add Exercise")
        dialog.set_extra_child(f.form)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add Exercise")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("add")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("add", False)
        f.name_row.connect(
            "changed",
            lambda _r: dialog.set_response_enabled(
                "add", bool(f.name_row.get_text().strip())
            ),
        )

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "add":
                return
            typ = "reps" if f.type_dd.get_selected() == 0 else "timed"
            w_raw = float(f.weight_adj.get_value()) if typ == "reps" else None
            try:
                self._db.add_exercise_to_workout(
                    self._workout_id,
                    name=f.name_row.get_text().strip(),
                    exercise_type=typ,
                    rest_seconds=int(f.rest_adj.get_value()),
                    timed_seconds=int(f.dur_adj.get_value())
                    if typ == "timed"
                    else None,
                    num_sets=int(f.sets_adj.get_value()),
                    target_reps=int(f.reps_adj.get_value()) if typ == "reps" else None,
                    target_weight_kg=None
                    if (w_raw is None or w_raw <= 0.0)
                    else prefs.display_to_kg(w_raw),
                )
            except ValueError as exc:
                self._show_error(str(exc))
                return
            self._reload()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)
