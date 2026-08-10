<<<<<<< HEAD
# Complete Audio Processing Pipeline: Split + Speaker Diarization + Whisper Transcription

from pydub import AudioSegment
from pyannote.audio import Pipeline
import torch
import os
import whisper
from datetime import datetime
import json

def split_audio_into_chunks(input_file, output_dir="audio_chunks", chunk_minutes=15, max_chunks=None, prefix=None):
    """
    Split a large audio file into smaller chunks
    chunk_minutes: Size of each chunk in minutes (default: 15 minutes)
    prefix: Optional prefix for chunk filenames (e.g., meeting name)
    """
    print(f"Loading audio file: {input_file}")

    # Load the audio file
    audio = AudioSegment.from_file(input_file)

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Convert minutes to milliseconds
    chunk_length = chunk_minutes * 60 * 1000

    # Split into chunks
    chunk_files = []
    total_chunks = len(audio) // chunk_length + (1 if len(audio) % chunk_length else 0)

    print(f"Creating {total_chunks} chunks of {chunk_minutes} minutes each...")

    # Use prefix if provided, else use empty string
    if prefix is None:
        # Try to infer prefix from filename
        prefix = os.path.splitext(os.path.basename(input_file))[0]

    for i, start_time in enumerate(range(0, len(audio), chunk_length)):
        # Stop if max_chunks limit reached
        if max_chunks and i >= max_chunks:
            print(f"Stopped at {max_chunks} chunks as requested")
            break

        # Extract chunk
        chunk = audio[start_time:start_time + chunk_length]

        # Create filename with time info
        start_min = start_time // 1000 // 60
        end_min = min((start_time + chunk_length) // 1000 // 60, len(audio) // 1000 // 60)
        chunk_filename = f"{output_dir}/{prefix}_chunk_{i+1:02d}_{start_min:03d}m-{end_min:03d}m.wav"

        # Export chunk
        chunk.export(chunk_filename, format="wav")
        chunk_files.append(chunk_filename)

        duration_sec = len(chunk) / 1000
        print(f"✓ Created: {os.path.basename(chunk_filename)} ({duration_sec:.1f}s)")

    print(f"\n🎉 Created {len(chunk_files)} audio chunks in '{output_dir}' folder")
    print(f"Each chunk is ~{chunk_minutes} minutes long")
    return chunk_files

def perform_speaker_diarization(audio_file, pipeline, chunk_offset_minutes=0):
    """
    Perform speaker diarization on a single audio file with overlap handling.
    Returns a list of diarization segments, including overlap flag.
    """
    print(f"\n🎙  Analyzing speakers in: {os.path.basename(audio_file)}")

    try:
        diarization = pipeline(audio_file)
        offset_seconds = chunk_offset_minutes * 60

        results = []
        overlaps = []

        # Collect all segments
        raw_segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            raw_segments.append({
                'speaker': speaker,
                'start': turn.start + offset_seconds,
                'end': turn.end + offset_seconds
            })

        # Sort by start time
        raw_segments.sort(key=lambda x: x['start'])

        # Detect overlaps
        for i in range(len(raw_segments)):
            current = raw_segments[i]
            overlap_group = [current]
            for j in range(i + 1, len(raw_segments)):
                next_seg = raw_segments[j]
                if next_seg['start'] < current['end']:  # Overlapping
                    overlap_group.append(next_seg)
                    current['end'] = max(current['end'], next_seg['end'])
                else:
                    break

            if len(overlap_group) > 1:
                speakers = sorted(set(seg['speaker'] for seg in overlap_group))
                start_time = min(seg['start'] for seg in overlap_group)
                end_time = max(seg['end'] for seg in overlap_group)
                overlaps.append({
                    'speakers': speakers,
                    'start': start_time,
                    'end': end_time,
                    'duration': end_time - start_time,
                    'overlap': True
                })

            else:
                results.append({
                    'speaker': current['speaker'],
                    'start': current['start'],
                    'end': current['end'],
                    'duration': current['end'] - current['start'],
                    'overlap': False
                })

        # Combine non-overlaps and overlaps
        combined = results + overlaps
        combined.sort(key=lambda x: x['start'])

        for entry in combined:
            if entry.get('overlap'):
                print(f"Overlap {entry['speakers']} from {entry['start']:.2f}s to {entry['end']:.2f}s")
            else:
                print(f"Speaker {entry['speaker']}: {entry['start']:.2f}s to {entry['end']:.2f}s")

        return combined

    except Exception as e:
        print(f"❌ Error processing {audio_file}: {str(e)}")
        return []


def transcribe_audio_segments(audio_file, diarization_results, whisper_model, chunk_offset_minutes=0):
    """
    Transcribe audio using Whisper and align with speaker diarization (including overlaps).
    """
    print(f"\n🎤 Transcribing: {os.path.basename(audio_file)}")

    try:
        result = whisper_model.transcribe(audio_file, word_timestamps=True)
        offset_seconds = chunk_offset_minutes * 60
        combined_segments = []

        for diar_segment in diarization_results:
            segment_start = diar_segment['start'] - offset_seconds
            segment_end = diar_segment['end'] - offset_seconds
            segment_words = []

            for segment in result['segments']:
                if 'words' not in segment:
                    continue
                for word_info in segment['words']:
                    word_start = word_info.get('start', 0)
                    word_end = word_info.get('end', 0)
                    if (word_start >= segment_start and word_start <= segment_end) or \
                       (word_end >= segment_start and word_end <= segment_end):
                        segment_words.append(word_info['word'].strip())

            segment_text = " ".join(segment_words).strip()
            if segment_text:
                combined_segments.append({
                    'speaker': diar_segment.get('speaker', None),
                    'speakers': diar_segment.get('speakers', [diar_segment.get('speaker')]),
                    'start': diar_segment['start'],
                    'end': diar_segment['end'],
                    'duration': diar_segment['duration'],
                    'text': segment_text,
                    'overlap': diar_segment.get('overlap', False)
                })

                mins = int(diar_segment['start'] // 60)
                secs = int(diar_segment['start'] % 60)
                spk_str = ', '.join(diar_segment.get('speakers', [diar_segment.get('speaker')]))
                print(f"[{mins:02d}:{secs:05.2f}] {spk_str}: {segment_text[:60]}...")

        return combined_segments

    except Exception as e:
        print(f"❌ Error transcribing {audio_file}: {str(e)}")
        return []


def process_audio_chunks(chunk_files, diarization_pipeline, original_chunk_minutes=15):
    """
    Process multiple audio chunks for speaker diarization only
    """
    all_results = []

    print(f"\n🔄 Processing {len(chunk_files)} audio chunks for speaker diarization...")

    for i, chunk_file in enumerate(chunk_files):
        # Calculate time offset for this chunk
        chunk_offset_minutes = i * original_chunk_minutes

        print(f"\n--- Processing chunk {i+1}/{len(chunk_files)} ---")

        # Get speaker diarization
        diarization_results = perform_speaker_diarization(chunk_file, diarization_pipeline, chunk_offset_minutes)
        all_results.extend(diarization_results)

    return all_results

def process_audio_chunks_with_transcription(chunk_files, diarization_pipeline, whisper_model, original_chunk_minutes=15):
    """
    Process multiple audio chunks for both speaker diarization and transcription
    """
    all_transcribed_segments = []

    print(f"\n🔄 Processing {len(chunk_files)} audio chunks with transcription...")

    for i, chunk_file in enumerate(chunk_files):
        # Calculate time offset for this chunk
        chunk_offset_minutes = i * original_chunk_minutes

        print(f"\n--- Processing chunk {i+1}/{len(chunk_files)} ---")

        # Step 1: Get speaker diarization
        diarization_results = perform_speaker_diarization(chunk_file, diarization_pipeline, chunk_offset_minutes)

        # Step 2: Get transcription aligned with speakers
        if diarization_results:
            transcribed_segments = transcribe_audio_segments(
                chunk_file, diarization_results, whisper_model, chunk_offset_minutes
            )
            all_transcribed_segments.extend(transcribed_segments)
        else:
            print(f"⚠  No speakers detected in chunk {i+1}, running basic transcription...")
            # Fallback: basic transcription without speaker info
            try:
                result = whisper_model.transcribe(chunk_file)
                fallback_segment = {
                    'speaker': 'UNKNOWN',
                    'start': chunk_offset_minutes * 60,
                    'end': (chunk_offset_minutes + original_chunk_minutes) * 60,
                    'duration': original_chunk_minutes * 60,
                    'text': result['text'].strip()
                }
                if fallback_segment['text']:
                    all_transcribed_segments.append(fallback_segment)
            except Exception as e:
                print(f"❌ Fallback transcription failed: {str(e)}")

    return all_transcribed_segments

def save_diarization_results(results, output_file="speaker_diarization_results.txt"):
    """
    Save speaker diarization results to a file
    """
    print(f"\n💾 Saving diarization results to {output_file}...")

    # Sort by start time
    sorted_results = sorted(results, key=lambda x: x['start'])

    with open(output_file, "w", encoding='utf-8') as f:
        f.write(f"Speaker Diarization Results\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")

        # Summary statistics
        speakers = {}
        for result in sorted_results:
            speaker = result['speaker']
            if speaker not in speakers:
                speakers[speaker] = {'duration': 0, 'segments': 0}
            speakers[speaker]['duration'] += result['duration']
            speakers[speaker]['segments'] += 1

        f.write("SUMMARY:\n")
        f.write("-" * 30 + "\n")
        f.write(f"Total segments: {len(sorted_results)}\n")
        f.write(f"Unique speakers: {len(speakers)}\n")
        f.write(f"Total duration: {sum(r['duration'] for r in sorted_results):.1f} seconds\n\n")

        f.write("SPEAKER STATISTICS:\n")
        f.write("-" * 30 + "\n")
        for speaker in sorted(speakers.keys()):
            stats = speakers[speaker]
            f.write(f"Speaker {speaker}:\n")
            f.write(f"  - Speaking time: {stats['duration']:.1f}s ({stats['duration']/60:.1f}min)\n")
            f.write(f"  - Speaking segments: {stats['segments']}\n\n")

        f.write("DETAILED TIMELINE:\n")
        f.write("-" * 30 + "\n")
        for result in sorted_results:
            minutes_start = int(result['start'] // 60)
            seconds_start = result['start'] % 60
            minutes_end = int(result['end'] // 60)
            seconds_end = result['end'] % 60

            f.write(f"[{minutes_start:02d}:{seconds_start:05.2f} - {minutes_end:02d}:{seconds_end:05.2f}] "
                   f"Speaker {result['speaker']} ({result['duration']:.1f}s)\n")

    print(f"✅ Results saved to: {output_file}")

def save_transcription_results(transcribed_segments, output_file="complete_transcription_results.txt", json_output="combined_output.json"):
    """
    Save transcription results in multiple formats for LLM processing
    """
    print(f"\n💾 Saving transcription results...")

    # Sort by start time
    sorted_segments = sorted(transcribed_segments, key=lambda x: x['start'])

    # Save human-readable format
    with open(output_file, "w", encoding='utf-8') as f:
        f.write(f"Meeting Transcription with Speaker Diarization\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")

        # Summary
        speakers = {}
        total_words = 0
        for segment in sorted_segments:
            speaker = segment['speaker']
            words = len(segment['text'].split())
            total_words += words

            if speaker not in speakers:
                speakers[speaker] = {'duration': 0, 'words': 0, 'segments': 0}
            speakers[speaker]['duration'] += segment['duration']
            speakers[speaker]['words'] += words
            speakers[speaker]['segments'] += 1

        f.write("MEETING SUMMARY:\n")
        f.write("-" * 40 + "\n")
        f.write(f"Total duration analyzed: {sum(s['duration'] for s in sorted_segments)/60:.1f} minutes\n")
        f.write(f"Total words spoken: {total_words}\n")
        f.write(f"Number of speakers: {len(speakers)}\n\n")

        f.write("SPEAKER STATISTICS:\n")
        f.write("-" * 40 + "\n")
        for speaker in sorted(speakers.keys()):
            stats = speakers[speaker]
            f.write(f"Speaker {speaker}:\n")
            f.write(f"  - Speaking time: {stats['duration']:.1f}s ({stats['duration']/60:.1f}min)\n")
            f.write(f"  - Words spoken: {stats['words']}\n")
            f.write(f"  - Speaking segments: {stats['segments']}\n\n")

        f.write("FULL TRANSCRIPT:\n")
        f.write("-" * 40 + "\n")

        current_speaker = None
        for segment in sorted_segments:
            minutes = int(segment['start'] // 60)
            seconds = segment['start'] % 60

            # Add speaker change indicator
            if segment['speaker'] != current_speaker:
                f.write(f"\n[{minutes:02d}:{seconds:05.2f}] SPEAKER {segment['speaker']}:\n")
                current_speaker = segment['speaker']

            f.write(f"{segment['text']}\n")

    # Save JSON format for LLM processing
    json_data = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'total_segments': len(sorted_segments),
            'total_duration_seconds': sum(s['duration'] for s in sorted_segments),
            'speakers': list(set(s['speaker'] for s in sorted_segments))
        },
        'segments': sorted_segments
    }

    with open(json_output, "w", encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Human-readable transcript saved to: {output_file}")
    print(f"✅ JSON data for LLM saved to: {json_output}")

    return json_data

import glob
import os

def get_es2002_audio_files(folder="/data/input"):
    wavs = sorted(glob.glob(os.path.join(folder, "ES2002*.Mix-Headset.wav")))
    print(f"✅ Found {len(wavs)} audio files for ES2002: {[os.path.basename(w) for w in wavs]}")
    return wavs

def process_and_merge_es2002_parts():
    folder = "./data/input/ES2002"
    audio_files = get_es2002_audio_files(folder)
    hf_token = HF_API_TOKEN  # Replace with your token
    whisper_model_size = "base"

    if not audio_files:
        print("❌ No audio files found.")
        return

    print(f"\n🤖 Loading models...")
    whisper_model = whisper.load_model(whisper_model_size)
    diarization_pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
    if torch.cuda.is_available():
        diarization_pipeline = diarization_pipeline.to(torch.device("cuda"))

    all_segments = []
    total_offset = 0  # seconds

    for i, audio_file in enumerate(audio_files):
        print(f"\n--- [{i+1}/{len(audio_files)}] Processing {os.path.basename(audio_file)} ---")
        # Extract meeting name as prefix (e.g., ES2002a)
        prefix = os.path.splitext(os.path.basename(audio_file))[0]
        chunk_files = split_audio_into_chunks(audio_file, output_dir="/data/audio_chunks", chunk_minutes=15, prefix=prefix)

        transcribed = process_audio_chunks_with_transcription(
            chunk_files,
            diarization_pipeline,
            whisper_model,
            original_chunk_minutes=15
        )

        for seg in transcribed:
            seg["start"] += total_offset
            seg["end"] += total_offset

        all_segments.extend(transcribed)
        audio_dur = AudioSegment.from_file(audio_file).duration_seconds
        total_offset += audio_dur

    final_json = {
        "metadata": {
            "meeting_id": "ES2002",
            "segments": len(all_segments),
            "total_duration": sum(s["duration"] for s in all_segments),
        },
        "segments": sorted(all_segments, key=lambda x: x["start"])
    }

    output_path = "./data/output/transcripts/ES2002_combined_transcription.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, indent=2)

    print(f"\n✅ Merged transcription saved to {output_path}")
    print(f"📊 Total segments: {len(all_segments)}")

if __name__ == "__main__":
=======
# Complete Audio Processing Pipeline: Split + Speaker Diarization + Whisper Transcription

from pydub import AudioSegment
from pyannote.audio import Pipeline
import torch
import os
import whisper
from datetime import datetime
import json

def split_audio_into_chunks(input_file, output_dir="audio_chunks", chunk_minutes=15, max_chunks=None, prefix=None):
    """
    Split a large audio file into smaller chunks
    chunk_minutes: Size of each chunk in minutes (default: 15 minutes)
    prefix: Optional prefix for chunk filenames (e.g., meeting name)
    """
    print(f"Loading audio file: {input_file}")

    # Load the audio file
    audio = AudioSegment.from_file(input_file)

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Convert minutes to milliseconds
    chunk_length = chunk_minutes * 60 * 1000

    # Split into chunks
    chunk_files = []
    total_chunks = len(audio) // chunk_length + (1 if len(audio) % chunk_length else 0)

    print(f"Creating {total_chunks} chunks of {chunk_minutes} minutes each...")

    # Use prefix if provided, else use empty string
    if prefix is None:
        # Try to infer prefix from filename
        prefix = os.path.splitext(os.path.basename(input_file))[0]

    for i, start_time in enumerate(range(0, len(audio), chunk_length)):
        # Stop if max_chunks limit reached
        if max_chunks and i >= max_chunks:
            print(f"Stopped at {max_chunks} chunks as requested")
            break

        # Extract chunk
        chunk = audio[start_time:start_time + chunk_length]

        # Create filename with time info
        start_min = start_time // 1000 // 60
        end_min = min((start_time + chunk_length) // 1000 // 60, len(audio) // 1000 // 60)
        chunk_filename = f"{output_dir}/{prefix}_chunk_{i+1:02d}_{start_min:03d}m-{end_min:03d}m.wav"

        # Export chunk
        chunk.export(chunk_filename, format="wav")
        chunk_files.append(chunk_filename)

        duration_sec = len(chunk) / 1000
        print(f"✓ Created: {os.path.basename(chunk_filename)} ({duration_sec:.1f}s)")

    print(f"\n🎉 Created {len(chunk_files)} audio chunks in '{output_dir}' folder")
    print(f"Each chunk is ~{chunk_minutes} minutes long")
    return chunk_files

def perform_speaker_diarization(audio_file, pipeline, chunk_offset_minutes=0):
    """
    Perform speaker diarization on a single audio file with overlap handling.
    Returns a list of diarization segments, including overlap flag.
    """
    print(f"\n🎙  Analyzing speakers in: {os.path.basename(audio_file)}")

    try:
        diarization = pipeline(audio_file)
        offset_seconds = chunk_offset_minutes * 60

        results = []
        overlaps = []

        # Collect all segments
        raw_segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            raw_segments.append({
                'speaker': speaker,
                'start': turn.start + offset_seconds,
                'end': turn.end + offset_seconds
            })

        # Sort by start time
        raw_segments.sort(key=lambda x: x['start'])

        # Detect overlaps
        for i in range(len(raw_segments)):
            current = raw_segments[i]
            overlap_group = [current]
            for j in range(i + 1, len(raw_segments)):
                next_seg = raw_segments[j]
                if next_seg['start'] < current['end']:  # Overlapping
                    overlap_group.append(next_seg)
                    current['end'] = max(current['end'], next_seg['end'])
                else:
                    break

            if len(overlap_group) > 1:
                speakers = sorted(set(seg['speaker'] for seg in overlap_group))
                start_time = min(seg['start'] for seg in overlap_group)
                end_time = max(seg['end'] for seg in overlap_group)
                overlaps.append({
                    'speakers': speakers,
                    'start': start_time,
                    'end': end_time,
                    'duration': end_time - start_time,
                    'overlap': True
                })

            else:
                results.append({
                    'speaker': current['speaker'],
                    'start': current['start'],
                    'end': current['end'],
                    'duration': current['end'] - current['start'],
                    'overlap': False
                })

        # Combine non-overlaps and overlaps
        combined = results + overlaps
        combined.sort(key=lambda x: x['start'])

        for entry in combined:
            if entry.get('overlap'):
                print(f"Overlap {entry['speakers']} from {entry['start']:.2f}s to {entry['end']:.2f}s")
            else:
                print(f"Speaker {entry['speaker']}: {entry['start']:.2f}s to {entry['end']:.2f}s")

        return combined

    except Exception as e:
        print(f"❌ Error processing {audio_file}: {str(e)}")
        return []


def transcribe_audio_segments(audio_file, diarization_results, whisper_model, chunk_offset_minutes=0):
    """
    Transcribe audio using Whisper and align with speaker diarization (including overlaps).
    """
    print(f"\n🎤 Transcribing: {os.path.basename(audio_file)}")

    try:
        result = whisper_model.transcribe(audio_file, word_timestamps=True)
        offset_seconds = chunk_offset_minutes * 60
        combined_segments = []

        for diar_segment in diarization_results:
            segment_start = diar_segment['start'] - offset_seconds
            segment_end = diar_segment['end'] - offset_seconds
            segment_words = []

            for segment in result['segments']:
                if 'words' not in segment:
                    continue
                for word_info in segment['words']:
                    word_start = word_info.get('start', 0)
                    word_end = word_info.get('end', 0)
                    if (word_start >= segment_start and word_start <= segment_end) or \
                       (word_end >= segment_start and word_end <= segment_end):
                        segment_words.append(word_info['word'].strip())

            segment_text = " ".join(segment_words).strip()
            if segment_text:
                combined_segments.append({
                    'speaker': diar_segment.get('speaker', None),
                    'speakers': diar_segment.get('speakers', [diar_segment.get('speaker')]),
                    'start': diar_segment['start'],
                    'end': diar_segment['end'],
                    'duration': diar_segment['duration'],
                    'text': segment_text,
                    'overlap': diar_segment.get('overlap', False)
                })

                mins = int(diar_segment['start'] // 60)
                secs = int(diar_segment['start'] % 60)
                spk_str = ', '.join(diar_segment.get('speakers', [diar_segment.get('speaker')]))
                print(f"[{mins:02d}:{secs:05.2f}] {spk_str}: {segment_text[:60]}...")

        return combined_segments

    except Exception as e:
        print(f"❌ Error transcribing {audio_file}: {str(e)}")
        return []


def process_audio_chunks(chunk_files, diarization_pipeline, original_chunk_minutes=15):
    """
    Process multiple audio chunks for speaker diarization only
    """
    all_results = []

    print(f"\n🔄 Processing {len(chunk_files)} audio chunks for speaker diarization...")

    for i, chunk_file in enumerate(chunk_files):
        # Calculate time offset for this chunk
        chunk_offset_minutes = i * original_chunk_minutes

        print(f"\n--- Processing chunk {i+1}/{len(chunk_files)} ---")

        # Get speaker diarization
        diarization_results = perform_speaker_diarization(chunk_file, diarization_pipeline, chunk_offset_minutes)
        all_results.extend(diarization_results)

    return all_results

def process_audio_chunks_with_transcription(chunk_files, diarization_pipeline, whisper_model, original_chunk_minutes=15):
    """
    Process multiple audio chunks for both speaker diarization and transcription
    """
    all_transcribed_segments = []

    print(f"\n🔄 Processing {len(chunk_files)} audio chunks with transcription...")

    for i, chunk_file in enumerate(chunk_files):
        # Calculate time offset for this chunk
        chunk_offset_minutes = i * original_chunk_minutes

        print(f"\n--- Processing chunk {i+1}/{len(chunk_files)} ---")

        # Step 1: Get speaker diarization
        diarization_results = perform_speaker_diarization(chunk_file, diarization_pipeline, chunk_offset_minutes)

        # Step 2: Get transcription aligned with speakers
        if diarization_results:
            transcribed_segments = transcribe_audio_segments(
                chunk_file, diarization_results, whisper_model, chunk_offset_minutes
            )
            all_transcribed_segments.extend(transcribed_segments)
        else:
            print(f"⚠  No speakers detected in chunk {i+1}, running basic transcription...")
            # Fallback: basic transcription without speaker info
            try:
                result = whisper_model.transcribe(chunk_file)
                fallback_segment = {
                    'speaker': 'UNKNOWN',
                    'start': chunk_offset_minutes * 60,
                    'end': (chunk_offset_minutes + original_chunk_minutes) * 60,
                    'duration': original_chunk_minutes * 60,
                    'text': result['text'].strip()
                }
                if fallback_segment['text']:
                    all_transcribed_segments.append(fallback_segment)
            except Exception as e:
                print(f"❌ Fallback transcription failed: {str(e)}")

    return all_transcribed_segments

def save_diarization_results(results, output_file="speaker_diarization_results.txt"):
    """
    Save speaker diarization results to a file
    """
    print(f"\n💾 Saving diarization results to {output_file}...")

    # Sort by start time
    sorted_results = sorted(results, key=lambda x: x['start'])

    with open(output_file, "w", encoding='utf-8') as f:
        f.write(f"Speaker Diarization Results\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")

        # Summary statistics
        speakers = {}
        for result in sorted_results:
            speaker = result['speaker']
            if speaker not in speakers:
                speakers[speaker] = {'duration': 0, 'segments': 0}
            speakers[speaker]['duration'] += result['duration']
            speakers[speaker]['segments'] += 1

        f.write("SUMMARY:\n")
        f.write("-" * 30 + "\n")
        f.write(f"Total segments: {len(sorted_results)}\n")
        f.write(f"Unique speakers: {len(speakers)}\n")
        f.write(f"Total duration: {sum(r['duration'] for r in sorted_results):.1f} seconds\n\n")

        f.write("SPEAKER STATISTICS:\n")
        f.write("-" * 30 + "\n")
        for speaker in sorted(speakers.keys()):
            stats = speakers[speaker]
            f.write(f"Speaker {speaker}:\n")
            f.write(f"  - Speaking time: {stats['duration']:.1f}s ({stats['duration']/60:.1f}min)\n")
            f.write(f"  - Speaking segments: {stats['segments']}\n\n")

        f.write("DETAILED TIMELINE:\n")
        f.write("-" * 30 + "\n")
        for result in sorted_results:
            minutes_start = int(result['start'] // 60)
            seconds_start = result['start'] % 60
            minutes_end = int(result['end'] // 60)
            seconds_end = result['end'] % 60

            f.write(f"[{minutes_start:02d}:{seconds_start:05.2f} - {minutes_end:02d}:{seconds_end:05.2f}] "
                   f"Speaker {result['speaker']} ({result['duration']:.1f}s)\n")

    print(f"✅ Results saved to: {output_file}")

def save_transcription_results(transcribed_segments, output_file="complete_transcription_results.txt", json_output="combined_output.json"):
    """
    Save transcription results in multiple formats for LLM processing
    """
    print(f"\n💾 Saving transcription results...")

    # Sort by start time
    sorted_segments = sorted(transcribed_segments, key=lambda x: x['start'])

    # Save human-readable format
    with open(output_file, "w", encoding='utf-8') as f:
        f.write(f"Meeting Transcription with Speaker Diarization\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")

        # Summary
        speakers = {}
        total_words = 0
        for segment in sorted_segments:
            speaker = segment['speaker']
            words = len(segment['text'].split())
            total_words += words

            if speaker not in speakers:
                speakers[speaker] = {'duration': 0, 'words': 0, 'segments': 0}
            speakers[speaker]['duration'] += segment['duration']
            speakers[speaker]['words'] += words
            speakers[speaker]['segments'] += 1

        f.write("MEETING SUMMARY:\n")
        f.write("-" * 40 + "\n")
        f.write(f"Total duration analyzed: {sum(s['duration'] for s in sorted_segments)/60:.1f} minutes\n")
        f.write(f"Total words spoken: {total_words}\n")
        f.write(f"Number of speakers: {len(speakers)}\n\n")

        f.write("SPEAKER STATISTICS:\n")
        f.write("-" * 40 + "\n")
        for speaker in sorted(speakers.keys()):
            stats = speakers[speaker]
            f.write(f"Speaker {speaker}:\n")
            f.write(f"  - Speaking time: {stats['duration']:.1f}s ({stats['duration']/60:.1f}min)\n")
            f.write(f"  - Words spoken: {stats['words']}\n")
            f.write(f"  - Speaking segments: {stats['segments']}\n\n")

        f.write("FULL TRANSCRIPT:\n")
        f.write("-" * 40 + "\n")

        current_speaker = None
        for segment in sorted_segments:
            minutes = int(segment['start'] // 60)
            seconds = segment['start'] % 60

            # Add speaker change indicator
            if segment['speaker'] != current_speaker:
                f.write(f"\n[{minutes:02d}:{seconds:05.2f}] SPEAKER {segment['speaker']}:\n")
                current_speaker = segment['speaker']

            f.write(f"{segment['text']}\n")

    # Save JSON format for LLM processing
    json_data = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'total_segments': len(sorted_segments),
            'total_duration_seconds': sum(s['duration'] for s in sorted_segments),
            'speakers': list(set(s['speaker'] for s in sorted_segments))
        },
        'segments': sorted_segments
    }

    with open(json_output, "w", encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Human-readable transcript saved to: {output_file}")
    print(f"✅ JSON data for LLM saved to: {json_output}")

    return json_data

import glob
import os

def get_es2002_audio_files(folder="/data/input"):
    wavs = sorted(glob.glob(os.path.join(folder, "ES2002*.Mix-Headset.wav")))
    print(f"✅ Found {len(wavs)} audio files for ES2002: {[os.path.basename(w) for w in wavs]}")
    return wavs

def process_and_merge_es2002_parts():
    folder = "./data/input/ES2002"
    audio_files = get_es2002_audio_files(folder)
    hf_token = HF_API_TOKEN  # Replace with your token
    whisper_model_size = "base"

    if not audio_files:
        print("❌ No audio files found.")
        return

    print(f"\n🤖 Loading models...")
    whisper_model = whisper.load_model(whisper_model_size)
    diarization_pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
    if torch.cuda.is_available():
        diarization_pipeline = diarization_pipeline.to(torch.device("cuda"))

    all_segments = []
    total_offset = 0  # seconds

    for i, audio_file in enumerate(audio_files):
        print(f"\n--- [{i+1}/{len(audio_files)}] Processing {os.path.basename(audio_file)} ---")
        # Extract meeting name as prefix (e.g., ES2002a)
        prefix = os.path.splitext(os.path.basename(audio_file))[0]
        chunk_files = split_audio_into_chunks(audio_file, output_dir="/data/audio_chunks", chunk_minutes=15, prefix=prefix)

        transcribed = process_audio_chunks_with_transcription(
            chunk_files,
            diarization_pipeline,
            whisper_model,
            original_chunk_minutes=15
        )

        for seg in transcribed:
            seg["start"] += total_offset
            seg["end"] += total_offset

        all_segments.extend(transcribed)
        audio_dur = AudioSegment.from_file(audio_file).duration_seconds
        total_offset += audio_dur

    final_json = {
        "metadata": {
            "meeting_id": "ES2002",
            "segments": len(all_segments),
            "total_duration": sum(s["duration"] for s in all_segments),
        },
        "segments": sorted(all_segments, key=lambda x: x["start"])
    }

    output_path = "./data/output/transcripts/ES2002_combined_transcription.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, indent=2)

    print(f"\n✅ Merged transcription saved to {output_path}")
    print(f"📊 Total segments: {len(all_segments)}")

if __name__ == "__main__":
>>>>>>> 524bd637d2efef453418eb3c0b4a53917f562877
    process_and_merge_es2002_parts()