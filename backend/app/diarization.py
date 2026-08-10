"""
Cleaned and optimized speaker diarization + transcription module.
Handles: audio splitting, speaker diarization (pyannote), and whisper transcription.
"""

from pydub import AudioSegment
from pyannote.audio import Pipeline
import torch
import os
import whisper
from bisect import bisect_left, bisect_right
import logging

logger = logging.getLogger(__name__)


def split_audio_into_chunks(input_file: str, output_dir: str = "audio_chunks",
                            chunk_minutes: int = 15) -> list[dict]:
    """
    Split a large audio file into smaller WAV chunks.
    Returns a list of dicts: { 'path': str, 'offset_seconds': float, 'duration_seconds': float }
    """
    logger.info(f"Loading audio file: {input_file}")
    audio = AudioSegment.from_file(input_file)
    os.makedirs(output_dir, exist_ok=True)

    chunk_length_ms = chunk_minutes * 60 * 1000
    prefix = os.path.splitext(os.path.basename(input_file))[0]
    chunks = []

    for i, start_ms in enumerate(range(0, len(audio), chunk_length_ms)):
        chunk = audio[start_ms:start_ms + chunk_length_ms]
        start_min = start_ms // 1000 // 60
        end_min = min((start_ms + chunk_length_ms) // 1000 // 60, len(audio) // 1000 // 60)
        chunk_path = os.path.join(output_dir, f"{prefix}_chunk_{i + 1:02d}_{start_min:03d}m-{end_min:03d}m.wav")

        chunk.export(chunk_path, format="wav")
        chunk_duration = len(chunk) / 1000.0
        chunks.append({
            'path': chunk_path,
            'offset_seconds': start_ms / 1000.0,
            'duration_seconds': chunk_duration,
        })
        logger.info(f"Created chunk: {os.path.basename(chunk_path)} ({chunk_duration:.1f}s)")

    logger.info(f"Split into {len(chunks)} chunks of ~{chunk_minutes} min each")
    return chunks


def perform_speaker_diarization(audio_file: str, pipeline: Pipeline,
                                offset_seconds: float = 0.0) -> list[dict]:
    """
    Perform speaker diarization on a single audio file.
    Uses a proper merge-intervals approach for overlap detection.
    Returns sorted list of segments with overlap flags.
    """
    logger.info(f"Analyzing speakers in: {os.path.basename(audio_file)}")

    try:
        diarization = pipeline(audio_file)
    except Exception as e:
        logger.error(f"Diarization failed for {audio_file}: {e}")
        return []

    # Collect raw segments with global offset applied
    raw_segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        raw_segments.append({
            'speaker': speaker,
            'start': turn.start + offset_seconds,
            'end': turn.end + offset_seconds,
        })

    # Sort by start time, then by end time descending (longer segments first)
    raw_segments.sort(key=lambda x: (x['start'], -x['end']))

    # Merge-intervals approach for overlap detection
    merged = []
    i = 0
    while i < len(raw_segments):
        current = raw_segments[i]
        group_speakers = {current['speaker']}
        group_start = current['start']
        group_end = current['end']
        j = i + 1

        # Absorb all segments that overlap with the current group
        while j < len(raw_segments) and raw_segments[j]['start'] < group_end:
            group_speakers.add(raw_segments[j]['speaker'])
            group_end = max(group_end, raw_segments[j]['end'])
            j += 1

        duration = group_end - group_start
        is_overlap = len(group_speakers) > 1

        if is_overlap:
            merged.append({
                'speaker': None,
                'speakers': sorted(group_speakers),
                'start': group_start,
                'end': group_end,
                'duration': duration,
                'overlap': True,
            })
        else:
            merged.append({
                'speaker': current['speaker'],
                'speakers': [current['speaker']],
                'start': group_start,
                'end': group_end,
                'duration': duration,
                'overlap': False,
            })

        i = j  # Skip past all consumed segments

    logger.info(f"Found {len(merged)} segments ({sum(1 for s in merged if s['overlap'])} overlaps)")
    return merged


def transcribe_audio_segments(audio_file: str, diarization_results: list[dict],
                              whisper_model, offset_seconds: float = 0.0) -> list[dict]:
    """
    Transcribe audio using Whisper and align words with diarization segments.
    Uses binary search for efficient word-to-segment alignment (O(n + m log n)
    instead of O(n * m)).
    """
    logger.info(f"Transcribing: {os.path.basename(audio_file)}")

    try:
        result = whisper_model.transcribe(audio_file, word_timestamps=True)
    except Exception as e:
        logger.error(f"Transcription failed for {audio_file}: {e}")
        return []

    # Flatten all words and sort by start time
    all_words = []
    for segment in result['segments']:
        for word_info in segment.get('words', []):
            w_start = word_info.get('start', 0)
            w_end = word_info.get('end', 0)
            all_words.append({
                'word': word_info['word'].strip(),
                'start': w_start,
                'end': w_end,
            })

    all_words.sort(key=lambda w: w['start'])
    word_starts = [w['start'] for w in all_words]

    combined_segments = []
    for diar_seg in diarization_results:
        # Convert global timestamps back to chunk-local for word matching
        seg_start_local = diar_seg['start'] - offset_seconds
        seg_end_local = diar_seg['end'] - offset_seconds

        # Binary search for words within this diarization segment
        left_idx = bisect_left(word_starts, seg_start_local)
        right_idx = bisect_right(word_starts, seg_end_local)

        # Collect words that fall within the segment boundaries
        segment_words = []
        for idx in range(max(0, left_idx - 1), min(len(all_words), right_idx + 1)):
            w = all_words[idx]
            if w['start'] >= seg_start_local - 0.1 and w['start'] <= seg_end_local + 0.1:
                segment_words.append(w['word'])

        text = " ".join(segment_words).strip()
        if text:
            combined_segments.append({
                'speaker': diar_seg.get('speaker'),
                'speakers': diar_seg.get('speakers', [diar_seg.get('speaker')]),
                'start': diar_seg['start'],
                'end': diar_seg['end'],
                'duration': diar_seg['duration'],
                'text': text,
                'overlap': diar_seg.get('overlap', False),
            })

    logger.info(f"Transcribed {len(combined_segments)} segments with text")
    return combined_segments


def process_audio_pipeline(audio_file: str, diarization_pipeline: Pipeline,
                           whisper_model, chunk_minutes: int = 15,
                           work_dir: str = "audio_chunks",
                           progress_callback=None) -> list[dict]:
    """
    Full pipeline for a single audio file:
    1. Split into chunks
    2. Diarize each chunk
    3. Transcribe each chunk aligned with diarization
    Returns all transcribed segments sorted by time.
    """
    # Step 1: Split audio
    if progress_callback:
        progress_callback("splitting", "Splitting audio into chunks...")
    chunks = split_audio_into_chunks(audio_file, output_dir=work_dir, chunk_minutes=chunk_minutes)

    all_segments = []

    for idx, chunk_info in enumerate(chunks):
        chunk_path = chunk_info['path']
        chunk_offset = chunk_info['offset_seconds']

        # Step 2: Diarize
        if progress_callback:
            progress_callback("diarizing", f"Analyzing speakers in chunk {idx + 1}/{len(chunks)}...")
        diarization_results = perform_speaker_diarization(
            chunk_path, diarization_pipeline, offset_seconds=chunk_offset
        )

        if not diarization_results:
            # Fallback: basic transcription without speaker info
            logger.warning(f"No speakers detected in chunk {idx + 1}, running basic transcription")
            if progress_callback:
                progress_callback("transcribing", f"Basic transcription for chunk {idx + 1} (no speakers found)...")
            try:
                result = whisper_model.transcribe(chunk_path)
                text = result.get('text', '').strip()
                if text:
                    all_segments.append({
                        'speaker': 'UNKNOWN',
                        'speakers': ['UNKNOWN'],
                        'start': chunk_offset,
                        'end': chunk_offset + chunk_info['duration_seconds'],
                        'duration': chunk_info['duration_seconds'],
                        'text': text,
                        'overlap': False,
                    })
            except Exception as e:
                logger.error(f"Fallback transcription failed for chunk {idx + 1}: {e}")
            continue

        # Step 3: Transcribe aligned with speakers
        if progress_callback:
            progress_callback("transcribing", f"Transcribing chunk {idx + 1}/{len(chunks)}...")
        transcribed = transcribe_audio_segments(
            chunk_path, diarization_results, whisper_model, offset_seconds=chunk_offset
        )
        all_segments.extend(transcribed)

    # Sort all segments by start time
    all_segments.sort(key=lambda x: x['start'])

    # Cleanup chunk files
    for chunk_info in chunks:
        try:
            os.remove(chunk_info['path'])
        except OSError:
            pass

    logger.info(f"Pipeline complete: {len(all_segments)} total segments")
    return all_segments
