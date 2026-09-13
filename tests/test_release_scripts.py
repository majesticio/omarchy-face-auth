import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReleaseScriptTests(unittest.TestCase):
    def test_update_uses_one_fixed_root_entrypoint(self):
        update = (ROOT / 'update').read_text()
        sudo_lines = [line.strip() for line in update.splitlines() if line.strip().startswith('sudo ')]
        self.assertEqual(sudo_lines, [
            'sudo /usr/lib/omarchy-face-auth/update-launcher "$(id -un)" "$(id -u)" "$PWD"'
        ])

    def test_update_transaction_carries_pam_and_status_inputs(self):
        launcher = (ROOT / 'scripts/update-launcher').read_text()
        transaction = (ROOT / 'scripts/update-system').read_text()
        for relative in ('pam/omarchy-face-password', 'pam/omarchy-face-rescan',
                         'pam/omarchy-lock-face'):
            self.assertIn(relative, launcher)
            self.assertIn(relative, transaction)
        self.assertIn('backend.py sync-status', transaction)

    def test_fresh_install_installs_update_entrypoint(self):
        installer = (ROOT / 'install').read_text()
        transaction = (ROOT / 'scripts/install-system').read_text()
        self.assertIn('scripts/update-launcher', installer)
        self.assertIn('/usr/lib/omarchy-face-auth/update-launcher', transaction)
        self.assertIn('backend.py sync-status', transaction)


if __name__ == '__main__':
    unittest.main()
