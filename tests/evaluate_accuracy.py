import os
from rouge_score import rouge_scorer
import re

def clean_text(text):
    text = re.sub(r'[*#]', '', text)
    return ' '.join(text.split()).lower()

def evaluate(reference_path, generated_path):
    with open(reference_path, 'r', encoding='utf-8') as f:
        reference = f.read()
    
    with open(generated_path, 'r', encoding='utf-8') as f:
        generated = f.read()

    ref_clean = clean_text(reference)
    gen_clean = clean_text(generated)

    scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
    scores = scorer.score(ref_clean, gen_clean)

    print("ROUGE-1: P={:.4f}, R={:.4f}, F1={:.4f}".format(scores['rouge1'].precision, scores['rouge1'].recall, scores['rouge1'].fmeasure))
    print("ROUGE-2: P={:.4f}, R={:.4f}, F1={:.4f}".format(scores['rouge2'].precision, scores['rouge2'].recall, scores['rouge2'].fmeasure))
    print("ROUGE-L: P={:.4f}, R={:.4f}, F1={:.4f}".format(scores['rougeL'].precision, scores['rougeL'].recall, scores['rougeL'].fmeasure))
    return scores

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ref_path = os.path.join(base_dir, "es2002", "ES2002_combined_reference_summary_grouped.txt")
    gen_path = os.path.join(base_dir, "tests", "final_minutes.txt")
    if os.path.exists(ref_path) and os.path.exists(gen_path):
        evaluate(ref_path, gen_path)
    else:
        print(f"Missing file(s): {ref_path} or {gen_path}")
