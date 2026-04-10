from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GObject, Gtk

from .progress_page import HistoryPage
from ..ui_utils import (
    clear_container,
    create_boxed_listbox,
    create_header_button,
    present_dialog,
    set_margins,
    style_header_icon_button,
)


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

        app_menu = Gio.Menu()
        app_menu.append("Preferences", "mainpage.preferences")
        app_menu.append("About Workouts", "mainpage.about")

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=app_menu)
        menu_btn.set_tooltip_text("Main menu")
        menu_btn.add_css_class("flat")
        header.pack_end(menu_btn)

        page_actions = Gio.SimpleActionGroup()
        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", lambda *_: self._show_preferences())
        page_actions.add_action(prefs_action)
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", lambda *_: self._show_about())
        page_actions.add_action(about_action)
        self.insert_action_group("mainpage", page_actions)

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
        self._history_page.refresh()

        clear_container(self._list)

        workouts = self.db.list_workouts()
        for w in workouts:
            ex_label = f"{w.exercise_count} exercise{'s' if w.exercise_count != 1 else ''}"
            set_label = f"{w.set_count} set{'s' if w.set_count != 1 else ''}"
            row = Adw.ActionRow(title=w.name, subtitle=f"{ex_label} \u2022 {set_label}", use_markup=False)
            gesture = Gtk.GestureClick()
            gesture.connect(
                "released",
                lambda _g, _n, _x, _y, wid=w.id: self.emit("workout-activated", wid),
            )
            row.add_controller(gesture)

            action_group = Gio.SimpleActionGroup()
            rename_action = Gio.SimpleAction.new("rename", None)
            rename_action.connect(
                "activate",
                lambda *_, wid=w.id, wname=w.name: self._show_rename_dialog(wid, wname),
            )
            action_group.add_action(rename_action)
            duplicate_action = Gio.SimpleAction.new("duplicate", None)
            duplicate_action.connect(
                "activate",
                lambda *_, wid=w.id, wname=w.name: self._show_duplicate_dialog(wid, wname),
            )
            action_group.add_action(duplicate_action)
            delete_action = Gio.SimpleAction.new("delete", None)
            delete_action.connect(
                "activate",
                lambda *_, wid=w.id, wname=w.name: self._confirm_delete_workout(wid, wname),
            )
            action_group.add_action(delete_action)
            row.insert_action_group("workout", action_group)

            menu = Gio.Menu()
            menu.append("Rename", "workout.rename")
            menu.append("Duplicate", "workout.duplicate")
            menu.append("Delete", "workout.delete")

            cog_btn = Gtk.MenuButton()
            cog_btn.set_icon_name("emblem-system-symbolic")
            cog_btn.set_menu_model(menu)
            cog_btn.set_valign(Gtk.Align.CENTER)
            style_header_icon_button(
                cog_btn,
                tooltip=f"Options for \u2018{w.name}\u2019",
                accessible_name=f"Options for {w.name}",
            )
            row.add_suffix(cog_btn)
            self._list.append(row)

        if workouts:
            self._workouts_stack.set_visible_child_name("list")
        else:
            self._workouts_stack.set_visible_child_name("empty")

    def _show_rename_dialog(self, workout_id: int, current_name: str) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading("Rename Workout")

        name_row = Adw.EntryRow(title="Name")
        name_row.set_text(current_name)
        dialog.set_extra_child(name_row)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("save", bool(current_name.strip()))

        name_row.connect(
            "changed",
            lambda _r: dialog.set_response_enabled(
                "save", bool(name_row.get_text().strip())
            ),
        )

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "save":
                return
            try:
                self.db.rename_workout(workout_id, name_row.get_text().strip())
            except ValueError as exc:
                self._show_error(str(exc))
                return
            self.refresh()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)

    def _show_duplicate_dialog(self, workout_id: int, source_name: str) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading("Duplicate Workout")
        dialog.set_body("Choose a name for the copy.")

        name_row = Adw.EntryRow(title="Name")
        name_row.set_text(f"Copy of {source_name}")
        dialog.set_extra_child(name_row)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("duplicate", "Duplicate")
        dialog.set_response_appearance("duplicate", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("duplicate")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("duplicate", True)

        name_row.connect(
            "changed",
            lambda _r: dialog.set_response_enabled(
                "duplicate", bool(name_row.get_text().strip())
            ),
        )

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "duplicate":
                return
            try:
                self.db.duplicate_workout(workout_id, name_row.get_text().strip())
            except ValueError as exc:
                self._show_error(str(exc))
                return
            self.refresh()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)

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

    def _show_preferences(self) -> None:
        prefs = self._app.prefs

        unit_row = Adw.ComboRow(title="Weight Unit")
        unit_model = Gtk.StringList()
        unit_model.append("Kilograms (kg)")
        unit_model.append("Pounds (lbs)")
        unit_row.set_model(unit_model)
        unit_row.set_selected(0 if prefs.weight_unit == "kg" else 1)
        unit_row.connect(
            "notify::selected",
            lambda row, _: setattr(
                prefs, "weight_unit", "kg" if row.get_selected() == 0 else "lbs"
            ),
        )

        group = Adw.PreferencesGroup(title="Units")
        group.add(unit_row)

        page = Adw.PreferencesPage()
        page.add(group)

        dialog = Adw.PreferencesDialog()
        dialog.add(page)
        present_dialog(dialog, self)

    def _show_about(self) -> None:
        dialog = Adw.AboutDialog(
            application_name="Workouts",
            application_icon="io.github.AronCalvert.Workouts",
            developer_name="Aron Calvert",
            version="0.1.0",
            website="https://github.com/AronCalvert/gnome-workouts",
            issue_url="https://github.com/AronCalvert/gnome-workouts/issues",
            license_type=Gtk.License.GPL_3_0,
        )
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
