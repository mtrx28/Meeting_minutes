"""
Runs the full audio -> minutes pipeline across every meeting in wavs/ (the
AMI Meeting Corpus ES2002-ES2016 set), scores each one against its human
reference summary, and gates the run against a stored baseline so a quality
regression fails loudly instead of shipping silently.

Usage:
    python tests/run_benchmark.py               # all meetings in wavs/
    python tests/run_benchmark.py ES2002 ES2003  # a subset (fast smoke test)
    python tests/run_benchmark.py --update-baseline

Requires backend/.env with HF_API_TOKEN and MISTRAL_API_KEY. Each meeting is
a full local ASR + diarization run, so expect several minutes per meeting on
CPU — start with a one- or two-meeting subset before running the full set.
"""

import argparse
import csv
import glob
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402

from app.pipeline import MeetingPipeline  # noqa: E402
from app.evaluation import score_rouge, check_grounding  # noqa: E402

WAVS_DIR = os.path.join(REPO_ROOT, "wavs")
REFERENCES_DIR = os.path.join(REPO_ROOT, "references")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
BASELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline_scores.json")

# How far below baseline a metric can drop before the run fails.
REGRESSION_TOLERANCE = 0.03


def discover_meetings() -> list[str]:
    """Meeting IDs that have both audio (wavs/) and a reference summary."""
    meeting_ids = []
    for path in sorted(glob.glob(os.path.join(WAVS_DIR, "ES*"))):
        meeting_id = os.path.basename(path)
        ref_path = os.path.join(REFERENCES_DIR, f"{meeting_id}_combined_reference_summary_grouped.txt")
        if os.path.isdir(path) and os.path.exists(ref_path):
            meeting_ids.append(meeting_id)
    return meeting_ids


def _concat_audio(meeting_dir: str, meeting_id: str) -> str:
    """AMI splits each meeting into a/b/c/d headset mixes; concatenate them
    into one file so the pipeline sees a single continuous meeting."""
    from pydub import AudioSegment

    parts = sorted(glob.glob(os.path.join(meeting_dir, "*.wav")))
    if not parts:
        raise FileNotFoundError(f"No .wav files found for {meeting_id} in {meeting_dir}")

    combined = AudioSegment.empty()
    for part in parts:
        combined += AudioSegment.from_file(part)

    out_path = os.path.join(OUTPUT_DIR, f"{meeting_id}_combined.wav")
    combined.export(out_path, format="wav")
    return out_path


def run_meeting(pipeline: MeetingPipeline, meeting_id: str, use_multi_agent: bool = False) -> dict:
    meeting_dir = os.path.join(WAVS_DIR, meeting_id)
    audio_path = _concat_audio(meeting_dir, meeting_id)

    mode = "multi-agent" if use_multi_agent else "single-shot"
    print(f"[{meeting_id}] running pipeline ({mode}) on {os.path.basename(audio_path)}...")
    result = pipeline.run(
        audio_path,
        work_dir=os.path.join(OUTPUT_DIR, f"{meeting_id}_chunks"),
        use_multi_agent=use_multi_agent,
    )

    minutes_path = os.path.join(OUTPUT_DIR, f"{meeting_id}_minutes.md")
    with open(minutes_path, "w", encoding="utf-8") as f:
        f.write(result["summary"] + "\n\n" + result["minutes"])

    ref_path = os.path.join(REFERENCES_DIR, f"{meeting_id}_combined_reference_summary_grouped.txt")
    with open(ref_path, "r", encoding="utf-8") as f:
        reference = f.read()

    source_transcript = "\n".join(seg["text"] for seg in result["segments"])
    generated_document = result["summary"] + "\n\n" + result["minutes"]

    rouge = score_rouge(reference, generated_document)
    grounding = check_grounding(generated_document, source_transcript)

    try:
        os.remove(audio_path)
    except OSError:
        pass

    return {
        "meeting_id": meeting_id,
        "mode": mode,
        "rouge1_f1": rouge["rouge1"]["f1"],
        "rouge2_f1": rouge["rouge2"]["f1"],
        "rougeL_f1": rouge["rougeL"]["f1"],
        "grounding_score": grounding.score,
        "unsupported_claims": grounding.unsupported,
        "agent_verification_rate": result.get("verification_rate"),
        "num_speakers": result["num_speakers"],
        "processing_time_seconds": result["metadata"]["processing_time_seconds"],
    }


