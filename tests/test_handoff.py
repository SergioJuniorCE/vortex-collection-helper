import os
import tempfile
import time
import unittest

from vch.handoff import VortexLog
from vch.models import ModKey


HANDOFF = (
    '[RENDERER] handling url '
    '{"url":"nxm://skyrimspecialedition/mods/1/files/2?key=a&expires=1"}\n'
)


class VortexLogTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "vortex.log")
        self.log = VortexLog(self.path, poll=0.01)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write(self, text, mode="a"):
        with open(self.path, mode, encoding="utf-8") as handle:
            handle.write(text)

    def test_missing_file(self):
        mark = self.log.mark()
        self.assertEqual((mark.size, mark.created), (0, 0.0))
        self.assertFalse(self.log.saw_handoff(mark, ModKey(1, 2)))

    def test_detects_handoff_after_mark(self):
        self.write("old line\n")
        mark = self.log.mark()
        self.write(HANDOFF)
        self.assertTrue(self.log.saw_handoff(mark, ModKey(1, 2)))

    def test_ignores_handoff_before_mark(self):
        self.write(HANDOFF)
        mark = self.log.mark()
        self.write("unrelated\n")
        self.assertFalse(self.log.saw_handoff(mark, ModKey(1, 2)))

    def test_ignores_prefix_file_id(self):
        mark = self.log.mark()
        self.write(
            '[RENDERER] handling url {"url":"nxm://x/mods/1/files/23?key=a"}\n'
        )
        self.assertFalse(self.log.saw_handoff(mark, ModKey(1, 2)))

    def test_truncation_rescans_from_start(self):
        self.write("x" * 50)
        mark = self.log.mark()
        self.write("", mode="w")
        self.write(HANDOFF)
        self.assertTrue(self.log.saw_handoff(mark, ModKey(1, 2)))

    def test_replacement_rescans_from_start(self):
        self.write("x" * 10)
        mark = self.log.mark()
        time.sleep(0.02)
        replacement = os.path.join(self.temp_dir.name, "replacement.log")
        with open(replacement, "w", encoding="utf-8") as handle:
            handle.write("y" * 20 + "\n")
        os.replace(replacement, self.path)
        self.write(HANDOFF)
        self.assertTrue(self.log.saw_handoff(mark, ModKey(1, 2)))

    def test_none_key_never_matches(self):
        mark = self.log.mark()
        self.write(HANDOFF)
        self.assertFalse(self.log.saw_handoff(mark, None))
        self.assertFalse(self.log.wait_handoff(mark, None, seconds=10, log=lambda _: None))


if __name__ == "__main__":
    unittest.main()
