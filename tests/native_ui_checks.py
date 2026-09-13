"""Exercise native controls on a private Broadway display, with no real PAM."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def worker(mode):
    spec = importlib.util.spec_from_file_location('face_dialog', ROOT / 'native/dialog.py')
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    sent = []
    class Channel:
        def fileno(self): return a.fileno()
        def send(self, data): sent.append(json.loads(data)); return len(data)
    app = ui.FaceApplication(Channel(), mode)
    failures = []
    def check(unused):
        try:
            if mode == 'approve':
                app.event(dict(event='request', request=dict(command='/usr/bin/id', argv=['id','-u'],
                    tty='/dev/pts/fixture', cwd='/tmp'), target='root', user='fixture'))
                app.event(dict(event='verified', remaining=30))
                assert app.window.get_default_widget() is app.allow
                app.key_pressed(None, ui.Gdk.KEY_Return, 0, 0)
                assert sent[-1] == dict(action='allow')
                app.key_released(None, ui.Gdk.KEY_Return, 0, 0)
                app.event(dict(event='verified', remaining=0))
                count = len(sent)
                app.key_pressed(None, ui.Gdk.KEY_Return, 0, 0)
                assert len(sent) == count  # expired Enter never approves
                app.key_released(None, ui.Gdk.KEY_Return, 0, 0)
                app.event(dict(event='password', reason='Fixture password check'))
                app.password_entry.set_text('synthetic-test-secret')
                app.submit_password()
                assert sent[-1]['action'] == 'password'
                assert app.password_entry.get_text() == ''
                app.event(dict(event='verified', remaining=30))
                app.key_pressed(None, ui.Gdk.KEY_Left, 0, 0)
                assert app.deny.has_css_class('suggested-action')
                assert not app.allow.has_css_class('suggested-action')
                app.key_pressed(None, ui.Gdk.KEY_Return, 0, 0)
                assert sent[-1] == dict(action='deny')
                assert ui.visible_text('a\n\u202eb') == 'a\\u000a\\u202eb'
            else:
                app.event(dict(event='status', status=dict(enabled=True, screenPreference=True,
                    sudoPreference=True, profiles=[dict(id=3,label='Fixture',time=0)])))
                assert len(app.profile_rows) == 1 and not sent
                app.screen_switch.set_active(False)
                assert sent == [dict(action='screen', value=False)]
        except Exception as error:
            failures.append(repr(error))
        app.quit()
    app.connect('activate', check)
    app.run([])
    a.close(); b.close()
    if failures:
        raise AssertionError(failures)
    print(mode + ': native keyboard and control checks passed')


if len(sys.argv) == 3 and sys.argv[1] == 'worker':
    worker(sys.argv[2])
else:
    import tempfile
    with tempfile.TemporaryDirectory() as runtime:
        env = dict(os.environ, XDG_RUNTIME_DIR=runtime, GDK_BACKEND='broadway',
                   BROADWAY_DISPLAY=':20', GSETTINGS_BACKEND='memory')
        server = subprocess.Popen(
            ['/usr/bin/gtk4-broadwayd', '-a', '127.0.0.1', '-p', '8100', ':20'],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(.2)
            for mode in ('approve', 'manage'):
                subprocess.run(['/usr/bin/python3', str(Path(__file__).resolve()), 'worker', mode],
                               env=env, check=True, timeout=10)
        finally:
            server.terminate()
            server.wait(timeout=3)
