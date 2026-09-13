#!/usr/bin/python3 -I
"""Fixed-purpose root controller. Never executes the displayed sudo command.

Management starts through its dedicated pkexec action; every mutation requires
fresh password-only PAM authentication. The GUI runs as the invoking user and
talks over an inherited private socket, with no public approval endpoint.
"""
import configparser
import contextlib
import ctypes as C
import fcntl
import json
import math
import os
from pathlib import Path
import pwd
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata

BASE = Path('/usr/lib/omarchy-face-auth')
SETTINGS = Path('/etc/omarchy-face-auth/settings.json')
INSTALLATION = Path('/etc/omarchy-face-auth/installation.json')
HOWDY = Path('/etc/howdy/config.ini')
MODEL_DIR = Path('/etc/howdy/models')
RUNTIME = Path('/run/omarchy-face-auth')
TRUSTED_UID = 0
MAX_SETTINGS_BYTES = 4096
MAX_CONFIG_BYTES = 131072
MAX_MODEL_BYTES = 2 * 1024 * 1024


def trusted_bytes(path, limit):
    """Read a bounded, root-owned regular file without following symlinks."""
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != TRUSTED_UID or
                info.st_mode & 0o022 or info.st_size > limit):
            raise ValueError('Untrusted file')
        with os.fdopen(fd, 'rb', closefd=False) as source:
            data = source.read(limit + 1)
        if len(data) > limit:
            raise ValueError('File too large')
        return data
    finally:
        os.close(fd)


def trusted_text(path, limit):
    try:
        return trusted_bytes(path, limit).decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('Invalid UTF-8') from error


def valid_label(value, maximum=64):
    return (isinstance(value, str) and value == value.strip() and
            1 <= len(value) <= maximum and len(value.encode('utf-8')) <= 256 and
            not any(unicodedata.category(char).startswith('C') for char in value))


def settings():
    value = json.loads(trusted_text(SETTINGS, MAX_SETTINGS_BYTES))
    if set(value) != {'enabled', 'screen', 'sudo'} or any(type(x) is not bool for x in value.values()):
        raise ValueError('Invalid settings')
    return value


def installation():
    value = json.loads(trusted_text(INSTALLATION, MAX_SETTINGS_BYTES))
    if set(value) != {'uid', 'user'} or type(value['uid']) is not int or not isinstance(value['user'], str):
        raise ValueError('Invalid installation identity')
    if value['uid'] <= 0 or not value['user'] or len(value['user']) > 64:
        raise ValueError('Invalid installation identity')
    account = pwd.getpwnam(value['user'])
    by_uid = pwd.getpwuid(value['uid'])
    if account.pw_uid != value['uid'] or by_uid.pw_name != value['user']:
        raise ValueError('Installation identity no longer matches the account database')
    return value


def configured_user(uid):
    identity = installation()
    if uid != identity['uid']:
        raise ValueError('Face authentication is configured for another user')
    return pwd.getpwuid(uid)


def models(user):
    path = MODEL_DIR / (user + '.dat')
    try:
        raw = trusted_text(path, MAX_MODEL_BYTES)
    except FileNotFoundError:
        return []
    entries = json.loads(raw)
    if not isinstance(entries, list) or len(entries) > 20:
        raise ValueError('Invalid profiles')
    identifiers = set()
    for item in entries:
        identifier = item.get('id') if isinstance(item, dict) else None
        enrolled = item.get('time', 0) if isinstance(item, dict) else None
        if (not isinstance(item, dict) or type(identifier) is not int or
                not 0 <= identifier <= 2**31 - 1 or identifier in identifiers or
                not valid_label(item.get('label')) or type(enrolled) not in (int, float) or
                not math.isfinite(enrolled) or enrolled < 0):
            raise ValueError('Invalid profile')
        identifiers.add(identifier)
    return entries


