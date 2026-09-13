import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'scripts/detect-ir-camera'
loader = importlib.machinery.SourceFileLoader('detect_ir_camera', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
camera = importlib.util.module_from_spec(spec)
loader.exec_module(camera)


class CameraDetectionTests(unittest.TestCase):
    def test_accepts_greyscale_ir_formats(self):
        output = "[0]: 'GREY'\n[1]: 'Y16 '\n"
        self.assertTrue(camera.greyscale_only(output))

    def test_rejects_rgb_and_mixed_capture_nodes(self):
        self.assertFalse(camera.greyscale_only("[0]: 'MJPG'\n"))
        self.assertFalse(camera.greyscale_only("[0]: 'GREY'\n[1]: 'YUYV'\n"))
        self.assertFalse(camera.greyscale_only(''))


if __name__ == '__main__':
    unittest.main()
