#!/usr/bin/python3 -I
"""Unprivileged native GTK interface. Decisions go only to its inherited socket.
No public IPC, shell command interpolation, authentication cache, or exec action.
"""
import json
import os
import shlex
import socket
import sys
import time
import unicodedata
import ctypes
import re
import tomllib
from pathlib import Path
# gtk4-layer-shell must interpose Wayland calls before GTK loads libwayland.
ctypes.CDLL('libgtk4-layer-shell.so.0', mode=ctypes.RTLD_GLOBAL)
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Adw, Gtk, Gdk, Gio, GLib, Gtk4LayerShell as LayerShell


def visible_text(text):
    """Render control/bidi characters visibly, so arguments cannot hide text."""
    return ''.join(c if c.isprintable() and unicodedata.category(c) != 'Cf'
                   else ('\\u%04x' % ord(c)) for c in str(text))


class FaceApplication(Adw.Application):
    def __init__(self, channel, mode):
        super().__init__(application_id='io.github.majesticio.FaceAuthentication',
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.channel = channel
        self.mode = mode
        self.ready = False
        self.busy = False
        self.deadline = 0
        self.selected = 'allow'
        self.return_down = False
        self.refreshing = False
        self.pending_status = {}
        self.blockers = []
        self.theme_signature = object()
        self.theme_provider = Gtk.CssProvider()
        self.connect('activate', self.activate)

    def send(self, action, **data):
        try:
            self.channel.send(json.dumps(dict(action=action, **data)).encode())
        except OSError:
            self.quit()

    def activate(self, app):
        self.window = Adw.ApplicationWindow(application=self)
        self.window.set_title('Authorize sudo' if self.mode == 'approve' else 'Face authentication')
        self.window.set_decorated(False)
        self.window.add_css_class('face-overlay')
        self.layer_supported = (os.environ.get('GDK_BACKEND') != 'broadway'
                                and LayerShell.is_supported())
        if not self.layer_supported and os.environ.get('GDK_BACKEND') != 'broadway':
            self.quit()
            return
        monitors = Gdk.Display.get_default().get_monitors()
        self.monitor = monitors.get_item(0) if monitors.get_n_items() else None
        geometry = self.monitor.get_geometry() if self.monitor else None
        max_height = max(260, min(660, geometry.height - 96)) if geometry else 660
        if self.layer_supported:
            self.configure_layer(self.window, self.monitor, True)
            for index in range(1, monitors.get_n_items()):
                blocker = Gtk.ApplicationWindow(application=self)
                blocker.set_decorated(False)
                blocker.add_css_class('face-overlay')
                shade = Gtk.Box()
                shade.add_css_class('face-backdrop')
                blocker.set_child(shade)
                self.configure_layer(blocker, monitors.get_item(index), False)
                self.blockers.append(blocker)
                blocker.present()
        else:
            # Private Broadway previews only; live sessions require layer shell.
            self.window.set_default_size(800, 740)
        self.window.connect('close-request', self.close_request)
        backdrop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                           halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        backdrop.add_css_class('face-backdrop')
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        outer.add_css_class('face-card')
        outer.set_size_request(min(540, geometry.width - 64) if geometry else 540, -1)
        center = Gtk.CenterBox(orientation=Gtk.Orientation.VERTICAL)
        center.set_vexpand(True)
        center.set_center_widget(outer)
        backdrop.append(center)
        if self.mode == 'manage':
            header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
            header.set_title_widget(Gtk.Label(label='Face authentication'))
            close = self.button('Close', lambda: self.close_request(self.window))
            header.pack_end(close)
            outer.append(header)
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.pages.set_vexpand(False)
        self.pages.set_vhomogeneous(False)
        outer.append(self.pages)
        self.main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(self.main, 'set_margin_' + side)(24)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(max_height - (48 if self.mode == 'manage' else 0))
        scroller.set_child(self.main)
        self.pages.add_named(scroller, 'main')
        self.headline = self.label('Preparing…', css='title-2')
        self.main.append(self.headline)
        self.description = self.label('')
        self.main.append(self.description)
        if self.mode == 'approve':
            self.build_approval()
        else:
            self.build_management()
        self.build_password()
        self.window.set_content(backdrop)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.theme_provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.refresh_theme()
        GLib.timeout_add(1000, self.refresh_theme)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.key_pressed)
        keys.connect('key-released', self.key_released)
        self.window.add_controller(keys)
        GLib.io_add_watch(self.channel.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.receive)
        GLib.timeout_add(200, self.tick)
        self.window.present()

    @staticmethod
    def configure_layer(window, monitor, keyboard):
        LayerShell.init_for_window(window)
        LayerShell.set_namespace(window, 'omarchy-face-auth')
        LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
        LayerShell.set_monitor(window, monitor)
        LayerShell.set_exclusive_zone(window, -1)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(window, edge, True)
        LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.EXCLUSIVE if keyboard else LayerShell.KeyboardMode.NONE)

    def refresh_theme(self):
        path = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'omarchy/current/theme/colors.toml'
        try:
            info = path.stat()
            signature = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if signature == self.theme_signature:
                return True
            if info.st_size > 65536:
                raise ValueError('Theme file too large')
            raw = path.read_bytes()
            palette = tomllib.loads(raw.decode())
        except (OSError, ValueError):
            signature = None
            if signature == self.theme_signature:
                return True
            palette = {}
        def color(key, fallback):
            value = palette.get(key, fallback)
            return value if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) else fallback
        bg = color('background', '#1c2026')
        fg = color('foreground', '#e7d7c6')
        accent = color('accent', '#55aaa6')
        muted = color('dark_foreground', '#8f8378')
        surface = color('lighter_background', '#292e35')
        deep = color('dark_background', '#151820')
        red = color('red', '#d6674f')
        light = palette.get('mode') == 'light'
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT if light else Adw.ColorScheme.FORCE_DARK)
        rgb = [int(accent[i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in rgb]
        luminance = sum(a*b for a,b in zip(linear, [.2126, .7152, .0722]))
        accent_text = '#111111' if luminance > .179 else '#ffffff'
        css = f'''
          @define-color accent_color {accent};
          @define-color accent_bg_color {accent};
          @define-color accent_fg_color {accent_text};
          @define-color window_bg_color {bg};
          @define-color window_fg_color {fg};
          @define-color view_bg_color {deep};
          @define-color view_fg_color {fg};
          @define-color card_bg_color {surface};
          @define-color card_fg_color {fg};
          @define-color headerbar_bg_color {bg};
          @define-color headerbar_fg_color {fg};
          @define-color destructive_color {red};
          @define-color destructive_bg_color {red};
          window.face-overlay {{ background: transparent; box-shadow: none; border-radius: 0; }}
          .face-backdrop {{ background: rgba(0,0,0,0.58); }}
          .face-card {{ background: {bg}; color: {fg}; border: 1px solid alpha({accent},0.55);
                       border-radius: 14px; box-shadow: 0 14px 48px rgba(0,0,0,0.4); }}
          .face-card headerbar {{ background: transparent; box-shadow: none; }}
          .face-card .dim-label {{ color: {muted}; opacity: 1; }}
          .face-card button {{ border-radius: 8px; min-height: 32px; }}
          .face-card button:focus-visible {{ outline: 2px solid {accent}; outline-offset: 2px; }}
          .face-card textview, .face-card textview text {{ background: {deep}; color: {fg}; }}
          .face-card .command-box {{ border-radius: 8px; border: 1px solid alpha({fg},0.12); }}
        '''
        self.theme_provider.load_from_data(css.encode())
        self.theme_signature = signature
        return True

    @staticmethod
    def label(text, css=None):
        label = Gtk.Label(label=text, xalign=0, wrap=True)
        label.set_selectable(True)
        if css:
            label.add_css_class(css)
        return label

    @staticmethod
    def button(label, callback, css=None):
        button = Gtk.Button(label=label)
        button.connect('clicked', lambda unused: callback())
        if css:
            button.add_css_class(css)
        return button

    def build_approval(self):
        self.command_view = Gtk.TextView(editable=False, cursor_visible=False,
                                        monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.command_view.set_top_margin(14)
        self.command_view.set_bottom_margin(14)
        self.command_view.set_left_margin(14)
        self.command_view.set_right_margin(14)
        command_scroll = Gtk.ScrolledWindow(min_content_height=52, max_content_height=140,
                                           propagate_natural_height=True)
        command_scroll.add_css_class('command-box')
        command_scroll.set_child(self.command_view)
        self.main.append(command_scroll)
        self.source_label = self.label('', 'dim-label')
        self.main.append(self.source_label)
        details = Gtk.Expander(label='Full command arguments')
        self.arguments = Gtk.TextView(editable=False, cursor_visible=False,
                                      monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        args_scroll = Gtk.ScrolledWindow(min_content_height=80, max_content_height=230,
                                        propagate_natural_height=True)
        args_scroll.set_child(self.arguments)
        details.set_child(args_scroll)
        self.main.append(details)
        self.countdown = self.label('', 'dim-label')
        self.main.append(self.countdown)
        buttons = Gtk.Box(spacing=12, homogeneous=True)
        self.deny = self.button('Deny', lambda: self.choose('deny'))
        self.allow = self.button('Allow once', lambda: self.choose('allow'), 'suggested-action')
        self.allow.set_sensitive(False)
        buttons.append(self.deny)
        buttons.append(self.allow)
        self.main.append(buttons)
        alternatives = Gtk.Box(spacing=12, homogeneous=True)
        self.rescan = self.button('Scan again', lambda: self.choose('rescan'))
        self.use_password = self.button('Use password instead', lambda: self.choose('use_password'))
        alternatives.append(self.rescan)
        alternatives.append(self.use_password)
        self.main.append(alternatives)
        self.hint = self.label('Enter: Allow once · ←/→: select · Escape: Deny', 'dim-label')
        self.main.append(self.hint)

    def select_approval(self, action):
        self.selected = action
        self.allow.remove_css_class('suggested-action')
        self.deny.remove_css_class('suggested-action')
        button = self.deny if action == 'deny' else self.allow
        button.add_css_class('suggested-action')
        button.grab_focus()

    def choose(self, action):
        if action == 'allow' and (not self.ready or self.busy or time.monotonic() >= self.deadline):
            return
        if action == 'deny':
            self.send('deny')
            self.quit()
            return
        self.ready = False
        self.busy = True
        self.allow.set_sensitive(False)
        self.rescan.set_sensitive(False)
        self.use_password.set_sensitive(False)
        self.send(action)

    def build_password(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      valign=Gtk.Align.CENTER)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + side)(32)
        box.append(self.label('Password required', 'title-2'))
        self.password_reason = self.label('')
        box.append(self.password_reason)
        self.password_entry = Gtk.PasswordEntry(show_peek_icon=True)
        self.password_entry.set_property('placeholder-text', 'Your login password')
        self.password_entry.connect('activate', lambda unused: self.submit_password())
        box.append(self.password_entry)
        row = Gtk.Box(spacing=12, homogeneous=True)
        row.append(self.button('Cancel', self.cancel_password))
        row.append(self.button('Authenticate', self.submit_password, 'suggested-action'))
        box.append(row)
        self.pages.add_named(box, 'password')

    def submit_password(self):
        if self.pages.get_visible_child_name() != 'password' or self.busy:
            return
        password = self.password_entry.get_text()
        self.password_entry.set_text('')
        self.busy = True
        self.send('password', password=password)
        del password

    def cancel_password(self):
        self.password_entry.set_text('')
        self.send('cancel_password')
        self.pages.set_visible_child_name('main')
        self.busy = False

    def build_management(self):
        self.master = self.button('Enable face authentication', self.toggle_master, 'suggested-action')
        self.main.append(self.master)
        group = Adw.PreferencesGroup(title='Use face authentication for')
        self.screen_switch = Adw.SwitchRow(title='Screen unlock', subtitle='F8 starts a scan; a match unlocks immediately')
        self.sudo_switch = Adw.SwitchRow(title='Sudo approval', subtitle='A match opens a command-specific approval dialog')
        self.screen_switch.connect('notify::active', lambda row, prop: self.setting_changed('screen', row))
        self.sudo_switch.connect('notify::active', lambda row, prop: self.setting_changed('sudo', row))
        group.add(self.screen_switch)
        group.add(self.sudo_switch)
        self.main.append(group)
        self.profiles = Adw.PreferencesGroup(title='Enrolled face profiles')
        self.profile_rows = []
        self.main.append(self.profiles)
        self.name_entry = Gtk.Entry(placeholder_text='New profile name (e.g. Glasses)', max_length=24)
        self.main.append(self.name_entry)
        self.enroll = self.button('Enroll face', self.request_enrollment)
        self.main.append(self.enroll)
        self.clear = self.button('Clear all profiles…', self.confirm_clear, 'destructive-action')
        self.main.append(self.clear)
        self.main.append(self.label('Changes require your password and persist after reboot. Disabling keeps profiles; removing the last profile turns face authentication off.', 'dim-label'))

    def mutation(self, action, value=None):
        if self.busy:
            return
        self.busy = True
        self.main.set_sensitive(False)
        self.send(action, value=value)

    def toggle_master(self):
        self.mutation('disable' if self.pending_status.get('enabled') else 'enable')

    def setting_changed(self, name, row):
        if not self.refreshing:
            self.mutation(name, row.get_active())

    def request_enrollment(self):
        name = self.name_entry.get_text().strip()
        if not name:
            self.description.set_text('Give the new face profile a name first.')
            self.name_entry.grab_focus()
            return
        confirmation = Adw.AlertDialog(heading='Enroll a face profile?',
                                       body='After your password is accepted, look at the IR camera. Pause any application using the camera first.')
        confirmation.add_response('cancel', 'Cancel')
        confirmation.add_response('enroll', 'Continue')
        confirmation.set_default_response('cancel')
        confirmation.connect('response', lambda unused, response: self.mutation('enroll', name) if response == 'enroll' else None)
        confirmation.present(self.window)

    def confirm_clear(self):
        confirmation = Adw.AlertDialog(heading='Clear all face profiles?',
                                       body='This removes every enrolled face profile and turns face authentication off. Password access remains available.')
        confirmation.add_response('cancel', 'Cancel')
        confirmation.add_response('clear', 'Clear all profiles')
        confirmation.set_response_appearance('clear', Adw.ResponseAppearance.DESTRUCTIVE)
        confirmation.set_default_response('cancel')
        confirmation.connect('response', lambda unused, response: self.mutation('clear', 'CLEAR') if response == 'clear' else None)
        confirmation.present(self.window)

    def update_status(self, data):
        self.pending_status = data['status']
        self.busy = False
        self.main.set_sensitive(True)
        self.pages.set_visible_child_name('main')
        self.headline.set_text('Face authentication is ' + ('on' if self.pending_status['enabled'] else 'off'))
        self.description.set_text(data.get('message') or 'Manage recognition and the faces enrolled for your account.')
        self.master.set_label('Disable face authentication' if self.pending_status['enabled'] else 'Enable face authentication')
        self.master.set_sensitive(self.pending_status['enabled'] or bool(self.pending_status['profiles']))
        self.refreshing = True
        self.screen_switch.set_active(self.pending_status['screenPreference'])
        self.sudo_switch.set_active(self.pending_status['sudoPreference'])
        self.refreshing = False
        for row in self.profile_rows:
            self.profiles.remove(row)
        self.profile_rows = []
        for entry in self.pending_status['profiles']:
            row = Adw.ActionRow(title=visible_text(entry['label']))
            stamp = time.strftime('%b %d, %Y', time.localtime(entry.get('time') or 0))
            row.set_subtitle('Enrolled ' + stamp)
            button = self.button('Remove', lambda number=entry['id']: self.mutation('remove', number))
            button.set_valign(Gtk.Align.CENTER)
            row.add_suffix(button)
            self.profiles.add(row)
            self.profile_rows.append(row)
        self.clear.set_sensitive(bool(self.profile_rows))

    def receive(self, fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            self.quit()
            return False
        try:
            packet, _, flags, _ = self.channel.recvmsg(131072)
            if not packet or flags & socket.MSG_TRUNC:
                raise ValueError('Closed')
            self.event(json.loads(packet))
        except (OSError, ValueError, KeyError, TypeError):
            self.quit()
            return False
        return True

    def event(self, data):
        event = data['event']
        if event == 'close':
            self.quit()
        elif event == 'request':
            request = data['request']
            display = [request['command']] + request['argv'][1:]
            self.command_view.get_buffer().set_text('Command details unavailable — password required' if request.get('password_only') else shlex.join([visible_text(arg) for arg in display]))
            self.arguments.get_buffer().set_text('\n'.join(f'argv[{i}] = {json.dumps(arg, ensure_ascii=True)}' for i, arg in enumerate(request['argv'])))
            self.description.set_text('Allow this command to run as ' + visible_text(data['target']) + '?')
            self.source_label.set_text('Requested by ' + visible_text(data['user']) + ' · ' + visible_text(request.get('tty', 'No terminal')) + '\nDirectory: ' + visible_text(request.get('cwd', '')))
        elif event == 'verified':
            self.pages.set_visible_child_name('main')
            self.busy = False
            self.deadline = time.monotonic() + float(data['remaining'])
            self.ready = data['remaining'] > 0
            self.headline.set_text('Face verified' if self.ready else 'Scan expired — scan again')
            self.allow.set_sensitive(self.ready)
            self.rescan.set_sensitive(True)
            self.use_password.set_sensitive(True)
            self.window.set_default_widget(self.allow)
            if self.ready:
                self.select_approval('allow')
        elif event == 'expired':
            self.expire()
        elif event == 'password':
            self.busy = False
            self.ready = False
            self.window.set_default_widget(None)
            self.password_reason.set_text(data['reason'])
            self.password_entry.set_text('')
            self.pages.set_visible_child_name('password')
            self.password_entry.grab_focus()
        elif event == 'busy':
            self.busy = True
            self.ready = False
            self.pages.set_visible_child_name('main')
            self.headline.set_text(data['message'])
            if self.mode == 'approve':
                self.allow.set_sensitive(False)
                self.countdown.set_text('')
        elif event == 'error':
            self.busy = False
            self.pages.set_visible_child_name('main')
            self.headline.set_text(data['message'])
            if self.mode == 'approve':
                self.ready = False
                self.rescan.set_sensitive(True)
                self.use_password.set_sensitive(True)
        elif event == 'status':
            self.update_status(data)

    def expire(self):
        self.ready = False
        self.busy = False
        self.headline.set_text('Scan expired — scan again')
        self.allow.set_sensitive(False)
        self.rescan.set_sensitive(True)
        self.use_password.set_sensitive(True)
        self.countdown.set_text('This command has not run.')

    def tick(self):
        if self.mode == 'approve' and self.ready:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self.expire()
            else:
                self.countdown.set_text(f'Face verification expires in {int(remaining) + 1}s · approval applies only to this request')
        return True

    def key_pressed(self, controller, key, code, modifiers):
        if key == Gdk.KEY_Escape:
            if self.pages.get_visible_child_name() == 'password' and self.mode == 'manage':
                self.cancel_password()
            else:
                self.send('deny')
                self.quit()
            return True
        if self.pages.get_visible_child_name() == 'password':
            return False
        if self.mode == 'approve' and key in (Gdk.KEY_Left, Gdk.KEY_Right):
            self.select_approval('deny' if self.selected == 'allow' else 'allow')
            return True
        if self.mode == 'approve' and key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if not self.return_down:
                self.return_down = True
                # Follow tab/mouse focus too, not only arrow selection.
                focus = self.window.get_focus()
                if focus is self.deny:
                    self.choose('deny')
                elif focus is self.rescan:
                    self.choose('rescan')
                elif focus is self.use_password:
                    self.choose('use_password')
                elif self.ready:
                    self.choose(self.selected)
            return True
        return False

    def key_released(self, controller, key, code, modifiers):
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.return_down = False

    def close_request(self, window):
        self.send('deny' if self.mode == 'approve' else 'close')
        self.quit()
        return False


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[2] not in ('approve', 'manage'):
        raise SystemExit(1)
    channel = socket.socket(fileno=int(sys.argv[1]))
    app = FaceApplication(channel, sys.argv[2])
    app.run([])