def status(uid):
    user = configured_user(uid).pw_name
    policy = settings()
    entries = models(user)
    cfg = configparser.ConfigParser()
    cfg.read_string(trusted_text(HOWDY, MAX_CONFIG_BYTES))
    enabled = policy['enabled'] and not cfg.getboolean('core', 'disabled', fallback=True)
    device = cfg.get('video', 'device_path', fallback='')
    camera = bool(device) and Path(device).exists()
    screen_pam = Path('/etc/pam.d/omarchy-lock-face')
    sudo_pam = Path('/etc/pam.d/sudo')
    screen_installed = screen_pam.exists() and 'check-screen' in trusted_text(screen_pam, MAX_CONFIG_BYTES)
    sudo_installed = sudo_pam.exists() and 'pam_face_intent.so mark' in trusted_text(sudo_pam, MAX_CONFIG_BYTES)
    return dict(known=True, enabled=enabled, screen=enabled and policy['screen'] and screen_installed,
                sudo=enabled and policy['sudo'] and sudo_installed, confirmation=sudo_installed,
                screenPreference=policy['screen'], sudoPreference=policy['sudo'],
                camera=camera, enrolled=bool(entries), available=camera and bool(entries),
                profiles=[{k: row.get(k) for k in ('id', 'label', 'time')} for row in entries])


def atomic_write(path, data, mode=0o644, gid=0):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, 0, gid)
        with os.fdopen(fd, 'wb') as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def set_policy(policy):
    # A disabled settings gate takes effect before Howdy config is changed.
    # Enabling publishes the gate only after Howdy is ready.
    raw = (json.dumps(policy, indent=2) + '\n').encode()
    cfg = configparser.ConfigParser()
    cfg.read_string(trusted_text(HOWDY, MAX_CONFIG_BYTES))
    cfg['core']['disabled'] = 'false' if policy['enabled'] else 'true'
    import io
    buf = io.StringIO()
    cfg.write(buf)
    if not policy['enabled']:
        atomic_write(SETTINGS, raw)
    atomic_write(HOWDY, buf.getvalue().encode())
    atomic_write(SETTINGS, raw)


class PamMessage(C.Structure):
    _fields_ = [('style', C.c_int), ('message', C.c_char_p)]


class PamResponse(C.Structure):
    _fields_ = [('response', C.c_void_p), ('code', C.c_int)]


CONVERSE = C.CFUNCTYPE(C.c_int, C.c_int, C.POINTER(C.POINTER(PamMessage)),
                      C.POINTER(C.POINTER(PamResponse)), C.c_void_p)


class PamConversation(C.Structure):
    _fields_ = [('conv', CONVERSE), ('data', C.c_void_p)]


def authenticate(service, user, password=None):
    if service not in ('omarchy-face-password', 'omarchy-face-rescan'):
        return False
    pam = C.CDLL('libpam.so.0')
    libc = C.CDLL('libc.so.6')
    libc.calloc.argtypes = [C.c_size_t, C.c_size_t]
    libc.calloc.restype = C.c_void_p
    libc.strdup.argtypes = [C.c_char_p]
    libc.strdup.restype = C.c_void_p
    libc.free.argtypes = [C.c_void_p]

    @CONVERSE
    def hidden_conversation(count, messages, responses, context):
        if count < 1 or count > 16:
            return 19
        if any(messages[i].contents.style not in (1, 3, 4) for i in range(count)):
            return 19
        if password is None and any(messages[i].contents.style == 1 for i in range(count)):
            return 19
        pointer = libc.calloc(count, C.sizeof(PamResponse))
        if not pointer:
            return 5
        items = C.cast(pointer, C.POINTER(PamResponse))
        for i in range(count):
            if messages[i].contents.style == 1:
                items[i].response = libc.strdup(password.encode())
                if not items[i].response:
                    for j in range(i):
                        if items[j].response:
                            libc.free(items[j].response)
                    libc.free(pointer)
                    return 5
        responses[0] = items
        return 0

    conv = PamConversation(hidden_conversation, None)
    handle = C.c_void_p()
    pam.pam_start.argtypes = [C.c_char_p, C.c_char_p, C.POINTER(PamConversation), C.POINTER(C.c_void_p)]
    pam.pam_authenticate.argtypes = [C.c_void_p, C.c_int]
    pam.pam_acct_mgmt.argtypes = [C.c_void_p, C.c_int]
    pam.pam_end.argtypes = [C.c_void_p, C.c_int]
    result = pam.pam_start(service.encode(), user.encode(), C.byref(conv), C.byref(handle))
    if result == 0:
        result = pam.pam_authenticate(handle, 0)
    if result == 0:
        result = pam.pam_acct_mgmt(handle, 0)
    if handle:
        pam.pam_end(handle, result)
    return result == 0


