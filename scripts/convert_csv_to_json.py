import csv
import json
import sys

csv.field_size_limit(min(sys.maxsize, 2**30))

input_file = "assets/training_data_6000.csv"
output_file = "assets/training_examples.json"

examples = []

with open(input_file, mode='r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            example = {
                "id": int(row.get("id", 0)) if row.get("id") else 0,
                "subject": row.get("Subject", "").strip(),
                "description_raw": row.get("Description", "").strip(),
                "project": row.get("Project", "").strip(),
                "priority": row.get("Priority", "").strip(),
                "bug_type": row.get("Type", "").strip(),
                "environment": "STAGE", # Assuming stage for all entries, or could try to parse from description
                "category": row.get("Category", "").strip()
            }
            if example["id"] != 0:
                examples.append(example)
        except Exception as e:
            print(f"Error parsing row: {row}. Error: {e}")

print(f"Successfully parsed {len(examples)} examples.")

with open(output_file, mode='w', encoding='utf-8') as f:
    json.dump(examples, f, indent=2, ensure_ascii=False)

print(f"Saved JSON data to {output_file}")
