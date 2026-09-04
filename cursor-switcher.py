#!/usr/bin/env python3
"""Trocador de Cursor - seletor de temas de cursor para GNOME/Ubuntu."""

import os
import re
import shutil
import struct
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

APP_ID = "org.beicom.CursorSwitcher"
IFACE = "org.gnome.desktop.interface"

# Diretorios de temas, do mais especifico (usuario) pro mais generico (sistema).
SEARCH_DIRS = [
    Path.home() / ".icons",
    Path.home() / ".local/share/icons",
    Path("/usr/local/share/icons"),
    Path("/usr/share/icons"),
]
INSTALL_DIR = Path.home() / ".local/share/icons"

SIZES = [
    ("Padrão", 24),
    ("Pequeno", 28),
    ("Médio", 32),
    ("Médio-Grande", 38),
    ("Grande", 48),
]

# Grupos de nomes alternativos: o primeiro que existir no tema e usado no preview.
PREVIEW_CURSORS = [
    ("default", "left_ptr", "arrow", "top_left_arrow"),
    ("pointer", "hand2", "hand1", "pointing_hand"),
    ("text", "xterm", "ibeam"),
    ("wait", "watch"),
    ("not-allowed", "crossed_circle", "forbidden", "no-drop"),
]

XCURSOR_IMAGE = 0xFFFD0002


# ---------------------------------------------------------------- Xcursor ----

def parse_xcursor(path: Path, want_size: int):
    """Le um arquivo XCursor e devolve (largura, altura, bytes RGBA) do tamanho
    nominal mais proximo de want_size, ou None se nao der pra ler."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 16 or data[:4] != b"Xcur":
        return None

    header_size, _version, ntoc = struct.unpack_from("<III", data, 4)
    best = None
    for i in range(ntoc):
        off = header_size + i * 12
        if off + 12 > len(data):
            break
        ctype, subtype, pos = struct.unpack_from("<III", data, off)
        if ctype != XCURSOR_IMAGE:
            continue
        if best is None or abs(subtype - want_size) < abs(best[0] - want_size):
            best = (subtype, pos)
    if best is None:
        return None

    pos = best[1]
    if pos + 36 > len(data):
        return None
    _hs, _ct, _st, _ver, w, h, _xh, _yh, _delay = struct.unpack_from("<9I", data, pos)
    if w == 0 or h == 0 or w > 512 or h > 512:
        return None
    start = pos + 36
    end = start + w * h * 4
    if end > len(data):
        return None

    # Xcursor guarda ARGB32 little-endian (bytes B,G,R,A) com alfa pre-multiplicado.
    buf = bytearray(data[start:end])
    buf[0::4], buf[2::4] = buf[2::4], buf[0::4]  # BGRA -> RGBA
    for i in range(0, len(buf), 4):
        a = buf[i + 3]
        if a == 0:
            buf[i] = buf[i + 1] = buf[i + 2] = 0
        elif a < 255:
            buf[i] = min(255, buf[i] * 255 // a)
            buf[i + 1] = min(255, buf[i + 1] * 255 // a)
            buf[i + 2] = min(255, buf[i + 2] * 255 // a)
    return w, h, bytes(buf)


_texture_cache: dict = {}


def cursor_texture(path: Path, size: int):
    key = (str(path), size)
    if key in _texture_cache:
        return _texture_cache[key]
    parsed = parse_xcursor(path, size)
    texture = None
    if parsed:
        w, h, rgba = parsed
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(rgba), GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4
        )
        if w != size:  # normaliza pro tamanho pedido
            scale = size / max(w, h)
            pixbuf = pixbuf.scale_simple(
                max(1, round(w * scale)), max(1, round(h * scale)),
                GdkPixbuf.InterpType.BILINEAR,
            )
        texture = Gdk.MemoryTexture.new(
            pixbuf.get_width(), pixbuf.get_height(),
            Gdk.MemoryFormat.R8G8B8A8, GLib.Bytes.new(pixbuf.get_pixels()),
            pixbuf.get_rowstride(),
        )
    _texture_cache[key] = texture
    return texture


# ------------------------------------------------------------------ Temas ----

class Theme:
    def __init__(self, path: Path):
        self.path = path
        self.dir_name = path.name
        self.name = self.dir_name
        self.inherits: list = []
        self._read_index()

    def _read_index(self):
        for candidate in ("index.theme", "cursor.theme"):
            f = self.path / candidate
            if not f.is_file():
                continue
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            m = re.search(r"^\s*Name\s*=\s*(.+)$", text, re.MULTILINE)
            if m and candidate == "index.theme":
                self.name = m.group(1).strip()
            m = re.search(r"^\s*Inherits\s*=\s*(.+)$", text, re.MULTILINE)
            if m and not self.inherits:
                raw = m.group(1).strip().strip('"')
                self.inherits = [p.strip().strip('"') for p in re.split(r"[;,]", raw) if p.strip()]

    @property
    def location(self) -> str:
        return "sistema" if str(self.path).startswith("/usr") else "usuário"

    @property
    def removable(self) -> bool:
        return not str(self.path).startswith("/usr")


def find_theme_dir(dir_name: str):
    for base in SEARCH_DIRS:
        p = base / dir_name
        if (p / "cursors").is_dir():
            return p
    return None


def discover_themes() -> list:
    found = {}
    for base in SEARCH_DIRS:  # primeiro que aparece vence (usuario > sistema)
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            cursors = entry / "cursors"
            if not entry.is_dir() or not cursors.is_dir():
                continue
            try:
                if not any(cursors.iterdir()):
                    continue
            except OSError:
                continue
            if entry.name not in found:
                found[entry.name] = Theme(entry)
    return sorted(found.values(), key=lambda t: t.name.lower())


def resolve_cursor(theme: Theme, names, _depth=0):
    """Acha o arquivo de um cursor no tema, seguindo a cadeia de Inherits."""
    for n in names:
        f = theme.path / "cursors" / n
        if f.is_file():
            return f
    if _depth < 4:
        for parent_name in theme.inherits:
            parent_dir = find_theme_dir(parent_name)
            if parent_dir and parent_dir != theme.path:
                hit = resolve_cursor(Theme(parent_dir), names, _depth + 1)
                if hit:
                    return hit
    return None


# --------------------------------------------------------------- Aplicar ----

def apply_theme(theme_name: str, size: int):
    settings = Gio.Settings.new(IFACE)
    settings.set_string("cursor-theme", theme_name)
    settings.set_int("cursor-size", size)
    Gio.Settings.sync()
    # Fallback pra apps X11/XWayland que nao leem gsettings.
    default_dir = Path.home() / ".icons/default"
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "index.theme").write_text(
        "[Icon Theme]\nName=Default\nComment=Default cursor theme\n"
        f"Inherits={theme_name}\n"
    )


def current_settings():
    s = Gio.Settings.new(IFACE)
    return s.get_string("cursor-theme"), s.get_int("cursor-size")


# ------------------------------------------------------------- Instalacao ----

def install_archive(archive: Path) -> list:
    """Extrai um arquivo baixado e instala os temas de cursor que houver dentro."""
    name = archive.name.lower()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmpdir)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as t:
                t.extractall(tmpdir, filter="tar")
        else:
            raise ValueError("Formato não suportado (use .tar.gz, .tar.xz, .tar.bz2 ou .zip).")

        roots = []
        for cursors_dir in tmpdir.rglob("cursors"):
            if cursors_dir.is_dir() and any(cursors_dir.iterdir()):
                roots.append(cursors_dir.parent)
        if not roots:
            raise ValueError("Nenhum tema de cursor encontrado no arquivo.")

        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        installed = []
        for root in roots:
            dest = INSTALL_DIR / root.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(root), str(dest))
            installed.append(root.name)
        return installed


# --------------------------------------------------------------- Interface ----

CSS = """
.preview-card { padding: 10px 8px 6px 8px; }
.preview-strip { min-height: 104px; padding: 8px; border-radius: 10px;
                 background: @view_bg_color; }
