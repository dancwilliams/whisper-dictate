# Transcription Optimization Guide

## Voice Activity Detection (VAD)

VAD filters silence and background noise before transcription, preventing hallucinations.

**Note:** VAD is disabled by default for backward compatibility. Enable it in Settings → Advanced transcription if you want to try it.

### When to Enable VAD

- Recording in noisy environments
- Audio contains long pauses
- Experiencing hallucinations (repeated phrases)

### When to Disable VAD

- Very clean audio (studio quality)
- Short, continuous speech
- VAD is cutting off syllables

### Tuning VAD Parameters

**Threshold** (0.3-0.8):
- Higher = more strict (only clear speech)
- Lower = more permissive (captures more)
- Default: 0.5

**Speech Padding** (200-800ms):
- Extra time before/after detected speech
- Increase if words are being cut off
- Default: 400ms

## Hallucination Prevention

Three thresholds work together to detect and reject hallucinations:

1. **Compression Ratio** (default: 2.4)
   - Detects repetitive text
   - Increase if getting stuck in loops

2. **Log Probability** (default: -1.0)
   - Filters low-confidence segments
   - More negative = more permissive

3. **No Speech** (default: 0.6)
   - Detects silence/background noise
   - Increase if hallucinating on silence

## Initial Prompts

Improve accuracy for specific domains:

- "Technical discussion about Python, APIs, and cloud computing."
- "Medical terminology including diagnosis, treatment, and medications."
- "Legal document with contract terms and clauses."

**Note**: Only affects first 30 seconds of transcription.

## Model Selection

**For Accuracy**: large-v3 or large-v3-turbo
**For Speed**: small or medium
**For Balance**: large-v3-turbo (recommended)

## Troubleshooting

**Hallucinations on silence**:
- Enable VAD
- Increase no_speech_threshold to 0.7

**Words cut off**:
- Increase VAD speech_pad_ms to 600-800
- Decrease VAD threshold to 0.4

**Poor accuracy on accents**:
- Try large-v3-turbo model
- Add initial prompt with expected terminology
- Increase beam_size to 10

**Slow transcription**:
- Use smaller model (small or medium)
- Disable word_timestamps
- Reduce beam_size to 1 (less accurate)
