#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import soundstage  # noqa: E402


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.contains = soundstage.CLASS_CONTAINS
        self.classes = {c.lower() for c in soundstage.CLASSES}
        self.binaries = {b.lower() for b in soundstage.BINARIES}

    def match(self, klass, pid=0):
        return soundstage.is_media_client(
            {"class": klass, "pid": pid},
            self.contains,
            self.classes,
            self.binaries,
        )

    def test_youtube_webapp(self):
        self.assertTrue(self.match("chrome-youtube.com__-Default"))

    def test_apple_music_webapp(self):
        self.assertTrue(self.match("chrome-music.apple.com__-Default"))

    def test_spotify_webapp(self):
        self.assertTrue(self.match("brave-open.spotify.com__-Default"))

    def test_spotify_native_class(self):
        self.assertTrue(self.match("Spotify"))

    def test_mpv_class(self):
        self.assertTrue(self.match("mpv"))

    def test_vlc_class(self):
        self.assertTrue(self.match("org.videolan.VLC"))

    def test_generic_chromium_is_ignored(self):
        self.assertFalse(self.match("chromium"))

    def test_chatgpt_webapp_is_ignored(self):
        self.assertFalse(self.match("chrome-chatgpt.com__-Default"))

    def test_discord_webapp_is_ignored(self):
        self.assertFalse(self.match("chrome-discord.com__-Default"))

    def test_label_youtube_music_before_youtube(self):
        self.assertEqual(
            soundstage.label_for({"class": "chrome-music.youtube.com__-Default"}),
            "YouTube Music",
        )
        self.assertEqual(
            soundstage.label_for({"class": "chrome-youtube.com__-Default"}),
            "YouTube",
        )

    def test_label_apple_music(self):
        self.assertEqual(
            soundstage.label_for({"class": "chrome-music.apple.com__-Default"}),
            "Apple Music",
        )


class SinkTests(unittest.TestCase):
    def test_classify_internal_and_hdmi(self):
        analog, hdmi = soundstage.classify_sinks(
            [
                {
                    "name": "alsa_output.pci-0.analog-stereo",
                    "ports": [],
                    "properties": {
                        "device.form_factor": "internal",
                        "device.profile.name": "analog-stereo",
                    },
                },
                {
                    "name": "alsa_output.pci-1.hdmi-stereo",
                    "ports": [{"availability": "available"}],
                    "properties": {"device.profile.name": "hdmi-stereo"},
                },
            ]
        )
        self.assertEqual(analog, "alsa_output.pci-0.analog-stereo")
        self.assertEqual(hdmi, "alsa_output.pci-1.hdmi-stereo")

    def test_unavailable_hdmi_is_skipped(self):
        analog, hdmi = soundstage.classify_sinks(
            [
                {
                    "name": "alsa_output.pci-1.hdmi-stereo",
                    "ports": [{"availability": "not available"}],
                    "properties": {"device.profile.name": "hdmi-stereo"},
                }
            ]
        )
        self.assertIsNone(analog)
        self.assertIsNone(hdmi)

    def test_laptop_sink_prefers_default_unless_hdmi(self):
        self.assertEqual(
            soundstage.laptop_sink("analog", "hdmi", "virtual-tuned"),
            "virtual-tuned",
        )
        self.assertEqual(
            soundstage.laptop_sink("analog", "hdmi", "hdmi"),
            "analog",
        )

    def test_unplugged_hdmi_does_not_stay_default(self):
        self.assertEqual(
            soundstage.laptop_sink(
                "analog",
                None,
                "alsa_output.pci-1.hdmi-stereo",
                hdmi_usable=False,
            ),
            "analog",
        )

    def test_has_external_monitor(self):
        monitors = [
            {"name": "eDP-1", "disabled": False},
            {"name": "HDMI-A-1", "disabled": False},
        ]
        self.assertTrue(soundstage.has_external_monitor(monitors, "eDP-1"))
        self.assertFalse(
            soundstage.has_external_monitor(
                [{"name": "eDP-1", "disabled": False}], "eDP-1"
            )
        )
        self.assertFalse(
            soundstage.has_external_monitor(
                [
                    {"name": "eDP-1", "disabled": False},
                    {"name": "HDMI-A-1", "disabled": True},
                ],
                "eDP-1",
            )
        )

    def test_reclaim_default_when_display_gone(self):
        self.assertTrue(
            soundstage.should_reclaim_default(
                "alsa_output.pci-1.hdmi-stereo",
                "analog",
                "alsa_output.pci-1.hdmi-stereo",
                False,
            )
        )
        self.assertFalse(
            soundstage.should_reclaim_default(
                "alsa_output.pci-1.hdmi-stereo",
                "analog",
                "alsa_output.pci-1.hdmi-stereo",
                True,
            )
        )
        self.assertFalse(
            soundstage.should_reclaim_default("analog", "analog", "hdmi", False)
        )


class DescendantsTests(unittest.TestCase):
    def test_walks_tree(self):
        children = {1: [2, 3], 2: [4], 3: []}
        self.assertEqual(soundstage.descendants(1, children), {1, 2, 3, 4})
        self.assertEqual(soundstage.descendants(3, children), {3})


class PreferExternalTests(unittest.TestCase):
    def test_hdmi_wins_over_later_laptop(self):
        hdmi = ("hdmi-sink", "YouTube", "HDMI-A-1")
        laptop = ("analog", "YouTube", "eDP-1")
        self.assertEqual(
            soundstage.prefer_external(hdmi, laptop, "hdmi-sink"),
            hdmi,
        )
        self.assertEqual(
            soundstage.prefer_external(laptop, hdmi, "hdmi-sink"),
            hdmi,
        )


if __name__ == "__main__":
    unittest.main()
