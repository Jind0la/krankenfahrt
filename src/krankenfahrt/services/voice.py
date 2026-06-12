"""Voice transcription service using faster-whisper (local CPU)."""

from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_whisper_model = None


async def transcribe_voice(audio_bytes: bytes, model_size: str = "small") -> str:
    """Transcribe German voice message to text using local Whisper model."""
    global _whisper_model

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("faster-whisper not installed, returning empty")
        return ""

    if _whisper_model is None:
        from ..config import config

        cache_dir = config.WHISPER_CACHE_DIR
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

        _whisper_model = WhisperModel(
            model_size or config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type="int8",
            download_root=cache_dir,
        )
        logger.info(f"Loaded Whisper model '{model_size or config.WHISPER_MODEL}' from {cache_dir}")

        # Warmup: transcribe 1s of silence to eliminate JIT compilation penalty
        try:
            import numpy as np
            warmup_audio = np.zeros(16000, dtype=np.float32)
            _whisper_model.transcribe(warmup_audio, language="de", beam_size=3)
            logger.info("Whisper model warmup complete")
        except Exception:
            logger.warning("Model warmup failed — first transcription may be slow", exc_info=True)

    # faster-whisper expects file path or numpy array
    # For bytes, we write to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_bytes)
        temp_path = f.name

    try:
        segments, info = _whisper_model.transcribe(temp_path, language="de", beam_size=5)
        text = " ".join(seg.text for seg in segments)
        logger.debug(f"Transcribed ({info.language}, {info.duration:.1f}s): {text[:100]}...")
        return text.strip()
    finally:
        Path(temp_path).unlink(missing_ok=True)
