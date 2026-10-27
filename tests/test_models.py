import unittest

from vch.models import ClickResult, HookState, ModKey, Prompt


class ModKeyTests(unittest.TestCase):
    def test_nxm_url(self):
        key = ModKey.from_url("nxm://skyrimspecialedition/mods/123/files/456?key=a")
        self.assertEqual(key, ModKey(123, 456))

    def test_web_url_with_file_id(self):
        key = ModKey.from_url(
            "https://www.nexusmods.com/skyrimspecialedition/mods/123"
            "?tab=files&file_id=456"
        )
        self.assertEqual(key, ModKey(123, 456))

    def test_web_url_without_file_id(self):
        key = ModKey.from_url(
            "https://www.nexusmods.com/skyrimspecialedition/mods/123"
        )
        self.assertIsNone(key)

    def test_trailing_slash(self):
        key = ModKey.from_url(
            "https://www.nexusmods.com/skyrimspecialedition/mods/123/"
            "?tab=files&file_id=456"
        )
        self.assertEqual(key, ModKey(123, 456))

    def test_log_fragment_matches_exact_file(self):
        key = ModKey(1, 12)
        line = '[RENDERER] handling url {"url":"nxm://x/mods/1/files/12?key=a"}'
        self.assertTrue(key.matches_log_line(line))

    def test_log_fragment_rejects_longer_file_id(self):
        key = ModKey(1, 12)
        line = '[RENDERER] handling url {"url":"nxm://x/mods/1/files/123?key=a"}'
        self.assertFalse(key.matches_log_line(line))

    def test_str(self):
        self.assertEqual(str(ModKey(1, 2)), "1/2")


class PromptTests(unittest.TestCase):
    def test_from_raw(self):
        prompt = Prompt.from_raw(
            {
                "hasPrompt": True,
                "index": 3,
                "total": 10,
                "modName": "Example",
                "text": "Download mod Example by Author",
            }
        )
        self.assertTrue(prompt.has_prompt)
        self.assertEqual(prompt.index, 3)
        self.assertEqual(prompt.total, 10)
        self.assertEqual(prompt.mod_name, "Example")

    def test_from_raw_rejects_non_dict(self):
        self.assertFalse(Prompt.from_raw(None).has_prompt)
        self.assertFalse(Prompt.from_raw("[]").has_prompt)


class HookStateTests(unittest.TestCase):
    def test_usable(self):
        self.assertTrue(HookState.from_raw("installed").usable)
        self.assertTrue(HookState.from_raw("already").usable)
        self.assertFalse(HookState.from_raw("no-api").usable)
        self.assertFalse(HookState.from_raw("unexpected").usable)


class ClickResultTests(unittest.TestCase):
    def test_none(self):
        self.assertFalse(ClickResult.from_raw("none").clicked)
        self.assertFalse(ClickResult.from_raw(None).clicked)

    def test_plain_click(self):
        self.assertTrue(ClickResult.from_raw("clicked").clicked)

    def test_label(self):
        result = ClickResult.from_raw("clicked:Finish")
        self.assertTrue(result.clicked)
        self.assertEqual(result.label, "Finish")


if __name__ == "__main__":
    unittest.main()