flowboxchild { border-radius: 14px; }
.badge { font-size: 0.75em; font-weight: bold; padding: 1px 8px;
         border-radius: 999px; background: @accent_bg_color; color: @accent_fg_color; }
.dim { opacity: 0.55; font-size: 0.82em; }
"""


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Trocador de Cursor")
        self.set_default_size(860, 660)

        self.themes = []
        self.selected = None
        self.size = current_settings()[1]
        if self.size not in [v for _, v in SIZES]:
            self.size = 24

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        header = Adw.HeaderBar()
        install_btn = Gtk.Button(child=Adw.ButtonContent(
            icon_name="folder-download-symbolic", label="Instalar…"))
        install_btn.set_tooltip_text("Instalar um tema baixado (.tar.xz, .tar.gz, .zip)")
        install_btn.connect("clicked", self.on_install)
        header.pack_start(install_btn)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text("Recarregar lista")
        refresh.connect("clicked", lambda *_: self.reload())
        header.pack_start(refresh)

        self.apply_btn = Gtk.Button(label="Aplicar")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.set_sensitive(False)
        self.apply_btn.connect("clicked", self.on_apply)
        header.pack_end(self.apply_btn)
        view.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # ---- barra de tamanho
        sizebar = Gtk.Box(spacing=12, margin_top=12, margin_bottom=6,
                          margin_start=16, margin_end=16)
        sizebar.append(Gtk.Label(label="Tamanho", xalign=0))
        linked = Gtk.Box(css_classes=["linked"])
        self.size_buttons = {}
        group = None
        for label, value in SIZES:
            btn = Gtk.ToggleButton(label=f"{label} ({value}px)")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.set_active(value == self.size)
            btn.connect("toggled", self.on_size_toggled, value)
            linked.append(btn)
            self.size_buttons[value] = btn
        sizebar.append(linked)
        body.append(sizebar)

        self.status = Gtk.Label(xalign=0, margin_start=16, margin_end=16,
                                margin_bottom=6, css_classes=["dim"], wrap=True)
        body.append(self.status)

        # ---- grade de temas
        self.flow = Gtk.FlowBox(
            valign=Gtk.Align.START, homogeneous=True, max_children_per_line=4,
            min_children_per_line=2, column_spacing=10, row_spacing=10,
            margin_start=16, margin_end=16, margin_bottom=16,
            selection_mode=Gtk.SelectionMode.SINGLE,
        )
        self.flow.connect("selected-children-changed", self.on_selection)
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self.flow)
        body.append(scroller)
        view.set_content(body)

        self.reload()

    # ---- construcao dos cards
    def reload(self):
        applied_theme, applied_size = current_settings()
        self.themes = discover_themes()
        self.flow.remove_all()
        select_child = None

        for theme in self.themes:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                           css_classes=["card", "preview-card"])

            strip = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER, css_classes=["preview-strip"],
                            hexpand=True)
            shown = 0
            for names in PREVIEW_CURSORS:
                path = resolve_cursor(theme, names)
                if not path:
                    continue
                texture = cursor_texture(path, min(self.size, 64))
                if texture is None:
                    continue
                pic = Gtk.Picture.new_for_paintable(texture)
                pic.set_can_shrink(False)
                pic.set_halign(Gtk.Align.CENTER)
                pic.set_valign(Gtk.Align.CENTER)
                strip.append(pic)
                shown += 1
                if shown == 4:
                    break
            if shown == 0:
                strip.append(Gtk.Label(label="sem pré-visualização", css_classes=["dim"]))
            card.append(strip)

            title_row = Gtk.Box(spacing=6, margin_top=2)
            title = Gtk.Label(label=theme.name, xalign=0, hexpand=True,
                              ellipsize=3, css_classes=["heading"])
            title_row.append(title)
            if theme.dir_name == applied_theme:
                title_row.append(Gtk.Label(label="atual", css_classes=["badge"],
                                           valign=Gtk.Align.CENTER))
            card.append(title_row)
            card.append(Gtk.Label(label=f"{theme.dir_name} · {theme.location}",
                                  xalign=0, ellipsize=3, css_classes=["dim"]))

            child = Gtk.FlowBoxChild(child=card)
            child.theme = theme
            self.flow.append(child)
            if theme.dir_name == applied_theme:
                select_child = child

        if select_child:
            self.flow.select_child(select_child)
        self.status.set_label(
            f"{len(self.themes)} temas encontrados · aplicado agora: "
            f"{applied_theme} em {applied_size}px"
        )

    # ---- eventos
    def on_selection(self, *_):
        children = self.flow.get_selected_children()
        self.selected = children[0].theme if children else None
        self.apply_btn.set_sensitive(self.selected is not None)

    def on_size_toggled(self, button, value):
        if button.get_active() and value != self.size:
            self.size = value
            self.reload()

    def on_apply(self, *_):
        if not self.selected:
            return
        try:
            apply_theme(self.selected.dir_name, self.size)
        except Exception as exc:  # noqa: BLE001
            self.toasts.add_toast(Adw.Toast(title=f"Erro ao aplicar: {exc}"))
            return
        self.toasts.add_toast(Adw.Toast(
            title=f"{self.selected.name} aplicado em {self.size}px "
                  "(apps já abertos podem precisar reiniciar)"))
        self.reload()

    def on_install(self, *_):
        dialog = Gtk.FileDialog(title="Escolha o tema baixado")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter()
        f.set_name("Pacotes de cursor (.tar.gz, .tar.xz, .tar.bz2, .zip)")
        for pattern in ("*.tar.gz", "*.tgz", "*.tar.xz", "*.tar.bz2", "*.zip"):
            f.add_pattern(pattern)
        filters.append(f)
        allf = Gtk.FileFilter()
        allf.set_name("Todos os arquivos")
        allf.add_pattern("*")
        filters.append(allf)
        dialog.set_filters(filters)
        dialog.set_default_filter(f)
        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(downloads)))
        dialog.open(self, None, self._install_done)

    def _install_done(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # cancelado
        if not gfile:
            return
        try:
            installed = install_archive(Path(gfile.get_path()))
        except Exception as exc:  # noqa: BLE001
            self.toasts.add_toast(Adw.Toast(title=f"Falhou: {exc}"))
            return
        _texture_cache.clear()
        self.reload()
        self.toasts.add_toast(Adw.Toast(
            title="Instalado: " + ", ".join(installed)))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = self.props.active_window or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