def check_regressions(results: list[dict], baseline: dict) -> list[str]:
    failures = []
    metrics = ("rouge1_f1", "rouge2_f1", "rougeL_f1", "grounding_score")
    for row in results:
        base = baseline.get(row["meeting_id"])
        if not base:
            continue
        for metric in metrics:
            drop = base.get(metric, 0) - row.get(metric, 0)
            if drop > REGRESSION_TOLERANCE:
                failures.append(
                    f"{row['meeting_id']}.{metric}: {row[metric]:.4f} vs baseline {base[metric]:.4f} "
                    f"(-{drop:.4f}, tolerance {REGRESSION_TOLERANCE})"
                )
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("meetings", nargs="*", help="Specific meeting IDs (e.g. ES2002). Default: all available.")
    parser.add_argument("--update-baseline", action="store_true", help="Write results as the new baseline instead of gating against it.")
    parser.add_argument("--multi-agent", action="store_true",
                         help="Generate minutes via the Extract->Verify->Write pipeline instead of single-shot generation.")
    args = parser.parse_args()

    load_dotenv(dotenv_path=os.path.join(BACKEND_DIR, ".env"))
    hf_token = os.getenv("HF_API_TOKEN")
    mistral_key = os.getenv("MISTRAL_API_KEY")
    if not hf_token or not mistral_key:
        print("Missing HF_API_TOKEN or MISTRAL_API_KEY in backend/.env", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    meeting_ids = args.meetings or discover_meetings()
    if not meeting_ids:
        print("No meetings found with both audio and a reference summary.", file=sys.stderr)
        sys.exit(1)

    pipeline = MeetingPipeline(
        hf_token=hf_token,
        mistral_api_key=mistral_key,
        whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", "base"),
    )

    results = []
    for meeting_id in meeting_ids:
        try:
            results.append(run_meeting(pipeline, meeting_id, use_multi_agent=args.multi_agent))
        except Exception as e:
            print(f"[{meeting_id}] FAILED: {e}", file=sys.stderr)

    if not results:
        print("No meetings evaluated successfully.", file=sys.stderr)
        sys.exit(1)

    csv_path = os.path.join(OUTPUT_DIR, "benchmark_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[k for k in results[0].keys() if k != "unsupported_claims"])
        writer.writeheader()
        for row in results:
            writer.writerow({k: v for k, v in row.items() if k != "unsupported_claims"})

    json_path = os.path.join(OUTPUT_DIR, "benchmark_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    averages = {
        metric: round(sum(r[metric] for r in results) / len(results), 4)
        for metric in ("rouge1_f1", "rouge2_f1", "rougeL_f1", "grounding_score")
    }

    print("\n=== Benchmark Results ===")
    for row in results:
        print(f"{row['meeting_id']}: ROUGE-1={row['rouge1_f1']:.4f}  ROUGE-2={row['rouge2_f1']:.4f}  "
              f"ROUGE-L={row['rougeL_f1']:.4f}  Grounding={row['grounding_score']:.4f}")
        if row["unsupported_claims"]:
            print(f"  potentially unsupported: {row['unsupported_claims']}")
    print(f"\nAverages: {averages}")
    print(f"Saved: {csv_path}\nSaved: {json_path}")

    if args.update_baseline:
        baseline = {row["meeting_id"]: row for row in results}
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2)
        print(f"Updated baseline: {BASELINE_PATH}")
        return

    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        failures = check_regressions(results, baseline)
        if failures:
            print("\nREGRESSIONS DETECTED:")
            for failure in failures:
                print(f"  - {failure}")
            sys.exit(1)
        print("\nNo regressions vs baseline.")
    else:
        print(f"\nNo baseline found at {BASELINE_PATH}. Run with --update-baseline to create one.")


if __name__ == "__main__":
    main()
