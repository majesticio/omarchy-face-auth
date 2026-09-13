import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('face_backend', ROOT / 'native/backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class FakeDialog:
    responses = []
    password_ok = False
    events = []

    def __init__(self, uid, mode):
        self.user = Mock(pw_name='test-user')

    def send(self, **event):
        self.events.append(event)

    def receive(self, *args):
        return self.responses.pop(0)

    def password(self, reason):
        return self.password_ok

    def close(self):
        pass


class NativeApprovalTests(unittest.TestCase):
    def setUp(self):
        FakeDialog.events = []
        FakeDialog.password_ok = False
        self.payload = dict(uid=1000, runas_uid=0, command='/usr/bin/id', argv=['id', '-u'], remaining=30)
        self.patches = [patch.object(backend, 'Dialog', FakeDialog),
                        patch.object(backend, 'settings', return_value=dict(enabled=True, screen=True, sudo=True)),
                        patch.object(backend, 'configured_user', return_value=Mock(pw_name='test-user')),
                        patch.object(backend, 'graphical_session')]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_allow_is_bound_to_current_verified_request(self):
        FakeDialog.responses = [dict(action='allow')]
        self.assertTrue(backend.approve(self.payload))
        self.assertEqual(FakeDialog.events[0]['request']['argv'], ['id', '-u'])

    def test_deny_never_runs_password_fallback(self):
        FakeDialog.password_ok = True
        FakeDialog.responses = [dict(action='deny')]
        self.assertFalse(backend.approve(self.payload))

    def test_expired_match_requires_fresh_scan(self):
        self.payload['remaining'] = 0
        FakeDialog.responses = [dict(action='allow'), dict(action='deny')]
        self.assertFalse(backend.approve(self.payload))
        self.assertIn(dict(event='expired'), FakeDialog.events)

    def test_disabled_setting_invalidates_pending_approval(self):
        FakeDialog.responses = [dict(action='allow'), dict(action='deny')]
        with patch.object(backend, 'settings', return_value=dict(enabled=False, sudo=True)):
            self.assertFalse(backend.approve(self.payload))

    def test_password_is_an_explicit_alternative(self):
        FakeDialog.password_ok = True
        FakeDialog.responses = [dict(action='use_password')]
        self.assertTrue(backend.approve(self.payload))

    def test_failed_password_does_not_authorize(self):
        FakeDialog.responses = [dict(action='use_password'), dict(action='deny')]
        self.assertFalse(backend.approve(self.payload))

    def test_unavailable_command_details_require_password(self):
        self.payload.update(password_only=True, command='', argv=[])
        FakeDialog.responses = [dict(action='allow')]
        self.assertFalse(backend.approve(self.payload))
        FakeDialog.password_ok = True
        self.assertTrue(backend.approve(self.payload))

    def test_rescan_must_succeed(self):
        FakeDialog.responses = [dict(action='rescan'), dict(action='allow'), dict(action='deny')]
        with patch.object(backend, 'enabled_for', return_value=True), patch.object(backend, 'authenticate', return_value=False):
            self.assertFalse(backend.approve(self.payload))

    def test_unexpected_reply_or_wrong_user_denied(self):
        FakeDialog.responses = [dict(action='yes')]
        self.assertFalse(backend.approve(self.payload))
        FakeDialog.responses = [dict(action='allow')]
        self.payload['uid'] = 1001
        with patch.object(backend, 'configured_user', side_effect=ValueError):
            self.assertFalse(backend.approve(self.payload))

    def test_management_never_mutates_without_password(self):
        FakeDialog.responses = [dict(action='clear', value='CLEAR'), dict(action='close')]
        with patch.object(backend, 'status', return_value={}), patch.object(backend, 'mutate') as mutation:
            backend.manage(1000)
            mutation.assert_not_called()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.policy = self.base / 'settings.json'
        self.config = self.base / 'howdy.ini'
        self.profile = self.base / 'test-user.dat'
        self.policy.write_text(json.dumps(dict(enabled=True, screen=True, sudo=True)))
        self.config.write_text('[core]\ndisabled = false\n[video]\ntimeout = 5\n')
        self.profile.write_text(json.dumps([dict(id=1, label='Fixture A'), dict(id=2, label='Fixture B')]))
        self.user = Mock(pw_name='test-user', pw_gid=1000)
        for item in [patch.object(backend, 'SETTINGS', self.policy), patch.object(backend, 'HOWDY', self.config),
                     patch.object(backend, 'MODEL_DIR', self.base), patch.object(backend, 'TRUSTED_UID', pathlib.Path(self.tmp.name).stat().st_uid),
                     patch.object(backend, 'RUNTIME', self.base),
                     patch.object(backend.os, 'fchown')]:
            item.start()
            self.addCleanup(item.stop)

    def test_disabling_preserves_profiles_and_other_preferences(self):
        before = self.profile.read_bytes()
        backend.mutate(self.user, 'disable', None)
        self.assertEqual(before, self.profile.read_bytes())
        self.assertEqual(backend.settings(), dict(enabled=False, screen=True, sudo=True))
        self.assertIn('disabled = true', self.config.read_text())

    def test_remove_one_retains_other_profile(self):
        def remove(*args, **kwargs):
            self.profile.write_text(json.dumps([dict(id=2, label='Fixture B')]))
            return Mock(returncode=0)
        with patch.object(backend.subprocess, 'run', side_effect=remove) as command:
            backend.mutate(self.user, 'remove', 1)
        self.assertEqual(command.call_args.args[0],
                         ['/usr/bin/howdy', '-U', 'test-user', '-y', 'remove', '1'])
        self.assertEqual([row['id'] for row in backend.models('test-user')], [2])
        self.assertTrue(backend.settings()['enabled'])

    def test_remove_last_disables_recognition(self):
        def remove(*args, **kwargs):
            identifier = int(args[0][-1])
            remaining = [row for row in backend.models('test-user') if row['id'] != identifier]
            if remaining:
                self.profile.write_text(json.dumps(remaining))
            else:
                self.profile.unlink()
            return Mock(returncode=0)
        with patch.object(backend.subprocess, 'run', side_effect=remove):
            backend.mutate(self.user, 'remove', 1)
            backend.mutate(self.user, 'remove', 2)
        self.assertFalse(backend.settings()['enabled'])

    def test_clearing_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            backend.mutate(self.user, 'clear', '')
        self.assertTrue(self.profile.exists())
        def clear(*args, **kwargs):
            self.profile.unlink()
            return Mock(returncode=0)
        with patch.object(backend.subprocess, 'run', side_effect=clear) as command:
            backend.mutate(self.user, 'clear', 'CLEAR')
        self.assertEqual(command.call_args.args[0],
                         ['/usr/bin/howdy', '-U', 'test-user', '-y', 'clear'])
        self.assertFalse(self.profile.exists())
        self.assertFalse(backend.settings()['enabled'])

    def test_cannot_enable_without_profile(self):
        self.profile.unlink()
        with self.assertRaises(ValueError):
            backend.mutate(self.user, 'enable', None)

    def test_failed_enrollment_preserves_upstream_atomic_file(self):
        original = self.profile.read_bytes()
        def fail(*args, **kwargs):
            raise backend.subprocess.TimeoutExpired('fixture', 25)
        with patch.object(backend.subprocess, 'run', side_effect=fail):
            with self.assertRaises(backend.subprocess.TimeoutExpired):
                backend.mutate(self.user, 'enroll', 'Glasses')
        self.assertEqual(self.profile.read_bytes(), original)

    def test_rejects_unknown_actions_and_invalid_values(self):
        for action, value in [('execute', '/bin/true'), ('sudo', 'true'), ('remove', '../other-user'),
                              ('enroll', 'Admin\u202e'), ('enroll', ' trailing ')]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                backend.mutate(self.user, action, value)

    def test_profile_metadata_is_bounded_and_unambiguous(self):
        self.profile.write_text(json.dumps([dict(id=1, label='A'), dict(id=1, label='B')]))
        with self.assertRaises(ValueError):
            backend.models('test-user')
        self.profile.write_text(json.dumps([dict(id=1, label='A\u202e')]))
        with self.assertRaises(ValueError):
            backend.models('test-user')

    def test_trusted_files_reject_symlinks_and_writable_metadata(self):
        self.policy.chmod(0o666)
        with self.assertRaises(ValueError):
            backend.settings()
        self.policy.chmod(0o644)
        link = self.base / 'linked-settings.json'
        link.symlink_to(self.policy)
        with patch.object(backend, 'SETTINGS', link), self.assertRaises(OSError):
            backend.settings()

    def test_runtime_locks_are_regular_and_not_writable(self):
        lock = self.base / 'profiles.lock'
        lock.write_bytes(b'')
        with backend.runtime_lock('profiles.lock', backend.fcntl.LOCK_SH):
            pass
        lock.chmod(0o666)
        with self.assertRaises(ValueError), backend.runtime_lock('profiles.lock', backend.fcntl.LOCK_SH):
            pass


class InstallationIdentityTests(unittest.TestCase):
    def test_identity_must_match_account_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, 'installation.json')
            uid = pathlib.Path(tmp).stat().st_uid
            path.write_text(json.dumps({'uid': uid, 'user': 'portable-user'}))
            account = Mock(pw_uid=uid, pw_name='portable-user')
            with patch.object(backend, 'INSTALLATION', path), \
                    patch.object(backend, 'TRUSTED_UID', uid), \
                    patch.object(backend.pwd, 'getpwnam', return_value=account), \
                    patch.object(backend.pwd, 'getpwuid', return_value=account):
                self.assertEqual(backend.configured_user(uid).pw_name, 'portable-user')
                with self.assertRaises(ValueError):
                    backend.configured_user(uid + 1)
                account.pw_uid = uid + 1
                with self.assertRaises(ValueError):
                    backend.installation()
                account.pw_uid = uid
                account.pw_name = 'renamed-user'
                with self.assertRaises(ValueError):
                    backend.installation()