def harden_process():
    """Keep secrets held by the privileged controller out of core dumps."""
    libc = C.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [C.c_int, C.c_ulong, C.c_ulong, C.c_ulong, C.c_ulong]
    libc.prctl.restype = C.c_int
    if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
        error = C.get_errno()
        raise OSError(error, os.strerror(error))


def graphical_session(uid):
    sd = C.CDLL('libsystemd.so.0')
    sd.sd_uid_get_display.argtypes = [C.c_uint, C.POINTER(C.c_void_p)]
    sd.sd_session_is_active.argtypes = [C.c_char_p]
    sd.sd_session_is_remote.argtypes = [C.c_char_p]
    sd.sd_session_get_type.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    libc = C.CDLL('libc.so.6')
    libc.free.argtypes = [C.c_void_p]
    session = C.c_void_p()
    kind = C.c_void_p()
    try:
        if sd.sd_uid_get_display(uid, C.byref(session)) < 0:
            raise RuntimeError('No graphical session')
        name = C.cast(session, C.c_char_p)
        if sd.sd_session_is_active(name) <= 0 or sd.sd_session_is_remote(name) != 0:
            raise RuntimeError('No active local session')
        locked = subprocess.check_output(['/usr/bin/loginctl', 'show-session', name.value.decode(),
                                          '--property=LockedHint', '--value'],
                                         text=True, timeout=3, env={'PATH': '/usr/bin'}).strip()
        if locked != 'no':
            raise RuntimeError('Session is locked or unavailable')
        if sd.sd_session_get_type(name, C.byref(kind)) < 0 or C.string_at(kind) != b'wayland':
            raise RuntimeError('Wayland session required')
    finally:
        libc.free(session)
        libc.free(kind)
    runtime = Path('/run/user') / str(uid)
    if runtime.stat().st_uid != uid:
        raise RuntimeError('Invalid runtime directory')
    for candidate in sorted(runtime.glob('wayland-*')):
        info = candidate.lstat()
        if stat.S_ISSOCK(info.st_mode) and info.st_uid == uid:
            return runtime, candidate.name
    raise RuntimeError('No Wayland display')


