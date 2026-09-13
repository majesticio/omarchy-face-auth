"""Render a fake request in a private Broadway display, never host authentication."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "approve"

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'build/native-preview'
OUTPUT.mkdir(exist_ok=True)
env = dict(os.environ, GDK_BACKEND='broadway', BROADWAY_DISPLAY=':19')
server = subprocess.Popen(['/usr/bin/gtk4-broadwayd', '-a', '127.0.0.1', '-p', '8099', ':19'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
log = open(OUTPUT / 'gtk.log', 'w')
gui = None
try:
    time.sleep(.3)
    gui = subprocess.Popen(['/usr/bin/python3', '-I', str(ROOT / 'native/dialog.py'),
                            str(child.fileno()), MODE], pass_fds=(child.fileno(),),
                           env=env, stdout=log, stderr=log)
    child.close()
    if MODE == 'approve':
        parent.send(json.dumps(dict(event='request', request=dict(
            command='/usr/bin/pacman', argv=['pacman', '-Ss', 'nvidia'],
            tty='/dev/pts/7', cwd='/home/alex'), target='root', user='alex')).encode())
        parent.send(json.dumps(dict(event='verified', remaining=30)).encode())
    else:
        parent.send(json.dumps(dict(event='status', status=dict(enabled=True, screenPreference=True,
            sudoPreference=True, profiles=[dict(id=0,label='Everyday',time=1789228800)]))).encode())
    result = subprocess.run(['/usr/bin/chromium', '--headless', '--disable-gpu',
                             '--no-first-run', '--no-default-browser-check',
                             '--user-data-dir=' + str(OUTPUT / 'chromium'),
                             '--window-size=900,760', '--timeout=8000',
                             '--screenshot=' + str(OUTPUT / (MODE + '.png')),
                             'http://127.0.0.1:8099'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
    print('Chromium exit:', result.returncode)
    print('GTK running:', gui.poll() is None)
    print((OUTPUT / 'gtk.log').read_text())
finally:
    if gui and gui.poll() is None:
        gui.terminate()
        gui.wait(timeout=3)
    parent.close()
    child.close()
    server.terminate()
    server.wait(timeout=3)
    log.close()
