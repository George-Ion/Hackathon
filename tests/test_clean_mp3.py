import unittest

from briefing.tts import clean_mp3


def frame(payload=b""):
    # MPEG1 Layer III, 128 kbps, 44.1 kHz, no padding, mono: 417 bytes
    body = payload + b"\x00" * (417 - 4 - len(payload))
    return bytes([0xFF, 0xFB, 0x90, 0xC4]) + body


def id3(size=20):
    return b"ID3\x04\x00\x00" + bytes([0, 0, 0, size]) + b"\x00" * size


class TestCleanMp3(unittest.TestCase):
    def test_removes_tags_and_info_frames_between_clips(self):
        clip = id3() + frame(b"\x00" * 17 + b"Info") + frame() + frame()
        cleaned = clean_mp3(clip + clip + clip)
        self.assertEqual(len(cleaned), 6 * 417)
        self.assertNotIn(b"Info", cleaned)
        self.assertNotIn(b"ID3", cleaned)

    def test_plain_audio_is_unchanged(self):
        audio = frame() * 5
        self.assertEqual(clean_mp3(audio), audio)


if __name__ == "__main__":
    unittest.main()
