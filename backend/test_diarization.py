import wave
import struct

from app.diarization import _load_waveform, perform_speaker_diarization


def _write_test_wav(path, n_channels=1, sample_rate=16000, n_frames=1600):
    """A silent 16-bit PCM WAV, using only the stdlib -- no pydub/ffmpeg
    dependency, so this test never touches the same native-codec path the
    bug it's guarding against lives in."""
    with wave.open(str(path), "wb") as f:
        f.setnchannels(n_channels)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        frames = struct.pack("<" + "h" * (n_frames * n_channels), *([1000] * (n_frames * n_channels)))
        f.writeframes(frames)


def test_load_waveform_reads_mono_wav_without_torchcodec(tmp_path):
    wav_path = tmp_path / "mono.wav"
    _write_test_wav(wav_path, n_channels=1, sample_rate=16000, n_frames=1600)

    result = _load_waveform(str(wav_path))

    assert result["sample_rate"] == 16000
    assert result["waveform"].shape == (1, 1600)
    assert result["waveform"].dtype.is_floating_point
    assert -1.0 <= result["waveform"].max().item() <= 1.0


def test_load_waveform_reads_stereo_wav_with_correct_channel_shape(tmp_path):
    wav_path = tmp_path / "stereo.wav"
    _write_test_wav(wav_path, n_channels=2, sample_rate=8000, n_frames=500)

    result = _load_waveform(str(wav_path))

    assert result["sample_rate"] == 8000
    assert result["waveform"].shape == (2, 500)


def test_load_waveform_rejects_unsupported_sample_width(tmp_path):
    wav_path = tmp_path / "weird.wav"
    with wave.open(str(wav_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(3)  # 24-bit, unsupported
        f.setframerate(16000)
        f.writeframes(b"\x00" * 30)

    try:
        _load_waveform(str(wav_path))
        assert False, "expected ValueError for unsupported sample width"
    except ValueError as e:
        assert "sample width" in str(e)


class _FakeTurn:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _FakeAnnotation:
    """Stands in for pyannote's Annotation: only itertracks() is used downstream."""

    def __init__(self, turns):
        self._turns = turns

    def itertracks(self, yield_label=False):
        for start, end, speaker in self._turns:
            yield _FakeTurn(start, end), None, speaker


class _FakeDiarizeOutput:
    """Stands in for pyannote.audio>=4.x's DiarizeOutput wrapper, which has
    .speaker_diarization instead of being the Annotation itself."""

    def __init__(self, annotation):
        self.speaker_diarization = annotation


def _fake_pipeline_factory(result):
    def _pipeline(waveform_dict):
        assert "waveform" in waveform_dict and "sample_rate" in waveform_dict
        return result
    return _pipeline


def test_perform_speaker_diarization_handles_legacy_annotation_return(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_test_wav(wav_path, n_frames=1600)

    annotation = _FakeAnnotation([(0.0, 1.0, "SPEAKER_00"), (1.5, 2.0, "SPEAKER_01")])
    results = perform_speaker_diarization(str(wav_path), _fake_pipeline_factory(annotation))

    assert len(results) == 2
    assert {r["speaker"] for r in results} == {"SPEAKER_00", "SPEAKER_01"}


def test_perform_speaker_diarization_handles_diarize_output_wrapper(tmp_path):
    """Regression test: pyannote.audio 4.x wraps results in DiarizeOutput
    (.speaker_diarization), not an Annotation with itertracks() directly --
    calling itertracks() on it raises AttributeError if unhandled."""
    wav_path = tmp_path / "clip.wav"
    _write_test_wav(wav_path, n_frames=1600)

    annotation = _FakeAnnotation([(0.0, 1.0, "SPEAKER_00")])
    wrapped = _FakeDiarizeOutput(annotation)
    results = perform_speaker_diarization(str(wav_path), _fake_pipeline_factory(wrapped))

    assert len(results) == 1
    assert results[0]["speaker"] == "SPEAKER_00"


def test_perform_speaker_diarization_returns_empty_on_pipeline_failure(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_test_wav(wav_path, n_frames=1600)

    def broken_pipeline(_):
        raise RuntimeError("boom")

    results = perform_speaker_diarization(str(wav_path), broken_pipeline)
    assert results == []
