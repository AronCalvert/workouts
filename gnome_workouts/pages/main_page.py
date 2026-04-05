from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GObject, Gtk

from .progress_page import HistoryPage
from ..ui_utils import *


class MainPage(Adw.NavigationPage):
    __gtype_name__ = "GnomeWorkoutsMainPage"

    __gsignals__ = {
        "workout-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, app: Adw.Application) -> None:
        super().__init__(title="Workouts")
        self._app = app

        self._stack = Adw.ViewStack()
        self._stack.set_vexpand(True)

        self._stack_switcher = Adw.ViewSwitcher()
        self._stack_switcher.set_stack(self._stack)
        self._stack_switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        self._stack_switcher.set_hexpand(True)
        self._stack_switcher.set_halign(Gtk.Align.CENTER)

        self._history_page = HistoryPage(app)
        self._stack.add_titled_with_icon(
            self._build_workouts_view(), "workouts", "Workouts", "view-list-symbolic"
        )
        self._stack.add_titled_with_icon(
            self._history_page, "history", "History", "document-open-recent-symbolic"
        )

        header = Adw.HeaderBar()
        header.set_title_widget(self._stack_switcher)

        add_btn = create_header_button(
            "list-add-symbolic",
            tooltip="Create a new workout",
            accessible_name="New Workout",
        )
        add_btn.connect("clicked", self._on_add_workout_clicked)
        header.pack_start(add_btn)

        prefs_btn = create_header_button(
            "emblem-system-symbolic",
            tooltip="Preferences",
            accessible_name="Preferences",
        )
        prefs_btn.connect("clicked", self._on_prefs_clicked)
        header.pack_end(prefs_btn)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._stack)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._toast_overlay)

        self.set_child(toolbar)

    @property
    def db(self):
        return self._app.db

    def _show_error(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))

    def _build_workouts_view(self) -> Gtk.Widget:
        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=760)
        clamp.set_hexpand(True)
        clamp.set_vexpand(True)

        self._workouts_stack = Gtk.Stack()
        self._workouts_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self._list_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        set_margins(self._list_page, all=18)

        self._list = create_boxed_listbox()
        self._list_page.append(self._list)

        self._empty_page = Adw.StatusPage(
            title="No Workouts Yet",
            description="Add your first workout using the \u201c+\u201d button above.",
            icon_name="view-list-symbolic",
        )

        self._workouts_stack.add_named(self._list_page, "list")
        self._workouts_stack.add_named(self._empty_page, "empty")
        clamp.set_child(self._workouts_stack)

        self.refresh()
        return clamp

    def refresh(self) -> None:
        if hasattr(self, "_history_page"):
            self._history_page.refresh()

        clear_container(self._list)

        workouts = self.db.list_workouts()
        for w in workouts:
            row = Adw.ActionRow(title=w.name)
            gesture = Gtk.GestureClick()
            gesture.connect(
                "released",
                lambda _g, _n, _x, _y, wid=w.id: self.emit("workout-activated", wid),
            )
            row.add_controller(gesture)

            delete_btn = Gtk.Button()
            delete_btn.set_icon_name("user-trash-symbolic")
            delete_btn.set_valign(Gtk.Align.CENTER)
            delete_btn.connect(
                "clicked",
                lambda _btn, workout_id=w.id, workout_name=w.name: (
                    self._confirm_delete_workout(workout_id, workout_name)
                ),
            )
            style_header_icon_button(
                delete_btn,
                tooltip=f"Delete workout \u2018{w.name}\u2019",
                accessible_name=f"Delete {w.name}",
            )
            row.add_suffix(delete_btn)
            self._list.append(row)

        if workouts:
            self._workouts_stack.set_visible_child_name("list")
        else:
            self._workouts_stack.set_visible_child_name("empty")

    def _confirm_delete_workout(self, workout_id: int, workout_name: str) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading("Delete Workout")
        dialog.set_body(
            f"Delete workout \u2018{workout_name}\u2019 and all associated data? This cannot be undone."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "delete":
                return
            try:
                self.db.delete_workout(workout_id)
            except ValueError as exc:
                self._show_error(str(exc))
                return
            self.refresh()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)

    def _on_prefs_clicked(self, _btn: Gtk.Button) -> None:
        prefs = self._app.prefs

        dialog = Adw.AlertDialog()
        dialog.set_heading("Preferences")

        unit_model = Gtk.StringList()
        unit_model.append("Kilograms (kg)")
        unit_model.append("Pounds (lbs)")
        unit_dd = Gtk.DropDown(model=unit_model)
        unit_dd.set_selected(0 if prefs.weight_unit == "kg" else 1)
        unit_dd.set_hexpand(True)
        unit_dd.set_valign(Gtk.Align.CENTER)
        set_accessible_label(unit_dd, "Weight unit")
        unit_row = Adw.ActionRow(title="Weight Unit")
        unit_row.add_suffix(unit_dd)

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        form.append(unit_row)
        dialog.set_extra_child(form)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "save":
                return
            prefs.weight_unit = "kg" if unit_dd.get_selected() == 0 else "lbs"

        dialog.connect("response", on_response)
        present_dialog(dialog, self)

    def _on_add_workout_clicked(self, _btn: Gtk.Button) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading("New Workout")
        dialog.set_body("Choose a name for your workout.")

        name_row = Adw.EntryRow(title="Name")
        dialog.set_extra_child(name_row)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Create")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("add")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("add", False)

        def on_name_changed(_row: Adw.EntryRow) -> None:
            dialog.set_response_enabled("add", bool(name_row.get_text().strip()))

        name_row.connect("changed", on_name_changed)

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "add":
                return
            try:
                self.db.create_workout(name_row.get_text().strip())
            except ValueError as exc:
                self._show_error(str(exc))
                return
            self.refresh()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)