class Dialog:
    def __init__(self, uid, mode):
        self.uid = uid
        self.user = pwd.getpwuid(uid)
        runtime, display = graphical_session(uid)
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.socket = parent
        self.deadline = time.monotonic() + (115 if mode == 'approve' else 1800)
        env = dict(PATH='/usr/bin', LANG='C.UTF-8', HOME=self.user.pw_dir,
                   USER=self.user.pw_name, LOGNAME=self.user.pw_name,
                   XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY=display,
                   GDK_BACKEND='wayland', DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(runtime / 'bus'))

        def drop_privileges():
            os.initgroups(self.user.pw_name, self.user.pw_gid)
            os.setresgid(self.user.pw_gid, self.user.pw_gid, self.user.pw_gid)
            os.setresuid(uid, uid, uid)

        self.process = subprocess.Popen(['/usr/bin/python3', '-I', str(BASE / 'dialog.py'),
                                         str(child.fileno()), mode],
                                        pass_fds=(child.fileno(),), env=env, cwd='/',
                                        preexec_fn=drop_privileges, start_new_session=True,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        child.close()
        self.socket.settimeout(3)

    def send(self, **data):
        packet = json.dumps(data, ensure_ascii=True).encode()
        if len(packet) > 131072:
            raise ValueError('Message too long')
        self.socket.sendall(packet)

    def receive(self, timeout=120):
        remaining = min(timeout, self.deadline - time.monotonic())
        if remaining <= 0 or not select.select([self.socket], [], [], remaining)[0]:
            raise TimeoutError('Dialog expired')
        data, _, flags, _ = self.socket.recvmsg(131072)
        if not data or flags & socket.MSG_TRUNC:
            raise EOFError('Dialog closed')
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError('Invalid response')
        return result

    def password(self, reason):
        self.send(event='password', reason=reason)
        message = self.receive(90)
        if message.get('action') != 'password' or not isinstance(message.get('password'), str):
            return False
        password = message.pop('password')
        if not 0 < len(password) <= 1024 or '\x00' in password:
            return False
        self.send(event='busy', message='Checking password…')
        accepted = authenticate('omarchy-face-password', self.user.pw_name, password)
        del password
        return accepted

    def close(self):
        try:
            self.send(event='close')
        except (OSError, ValueError):
            pass
        self.socket.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def approve(payload):
    uid = payload.get('uid')
    args = payload.get('argv')
    try:
        configured_user(uid)
    except (KeyError, TypeError, ValueError):
        return False
    if type(payload.get('runas_uid')) is not int:
        return False
    password_only = payload.get('password_only') is True
    if not isinstance(args, list) or len(args) > 256 or any(not isinstance(arg, str) for arg in args):
        return False
    if not password_only and (not args or not isinstance(payload.get('command'), str) or not payload['command'].startswith('/')):
        return False
    remaining = payload.get('remaining', 0)
    if not isinstance(remaining, (int, float)) or not math.isfinite(remaining):
        return False
    now = time.monotonic()
    absolute = payload.get('expires_at', now + max(0, min(30, remaining)))
    if not isinstance(absolute, (int, float)) or not math.isfinite(absolute):
        return False
    expires = min(absolute, now + 30)
    dialog = Dialog(uid, 'approve')
    try:
        try:
            target = pwd.getpwuid(payload['runas_uid']).pw_name
        except KeyError:
            target = str(payload['runas_uid'])
        dialog.send(event='request', request=payload, target=target, user=dialog.user.pw_name)
        if password_only:
            return dialog.password('Command details are unavailable or too long to verify. Enter your password to authorize this sudo request.')
        dialog.send(event='verified', remaining=max(0, expires - time.monotonic()))
        while True:
            response = dialog.receive()
            action = response.get('action')
            if action == 'deny':
                return False
            if action == 'allow':
                policy = settings()
                if time.monotonic() < expires and policy['enabled'] and policy['sudo']:
                    graphical_session(uid)
                    return True
                dialog.send(event='expired')
            elif action == 'use_password':
                if dialog.password('Authorize this sudo request with your password'):
                    return True
                dialog.send(event='error', message='Password not accepted. This command has not run.')
            elif action == 'rescan':
                expires = 0
                dialog.send(event='busy', message='Looking for your face…')
                if enabled_for('sudo') and authenticate('omarchy-face-rescan', dialog.user.pw_name):
                    expires = time.monotonic() + 30
                    dialog.send(event='verified', remaining=30)
                else:
                    dialog.send(event='error', message='Face not recognized. Try again or use your password.')
            else:
                return False
    finally:
        dialog.close()


def enabled_for(scope):
    if scope not in ('screen', 'sudo'):
        return False
    policy = settings()
    if not policy['enabled'] or not policy[scope]:
        return False
    try:
        with runtime_lock('profiles.lock', fcntl.LOCK_SH | fcntl.LOCK_NB):
            pass
    except BlockingIOError:
        return False
    return True


@contextlib.contextmanager
def runtime_lock(name, operation):
    if name not in ('profiles.lock', 'approval.lock', 'manage.lock'):
        raise ValueError('Unknown lock')
    fd = os.open(RUNTIME / name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != TRUSTED_UID or
                info.st_mode & 0o022):
            raise ValueError('Untrusted lock')
        with os.fdopen(fd, 'rb', closefd=False) as lock:
            fcntl.flock(lock, operation)
            yield lock
    finally:
        os.close(fd)


def mutate(user, action, value):
    policy = settings()
    entries = models(user.pw_name)
    if action in ('enable', 'disable', 'screen', 'sudo'):
        if action == 'enable':
            if not entries:
                raise ValueError('Enroll a face profile before enabling recognition.')
            policy['enabled'] = True
        elif action == 'disable':
            policy['enabled'] = False
        else:
            if type(value) is not bool:
                raise ValueError('Invalid setting')
            policy[action] = value
        set_policy(policy)
        return 'Setting saved. It will persist after reboot.'
    if action == 'enroll':
        if not valid_label(value, 24):
            raise ValueError('Choose a profile name of 1–24 characters.')
        if len(entries) >= 5:
            raise ValueError('Remove an old profile before adding another (maximum 5).')
        subprocess.run(['/usr/bin/howdy', '-U', user.pw_name, '-y', 'add', value],
                       env={'PATH': '/usr/bin', 'LANG': 'C.UTF-8'}, cwd='/',
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=25, check=True)
        updated = models(user.pw_name)
        if len(updated) != len(entries) + 1:
            raise ValueError('Enrollment was not completed.')
        return 'Face profile enrolled. Your enable/disable setting was retained.'
    if action == 'remove':
        if type(value) is not int or not any(row['id'] == value for row in entries):
            raise ValueError('That profile no longer exists.')
        subprocess.run(['/usr/bin/howdy', '-U', user.pw_name, '-y', 'remove', str(value)],
                       env={'PATH': '/usr/bin', 'LANG': 'C.UTF-8'}, cwd='/',
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, check=True)
    elif action == 'clear':
        if value != 'CLEAR':
            raise ValueError('Clear all profiles was not confirmed.')
        subprocess.run(['/usr/bin/howdy', '-U', user.pw_name, '-y', 'clear'],
                       env={'PATH': '/usr/bin', 'LANG': 'C.UTF-8'}, cwd='/',
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, check=True)
    else:
        raise ValueError('Unsupported action')
    remaining = models(user.pw_name)
    if not remaining:
        policy['enabled'] = False
        set_policy(policy)
    return 'Profile removed.' if remaining else 'All profiles removed. Face authentication is off.'


def manage(uid):
    dialog = Dialog(uid, 'manage')
    try:
        dialog.send(event='status', status=status(uid))
        while True:
            request = dialog.receive(1800)
            action = request.get('action')
            if action in ('close', 'deny'):
                return
            if action not in ('enable', 'disable', 'screen', 'sudo', 'enroll', 'remove', 'clear'):
                return
            reasons = {'enable': 'Enable face authentication', 'disable': 'Disable face authentication',
                       'enroll': 'Enroll a new face profile', 'remove': 'Remove the selected face profile',
                       'clear': 'Clear ALL face profiles and disable face authentication',
                       'screen': 'Change face authentication for screen unlock',
                       'sudo': 'Change face authentication for sudo approval'}
            if not dialog.password(reasons[action] + ' — enter your login password'):
                dialog.send(event='status', status=status(uid), message='Password not accepted or cancelled. Nothing changed.')
                continue
            graphical_session(uid)
            try:
                with runtime_lock('profiles.lock', fcntl.LOCK_EX | fcntl.LOCK_NB):
                    dialog.send(event='busy', message='Look at the IR camera. Enrolling…' if action == 'enroll' else 'Saving…')
                    result = mutate(dialog.user, action, request.get('value'))
                dialog.send(event='status', status=status(uid), message=result)
            except ValueError as error:
                dialog.send(event='status', status=status(uid), message=str(error))
            except (OSError, subprocess.SubprocessError):
                dialog.send(event='status', status=status(uid), message='Could not complete that change. For enrollment, make sure the IR camera is free and your face is visible.')
    finally:
        dialog.close()


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ''
    if mode == 'status':
        print(json.dumps(status(os.getuid())))
        return 0
    if mode in ('check-screen', 'check-sudo'):
        try:
            identity = installation()
            pam_user = os.environ.get('PAM_USER')
            allowed = pam_user == identity['user'] if pam_user is not None else os.geteuid() == 0
            return 0 if allowed and enabled_for(mode.removeprefix('check-')) else 1
        except (KeyError, OSError, ValueError):
            return 1
    if os.geteuid() != 0:
        return 1
    os.umask(0o077)
    harden_process()
    # No privilege-bearing action relies on inherited Python/session variables.
    if mode == 'approve':
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            return 1
        with runtime_lock('approval.lock', fcntl.LOCK_EX | fcntl.LOCK_NB):
            return 0 if approve(json.loads(raw)) else 1
    if mode == 'manage':
        uid = int(os.environ.get('PKEXEC_UID', '-1'))
        configured_user(uid)
        with runtime_lock('manage.lock', fcntl.LOCK_EX | fcntl.LOCK_NB):
            manage(uid)
        return 0
    return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, EOFError, TimeoutError, RuntimeError):
        # Never log payloads, passwords, embeddings, or command arguments.
        raise SystemExit(1)
