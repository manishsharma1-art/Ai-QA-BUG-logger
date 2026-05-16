"""
Extract curated training examples from the 611 real bugs.
Saves diverse, well-formatted examples as training_examples.json
"""
import json

with open("training_data_raw.json", "r", encoding="utf-8-sig") as f:
    bugs = json.load(f)

examples = []
for b in bugs:
    desc = (b.get("description", {}) or {}).get("raw", "") or ""
    if not ("Actual Behavior" in desc and "Expected Behavior" in desc and "Steps to reproduce" in desc):
        continue

    proj = b.get("_links", {}).get("project", {}).get("title", "?")
    prio = b.get("_links", {}).get("priority", {}).get("title", "?")
    bt = (b.get("_links", {}).get("customField6", {}) or {}).get("title", "Unknown")
    env_val = (b.get("_links", {}).get("customField9", {}) or {}).get("title", "STAGE")
    cat = (b.get("_links", {}).get("category", {}) or {}).get("title", "")

    examples.append({
        "id": b.get("id"),
        "subject": b.get("subject", ""),
        "description_raw": desc,
        "project": proj,
        "priority": prio,
        "bug_type": bt,
        "environment": env_val,
        "category": cat,
    })

# Save all
with open("training_examples.json", "w", encoding="utf-8") as f:
    json.dump(examples, f, indent=2, ensure_ascii=False)

print(f"Extracted {len(examples)} training examples")

# Pick 20 diverse examples for the few-shot prompt
diverse = []
seen_combos = set()
for ex in examples:
    combo = (ex["project"], ex["bug_type"], ex["priority"])
    if combo not in seen_combos or len(diverse) < 5:
        seen_combos.add(combo)
        diverse.append(ex)
        if len(diverse) >= 20:
            break

with open("training_examples_fewshot.json", "w", encoding="utf-8") as f:
    json.dump(diverse, f, indent=2, ensure_ascii=False)

print(f"Selected {len(diverse)} diverse few-shot examples")
