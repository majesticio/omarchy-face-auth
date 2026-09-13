"""Uses Linux PAM with a private config directory; no host PAM files or camera."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'build/pam_fixture.so'
RUNNER = ROOT / 'build/pam_runner'


class PamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Linux-PAM 1.7.2 rejects non-root confdir trees. Keep this suite
        # host-independent instead of weakening ownership or touching /etc.
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, 'probe').write_text('auth required pam_permit.so\n')
            result = subprocess.run([str(RUNNER), tmp, 'probe', '', '', '', '0'],
                                    capture_output=True, text=True)
        if 'result:4' in result.stdout:
            raise unittest.SkipTest('host PAM rejects unprivileged private configuration trees')

    def run_stack(self, stack, answer='yes', password='', service='sudo', rhost='', delay=0):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, service).write_text(stack)
            result = subprocess.run([str(RUNNER), tmp, service, answer, password, rhost, str(delay)],
                                    capture_output=True, text=True, timeout=20)
        self.assertIn('result:', result.stdout, result.stderr)
        return result.returncode == 0, result.stdout

    def test_screen_stack_unlocks_on_match_without_confirmation(self):
        source = (ROOT / 'pam/omarchy-lock-face').read_text()
        stack = '\n'.join(line for line in source.splitlines()
                          if line.startswith('auth ') and 'pam_faillock' not in line)
        stack = stack.replace('pam_howdy.so', f'{FIXTURE} recognize') + '\n'
        stack = stack.replace('pam_exec.so quiet /usr/lib/omarchy-face-auth/backend.py check-screen', f'{FIXTURE} recognize')
        ok, log = self.run_stack(stack, service='omarchy-lock-face', answer='')
        self.assertTrue(ok)
        self.assertNotIn('Confirm screen unlock?', log)
        self.assertFalse(self.run_stack(stack.replace(' recognize', ' reject'), service='omarchy-lock-face')[0])
        self.assertFalse(self.run_stack(stack.replace(' recognize', ' ignore'), service='omarchy-lock-face')[0])

    def dialog_stack(self, face='recognize', gate='recognize', marker='recognize'):
        source = (ROOT / 'pam/sudo.dialog-prefix').read_text()
        source = '\n'.join(line for line in source.splitlines() if 'pam_faillock' not in line)
        source = source.replace('pam_face_intent.so reset', f'{FIXTURE} ignore')
        source = source.replace('pam_face_intent.so mark', f'{FIXTURE} {marker}')
        source = source.replace('pam_howdy.so', f'{FIXTURE} {face}')
        source = source.replace('pam_exec.so quiet /usr/lib/omarchy-face-auth/backend.py check-sudo', f'{FIXTURE} {gate}')
        return source + f'\nauth required {FIXTURE} password\n'

    def test_dialog_stack_needs_match_and_working_approval_marker(self):
        self.assertTrue(self.run_stack(self.dialog_stack())[0])
        for face, gate, marker in [('reject', 'recognize', 'recognize'),
                                   ('recognize', 'reject', 'recognize'),
                                   ('recognize', 'recognize', 'ignore')]:
            stack = self.dialog_stack(face, gate, marker)
            self.assertFalse(self.run_stack(stack)[0])
            self.assertTrue(self.run_stack(stack, password='correct-password')[0])

    def test_real_marker_without_sudo_audit_plugin_falls_back(self):
        stack = self.dialog_stack(marker='ignore').replace(f'{FIXTURE} ignore\nauth required {FIXTURE} password',
            f'{ROOT / "build/pam_face_intent.so"} mark\nauth required {FIXTURE} password')
        self.assertFalse(self.run_stack(stack)[0])
        self.assertTrue(self.run_stack(stack, password='correct-password')[0])

    def test_dialog_stack_remote_request_uses_password(self):
        stack = self.dialog_stack()
        self.assertFalse(self.run_stack(stack, rhost='remote.example')[0])
        self.assertTrue(self.run_stack(stack, rhost='remote.example', password='correct-password')[0])


if __name__ == '__main__':
    unittest.main()
