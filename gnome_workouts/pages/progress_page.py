from __future__ import annotations

import datetime as pydt

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gtk

from ..models import SessionInfo, SessionPerformedLine
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


class HistoryPage(Gtk.Box):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._app = app

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        clamp = Adw.Clamp(maximum_size=600, tightening_threshold=600)
        clamp.set_hexpand(True)
        clamp.set_vexpand(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        set_margins(outer, top=18, bottom=18, start=18, end=18)
        clamp.set_child(outer)
        scroll.set_child(clamp)

        _css = Gtk.CssProvider()
        _css.load_from_string("""
            .history-calendar {
                background-color: @card_bg_color;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            _css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._calendar = Gtk.Calendar()
        self._calendar.add_css_class("history-calendar")
        self._calendar.connect("day-selected", self._on_day_selected)
        self._calendar.connect("prev-month", self._on_month_changed)
        self._calendar.connect("next-month", self._on_month_changed)

        cal_frame = Gtk.Frame()
        cal_frame.set_halign(Gtk.Align.CENTER)
        cal_frame.set_child(self._calendar)
        outer.append(cal_frame)

        self._detail_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12
        )
        outer.append(self._detail_container)

        self.append(scroll)
        self._refresh_marks()

    @property
    def _db(self):
        return self._app.db

    def refresh(self) -> None:
        self._refresh_marks()
        self._show_selected_day()

    def _refresh_marks(self) -> None:
        self._calendar.clear_marks()
        dt = self._calendar.get_date()
        for day in self._db.get_sessions_for_month(dt.get_year(), dt.get_month()):
            self._calendar.mark_day(day)

    def _on_day_selected(self, _cal: Gtk.Calendar) -> None:
        self._show_selected_day()

    def _on_month_changed(self, _cal: Gtk.Calendar) -> None:
        self._refresh_marks()
        clear_container(self._detail_container)

    def _show_selected_day(self) -> None:
        clear_container(self._detail_container)
        dt = self._calendar.get_date()
        year, month, day = dt.get_year(), dt.get_month(), dt.get_day_of_month()

        sessions = self._db.get_sessions_for_date(year, month, day)
        if not sessions:
            return

        heading = Gtk.Label(label=pydt.date(year, month, day).strftime("%A, %B %-d"))
        heading.add_css_class("heading")
        heading.set_halign(Gtk.Align.START)
        self._detail_container.append(heading)

        session_list = create_boxed_listbox()
        for si in sessions:
            time_str = si.started_at[11:16]
            row = Adw.ActionRow(title=si.workout_name, subtitle=time_str)
            row.set_activatable(True)
            row.connect("activated", lambda _r, s=si: self._open_session_dialog(s))

            del_btn = Gtk.Button()
            del_btn.set_icon_name("user-trash-symbolic")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.connect("clicked", lambda _b, s=si: self._confirm_delete_session(s))
            style_header_icon_button(
                del_btn,
                tooltip="Delete this session from history",
                accessible_name=f"Delete {si.workout_name} session",
            )
            row.add_suffix(del_btn)
            session_list.append(row)

        self._detail_container.append(session_list)

    def _confirm_delete_session(self, si: SessionInfo) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading("Delete Session?")
        dialog.set_body(
            f"Remove the \u201c{si.workout_name}\u201d session at {si.started_at[11:16]}? "
            "This cannot be undone."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "delete":
                return
            self._db.delete_session(si.session_id)
            self._refresh_marks()
            self._show_selected_day()

        dialog.connect("response", on_response)
        present_dialog(dialog, self)

    def _open_session_dialog(self, si: SessionInfo) -> None:
        lines = self._db.get_session_performed_lines(si.session_id)
        time_str = si.started_at[11:16]

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        set_margins(content_box, top=18, bottom=18, start=18, end=18)

        time_label = Gtk.Label(label=time_str)
        time_label.add_css_class("dim-label")
        time_label.set_halign(Gtk.Align.CENTER)
        content_box.append(time_label)

        if not lines:
            empty_label = Gtk.Label(label="No sets were logged in this session.")
            empty_label.add_css_class("dim-label")
            empty_label.set_halign(Gtk.Align.CENTER)
            content_box.append(empty_label)
        else:
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
                    detail = Gtk.Label(label=_format_set_detail(line))
                    detail.add_css_class("dim-label")
                    detail.set_valign(Gtk.Align.CENTER)
                    row.add_suffix(detail)
                    set_list.append(row)
                group_box.append(set_list)
                content_box.append(group_box)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        clamp = Adw.Clamp(maximum_size=480, tightening_threshold=480)
        clamp.set_child(content_box)
        scroll.set_child(clamp)

        header = Adw.HeaderBar()

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(scroll)

        dialog = Adw.Dialog()
        dialog.set_title(si.workout_name)
        dialog.set_follows_content_size(False)
        dialog.set_content_width(600)
        dialog.set_content_height(560)
        dialog.set_child(toolbar)
        dialog.present(self)