class RealPamPasswordTests(unittest.TestCase):
    def test_native_password_callback_against_private_pam_stack(self):
        # Exercise real libpam + the compiled fixture, without host PAM changes.
        with tempfile.TemporaryDirectory() as probe:
            pathlib.Path(probe, 'probe').write_text('auth required pam_permit.so\n')
            result = backend.subprocess.run(
                [str(ROOT / 'build/pam_runner'), probe, 'probe', '', '', '', '0'],
                capture_output=True, text=True)
        if 'result:4' in result.stdout:
            self.skipTest('host PAM rejects unprivileged private configuration trees')
        library_loader = backend.C.CDLL
        pam = library_loader('libpam.so.0')
        pam.pam_start_confdir.argtypes = [backend.C.c_char_p, backend.C.c_char_p,
            backend.C.POINTER(backend.PamConversation), backend.C.c_char_p,
            backend.C.POINTER(backend.C.c_void_p)]
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, 'omarchy-face-password').write_text(
                f'auth required {ROOT / "build/pam_fixture.so"} password\naccount required pam_permit.so\n')
            class Start:
                def __call__(self, service, user, conv, handle):
                    return pam.pam_start_confdir(service, user, conv, tmp.encode(), handle)
            proxy = Mock()
            proxy.pam_start = Start()
            for name in ('pam_authenticate', 'pam_acct_mgmt', 'pam_end'):
                setattr(proxy, name, getattr(pam, name))
            def loader(name):
                return proxy if name == 'libpam.so.0' else library_loader(name)
            with patch.object(backend.C, 'CDLL', side_effect=loader):
                self.assertTrue(backend.authenticate('omarchy-face-password', 'fixture-user', 'correct-password'))
                self.assertFalse(backend.authenticate('omarchy-face-password', 'fixture-user', 'wrong-password'))
                self.assertFalse(backend.authenticate('omarchy-face-password', 'fixture-user'))
                self.assertFalse(backend.authenticate('arbitrary-service', 'fixture-user', 'correct-password'))


if __name__ == '__main__':
    unittest.main()
