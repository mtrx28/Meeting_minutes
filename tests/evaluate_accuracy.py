"""
Quick single-meeting ROUGE check against tests/final_minutes.txt (produced by
run_summarization.py). For the full multi-meeting benchmark with a regression
gate and hallucination/grounding scoring, use tests/run_benchmark.py instead.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.evaluation import score_rouge


def evaluate(reference_path, generated_path):
    with open(reference_path, 'r', encoding='utf-8') as f:
        reference = f.read()
    with open(generated_path, 'r', encoding='utf-8') as f:
        generated = f.read()

    scores = score_rouge(reference, generated)
    for metric, values in scores.items():
        print(f"{metric.upper()}: P={values['precision']:.4f}, R={values['recall']:.4f}, F1={values['f1']:.4f}")
    return scores


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ref_path = os.path.join(base_dir, "references", "ES2002_combined_reference_summary_grouped.txt")
    gen_path = os.path.join(base_dir, "tests", "final_minutes.txt")
    if os.path.exists(ref_path) and os.path.exists(gen_path):
        evaluate(ref_path, gen_path)
    else:
        print(f"Missing file(s): {ref_path} or {gen_path}")
