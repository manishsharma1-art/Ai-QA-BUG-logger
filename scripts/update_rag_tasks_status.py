"""
One-shot script to refresh `.kiro/specs/rag-few-shot-retrieval/tasks.md` so the
status markers reflect what is actually committed on `feat/rag-few-shot-retrieval`.

Marks Phase 0-9 (top-level tasks 1..10) and all of their children as `[x]`.
Leaves Phase 10 (deploy gate) and Phases 11-13 (deploy + post-deploy + rollback)
as `[ ]` because the deploy gate has not been crossed.

Idempotent: re-running has no further effect after first run.
"""
from pathlib import Path
import re

TASKS = Path(".kiro/specs/rag-few-shot-retrieval/tasks.md")

# Top-level tasks to mark complete: 1 (Phase 0) through 10 (Phase 9 local verify).
# Tasks 11..14 stay open.
DONE_PARENTS = {"1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10."}

text = TASKS.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
out = []

# Regex: indented "- [ ] N.M ..." or "- [ ]* N.M ..." (note optional star).
LEAF_RE = re.compile(r"^(\s+)- \[ \](\*?) (\d+\.\d+) ")
PARENT_RE = re.compile(r"^- \[ \] (\d+)\. ")

for line in lines:
    leaf_m = LEAF_RE.match(line)
    parent_m = PARENT_RE.match(line)

    if leaf_m:
        leaf_id = leaf_m.group(3)  # e.g. "1.1", "10.7"
        major = leaf_id.split(".")[0] + "."
        if major in DONE_PARENTS:
            line = line.replace("- [ ]", "- [x]", 1)
    elif parent_m:
        parent_num = parent_m.group(1) + "."
        if parent_num in DONE_PARENTS:
            line = line.replace("- [ ]", "- [x]", 1)

    out.append(line)

new = "".join(out)

if new != text:
    TASKS.write_text(new, encoding="utf-8")
    print(f"Updated {TASKS}")
else:
    print("No changes (already up to date)")
