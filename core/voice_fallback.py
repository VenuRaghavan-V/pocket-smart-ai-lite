"""
core/voice_fallback.py
----------------------
OPTIONAL module - not wired into app.py by default.

The main app uses the browser's native Web Speech API for voice input
(zero setup, works great on Chrome/Edge/Android for both English and
Tamil). This file exists so the project also satisfies a fully
server-side Speech-to-Text path using Python's `SpeechRecognition`
library, for browsers that don't support Web Speech API (e.g. Firefox
desktop) or for a future desktop/CLI client.

Deploy note (changed for the LITE build): the heavy imports are now
INSIDE the function instead of at module import time, and they are NOT
listed in requirements.txt. That way neither the local app nor the
Vercel/Render bundle pulls in SpeechRecognition/pydub/ffmpeg unless you
explicitly opt in - which is what keeps the bundle small.

Requirements to enable this on a machine/host you control:
    pip install SpeechRecognition pydub
    + ffmpeg installed on your system (for converting browser audio
      formats like webm/ogg into WAV, which SpeechRecognition needs)

To enable:
    1. Uncomment the import + route in app.py
    2. Uncomment the mic-fallback code path in static/js/script.js
"""

import io


def transcribe_audio_file(file_storage, lang_code: str = "en-IN") -> str:
    """
    Convert an uploaded browser audio blob (webm/ogg) to text.

    file_storage: a werkzeug FileStorage object (request.files['audio'])
    lang_code: 'en-IN' for English, 'ta-IN' for Tamil
    """
    # Imported here (not at module level) so the optional, heavy
    # dependencies never affect app startup or the deploy bundle size.
    import speech_recognition as sr
    from pydub import AudioSegment

    recognizer = sr.Recognizer()

    # Convert whatever format the browser sent into WAV in-memory
    audio_bytes = file_storage.read()
    audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))

    wav_buffer = io.BytesIO()
    audio_segment.export(wav_buffer, format="wav")
    wav_buffer.seek(0)

    with sr.AudioFile(wav_buffer) as source:
        audio_data = recognizer.record(source)

    try:
        return recognizer.recognize_google(audio_data, language=lang_code)
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as exc:
        raise RuntimeError(f"Speech recognition service error: {exc}") from exc
