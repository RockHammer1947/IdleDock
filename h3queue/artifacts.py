"""Bounded, provider-independent artifact checks; technical acceptance only."""
import array
import json
import math
import sys
import wave
from pathlib import Path
from .store import digest
from .system_tools import require_tool


def audio_metadata(path):
    with wave.open(str(path), 'rb') as audio:
        channels, rate, frames, width = audio.getnchannels(), audio.getframerate(), audio.getnframes(), audio.getsampwidth()
        if width != 2 or channels not in (1, 2) or not 8000 <= rate <= 192000 or frames <= rate/10:
            raise ValueError('Expected nonempty PCM16 WAV, mono/stereo, 8–192 kHz')
        count = peak = 0
        while chunk := audio.readframes(65536):
            values = array.array('h', chunk)
            if sys.byteorder != 'little':values.byteswap()
            count += len(values)
            peak = max(peak, max((abs(v) for v in values), default=0))
        if count != frames*channels:raise ValueError('Truncated WAV')
        if peak < 2:raise ValueError('Silent WAV')
        return {'audio_seconds': frames/rate, 'sample_rate': rate, 'channels': channels}


def verify(context, path, kind):
    path = Path(path).resolve()
    if not path.is_relative_to(context.out.resolve()) or not path.is_file() or path.stat().st_size == 0:
        raise ValueError('Output must be a nonempty file inside this attempt')
    metadata = {}
    if kind == 'audio':
        metadata = audio_metadata(path)
    elif kind == 'json':
        if path.stat().st_size > 16*1024**2:raise ValueError('JSON output exceeds 16 MiB')
        json.loads(path.read_text(), parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    elif kind == 'video':
        ff = require_tool('ffmpeg')
        fp = require_tool('ffprobe')
        context.run([str(ff), '-v', 'error', '-threads', '2', '-i', str(path), '-f', 'null', '-'], 'decode-output', max_seconds=600)
        context.run([str(fp), '-v', 'error', '-show_streams', '-of', 'json', str(path)], 'probe', max_seconds=600)
        probe = json.loads((context.out/'probe.log').read_text())
        if not any(s['codec_type']=='video' for s in probe['streams']):raise ValueError('No video stream')
        metadata = {'probe': probe}
    elif kind != 'file':raise ValueError('Unknown output kind')
    return {'output': str(path), 'sha': digest(path), 'output_kind': kind,
            'review': 'technical_pass_human_review_pending', 'metadata': metadata}
