from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GObject, Gtk


def set_accessible_label(widget: Gtk.Widget, label: str) -> None:
    """Expose a short name to assistive tech (icon-only buttons, images, etc.)."""
    v = GObject.Value()
    v.init(GObject.TYPE_STRING)
    v.set_string(label)
    widget.update_property([Gtk.AccessibleProperty.LABEL], [v])


def style_header_icon_button(
    button: Gtk.Button,
    *,
    tooltip: str,
    accessible_name: str,
) -> None:
    """GNOME header-bar icon buttons: flat style, tooltip, and accessible name."""
    button.add_css_class("flat")
    button.set_tooltip_text(tooltip)
    set_accessible_label(button, accessible_name)


def create_header_button(icon_name: str, *, tooltip: str, accessible_name: str) -> Gtk.Button:
    """Create a flat icon-only header-bar button."""
    btn = Gtk.Button()
    btn.set_icon_name(icon_name)
    style_header_icon_button(btn, tooltip=tooltip, accessible_name=accessible_name)
    return btn


def create_boxed_listbox() -> Gtk.ListBox:
    """Create a standard boxed-list ListBox with no selection."""
    lb = Gtk.ListBox()
    lb.set_selection_mode(Gtk.SelectionMode.NONE)
    lb.add_css_class("boxed-list")
    return lb


def present_dialog(dialog: Adw.AlertDialog, anchor: Gtk.Widget) -> None:
    root = anchor.get_root()
    dialog.present(root if isinstance(root, Gtk.Widget) else None)


def clear_container(container: Gtk.Widget) -> None:
    child = container.get_first_child()
    while child is not None:
        container.remove(child)
        child = container.get_first_child()


def set_margins(
    widget: Gtk.Widget,
    *,
    all: int | None = None,
    top: int | None = None,
    bottom: int | None = None,
    start: int | None = None,
    end: int | None = None,
) -> None:
    if all is not None:
        top = bottom = start = end = all
    if top is not None:
        widget.set_margin_top(top)
    if bottom is not None:
        widget.set_margin_bottom(bottom)
    if start is not None:
        widget.set_margin_start(start)
    if end is not None:
        widget.set_margin_end(end)
