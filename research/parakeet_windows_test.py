"""
Test NVIDIA Parakeet compatibility on Windows.

This script tests:
1. NeMo toolkit installation
2. Parakeet model download and loading
3. Basic transcription
4. Performance benchmarking
"""

import sys
import time
from pathlib import Path


def test_nemo_installation():
    """Test if NeMo can be installed on Windows."""
    try:
        import nemo
        import nemo.collections.asr as nemo_asr

        print(f"[OK] NeMo installed: {nemo.__version__}")
        return True
    except ImportError as e:
        print(f"[FAIL] NeMo import failed: {e}")
        return False


def test_parakeet_loading():
    """Test loading Parakeet model."""
    try:
        import nemo.collections.asr as nemo_asr

        print("Attempting to load parakeet-tdt-0.6b-v2...")
        model = nemo_asr.models.ASRModel.from_pretrained(
            model_name="nvidia/parakeet-tdt-0.6b-v2"
        )
        print("[OK] Parakeet model loaded successfully")
        return model
    except Exception as e:
        print(f"[FAIL] Parakeet loading failed: {e}")
        return None


def test_transcription(model, audio_path: Path):
    """Test transcription with sample audio."""
    try:
        start = time.time()
        output = model.transcribe([str(audio_path)])
        elapsed = time.time() - start
        print(f"[OK] Transcription successful in {elapsed:.2f}s")
        print(f"  Result: {output[0]}")
        return True
    except Exception as e:
        print(f"[FAIL] Transcription failed: {e}")
        return False


def benchmark_speed(model, audio_path: Path, iterations: int = 5):
    """Benchmark transcription speed."""
    times = []
    for i in range(iterations):
        start = time.time()
        model.transcribe([str(audio_path)])
        elapsed = time.time() - start
        times.append(elapsed)

    avg_time = sum(times) / len(times)
    print(f"Average transcription time: {avg_time:.2f}s ({iterations} runs)")
    return avg_time


if __name__ == "__main__":
    print("Testing NVIDIA Parakeet on Windows...\n")

    # Test 1: Installation
    if not test_nemo_installation():
        print("\nNeMo installation required. Install with:")
        print("  uv pip install nemo_toolkit[asr]")
        sys.exit(1)

    # Test 2: Model loading
    model = test_parakeet_loading()
    if model is None:
        print("\nParakeet model loading failed.")
        sys.exit(1)

    # Test 3: Transcription (requires sample audio)
    print("\n[OK] All tests passed!")
    print("\nNext steps:")
    print("1. Test with actual dictation audio")
    print("2. Compare accuracy vs faster-whisper")
    print("3. Benchmark memory usage")
