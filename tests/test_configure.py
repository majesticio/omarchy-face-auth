import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('configure', ROOT / 'scripts/configure.py')
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class ConfigurationTests(unittest.TestCase):
    def test_pam_block_follows_header_and_is_not_repeatable(self):
        result = configure.sudo_pam('#%PAM-1.0\nauth include system-auth\n', 'auth optional fixture.so\n')
        self.assertTrue(result.startswith('#%PAM-1.0\n' + configure.PAM_BEGIN))
        self.assertIn('auth include system-auth', result)
        with self.assertRaises(ValueError):
            configure.sudo_pam(result, 'auth optional fixture.so\n')

    def test_sudo_plugins_preserve_existing_configuration(self):
        original = 'Path askpass /usr/bin/askpass\n'
        result = configure.sudo_conf(original)
        self.assertTrue(result.startswith(original))
        self.assertIn('Plugin face_approval /usr/lib/security/pam_face_intent.so', result)

    def test_sudo_plugins_do_not_duplicate_existing_core_roles(self):
        original = 'Plugin custom_policy custom.so\nPlugin custom_io custom.so\nPlugin custom_audit custom.so\n'
        result = configure.sudo_conf(original)
        self.assertNotIn('sudoers_policy', result)
        self.assertNotIn('sudoers_io', result)
        self.assertNotIn('sudoers_audit', result)
        self.assertIn('Plugin face_audit', result)

    def test_howdy_device_is_validated_and_disabled_until_commit(self):
        original = '[core]\ndisabled = false\n[video]\ndevice_path = none\n'
        result = configure.howdy_config(original, '/dev/v4l/by-path/camera')
        self.assertIn('disabled = true', result)
        self.assertIn('device_path = /dev/v4l/by-path/camera', result)
        with self.assertRaises(ValueError):
            configure.howdy_config(original, '/tmp/fake-camera')


if __name__ == '__main__':
    unittest.main()
