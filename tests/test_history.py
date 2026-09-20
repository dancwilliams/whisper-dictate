"""Tests for the local dictation history."""

import json
import time

import numpy as np

from whisper_dictate import history


def _entry(**overrides):
    entry = {
        "raw": "so um the threat fax report",
        "cleaned": "The threatfax report.",
        "final": "The threatfax report.",
        "process_name": "olk.exe",
        "asr_backend": "whisper",
        "cleanup_backend": "s1",
        "asr_ms": 120,
        "cleanup_ms": 30,
        "cold": False,
    }
    entry.update(overrides)
    return entry


class TestRecord:
    def test_one_append_is_valid_jsonl(self, tmp_path):
        path = tmp_path / "history.jsonl"
        history.record(**_entry(), path=path, audio_dir=tmp_path / "audio")

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["final"] == "The threatfax report."
        assert row["app"] == "olk.exe"
        assert row["asr_backend"] == "whisper"
        assert row["cold"] is False

    def test_no_window_title_is_ever_stored(self, tmp_path):
        """A window title is the document you had open. It is not needed to
        improve a recognizer, so it is not recorded."""
        path = tmp_path / "history.jsonl"
        entry = history.record(**_entry(), path=path, audio_dir=tmp_path / "audio")

        assert "title" not in entry
        assert "url" not in entry
        assert "window_title" not in entry
        assert set(entry) == {
            "ts",
            "app",
            "asr_backend",
            "cleanup_backend",
            "raw",
            "cleaned",
            "final",
            "asr_ms",
            "cleanup_ms",
            "cold",
            "audio_file",
        }

    def test_appends_rather_than_overwrites(self, tmp_path):
        path = tmp_path / "history.jsonl"
        for i in range(3):
            history.record(**_entry(final=f"line {i}"), path=path, audio_dir=tmp_path / "audio")
        assert len(path.read_text(encoding="utf-8").splitlines()) == 3

    def test_audio_is_written_and_named_in_the_entry(self, tmp_path):
        audio_dir = tmp_path / "audio"
        entry = history.record(
            **_entry(),
            audio=np.zeros(1600, dtype=np.float32),
            path=tmp_path / "history.jsonl",
            audio_dir=audio_dir,
        )
        assert entry["audio_file"].endswith(".wav")
        assert (audio_dir / entry["audio_file"]).is_file()

    def test_zero_days_keeps_no_audio(self, tmp_path):
        audio_dir = tmp_path / "audio"
        entry = history.record(
            **_entry(),
            audio=np.zeros(1600, dtype=np.float32),
            audio_days=0,
            path=tmp_path / "history.jsonl",
            audio_dir=audio_dir,
        )
        assert entry["audio_file"] is None
        assert not audio_dir.exists()

    def test_an_unwritable_path_does_not_raise(self, tmp_path):
        """Losing the record must never cost the dictation."""
        path = tmp_path / "nope"
        path.mkdir()
        assert history.append({"a": 1}, path) is False


class TestSaveAudio:
    def test_writes_16_bit_mono_at_16k(self, tmp_path):
        import wave

        name = history.save_audio(np.zeros(800, dtype=np.float32), "20260919T120000", tmp_path)
        with wave.open(str(tmp_path / name), "rb") as fh:
            assert fh.getnchannels() == 1
            assert fh.getsampwidth() == 2
            assert fh.getframerate() == 16000
            assert fh.getnframes() == 800

    def test_samples_survive_the_round_trip(self, tmp_path):
        import wave

        audio = np.array([0.0, 0.5, -0.5], dtype=np.float32)
        name = history.save_audio(audio, "20260919T120001", tmp_path)
        with wave.open(str(tmp_path / name), "rb") as fh:
            back = np.frombuffer(fh.readframes(3), dtype="<i2") / 32767.0
        assert np.allclose(back, audio, atol=1e-4)

    def test_clipping_does_not_wrap(self, tmp_path):
        """Without the clip, a sample above 1.0 wraps to a loud negative."""
        import wave

        name = history.save_audio(np.array([2.0, -2.0], dtype=np.float32), "t", tmp_path)
        with wave.open(str(tmp_path / name), "rb") as fh:
            back = np.frombuffer(fh.readframes(2), dtype="<i2")
        assert back.tolist() == [32767, -32767]


class TestPruneAudio:
    def _aged(self, path, days_old):
        path.write_bytes(b"RIFF")
        old = time.time() - days_old * 86400
        import os

        os.utime(path, (old, old))

    def test_removes_only_old_files(self, tmp_path):
        self._aged(tmp_path / "old.wav", 15)
        self._aged(tmp_path / "recent.wav", 3)

        assert history.prune_audio(14, tmp_path) == 1
        assert not (tmp_path / "old.wav").exists()
        assert (tmp_path / "recent.wav").exists()

    def test_leaves_files_that_are_not_recordings(self, tmp_path):
        self._aged(tmp_path / "old.wav", 20)
        self._aged(tmp_path / "notes.txt", 20)

        history.prune_audio(14, tmp_path)
        assert (tmp_path / "notes.txt").exists()

    def test_zero_days_prunes_nothing(self, tmp_path):
        """0 means audio is not being kept at all; it does not mean delete now,
        which would throw away whatever is still on disk from before."""
        self._aged(tmp_path / "old.wav", 99)
        assert history.prune_audio(0, tmp_path) == 0
        assert (tmp_path / "old.wav").exists()

    def test_missing_directory_is_fine(self, tmp_path):
        assert history.prune_audio(14, tmp_path / "absent") == 0
