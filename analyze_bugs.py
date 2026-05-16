"""Extract comprehensive training patterns from all 611 bugs."""
import json
import re

with open("training_data_raw.json", "r", encoding="utf-8-sig") as f:
    bugs = json.load(f)

# ─────────────────────────────────────────
# 1. Analyze title patterns
# ─────────────────────────────────────────
print("=" * 80)
print("1. TITLE PATTERNS")
print("=" * 80)

# Common title starters
starters = {}
for b in bugs:
    title = b.get("subject", "")
    # Get first 3 words
    words = title.split()[:3]
    starter = " ".join(words)
    starters[starter] = starters.get(starter, 0) + 1

print("\nTop 30 title starters (first 3 words):")
for k, v in sorted(starters.items(), key=lambda x: -x[1])[:30]:
    print(f"  [{v:3d}] {k}")

# ─────────────────────────────────────────
# 2. Analyze description formats
# ─────────────────────────────────────────
print("\n" + "=" * 80)
print("2. DESCRIPTION FORMAT PATTERNS")
print("=" * 80)

has_actual = 0
has_expected = 0
has_steps = 0
has_env = 0
has_device = 0
has_os = 0
has_logs = 0
has_cf4 = 0

device_names = []
os_names = []

for b in bugs:
    desc = (b.get("description", {}) or {}).get("raw", "") or ""
    cf4 = (b.get("customField4", {}) or {}).get("raw", "") or ""
    
    if "Actual Behavior" in desc or "actual behavior" in desc.lower():
        has_actual += 1
    if "Expected Behavior" in desc or "expected behavior" in desc.lower():
        has_expected += 1
    if "Steps to reproduce" in desc or "steps to reproduce" in desc.lower():
        has_steps += 1
    if "Test Environment" in desc or "test environment" in desc.lower():
        has_env += 1
    if "Device" in desc:
        has_device += 1
        # Extract device names
        match = re.search(r'\*\*Device[:\*]*\*?\*?\s*(.+?)(?:\n|$)', desc)
        if match:
            device_names.append(match.group(1).strip())
    if "Operating System" in desc:
        has_os += 1
        match = re.search(r'\*\*Operating System[:\*]*\*?\*?\s*(.+?)(?:\n|$)', desc)
        if match:
            os_names.append(match.group(1).strip())
    if "Logs" in desc or "firebase" in desc.lower() or "crashlytics" in desc.lower():
        has_logs += 1
    if cf4.strip():
        has_cf4 += 1

total = len(bugs)
print(f"\nFormat adherence (out of {total} bugs):")
print(f"  Has 'Actual Behavior':     {has_actual:3d} ({has_actual*100//total}%)")
print(f"  Has 'Expected Behavior':   {has_expected:3d} ({has_expected*100//total}%)")
print(f"  Has 'Steps to reproduce':  {has_steps:3d} ({has_steps*100//total}%)")
print(f"  Has 'Test Environment':    {has_env:3d} ({has_env*100//total}%)")
print(f"  Has 'Device':              {has_device:3d} ({has_device*100//total}%)")
print(f"  Has 'Operating System':    {has_os:3d} ({has_os*100//total}%)")
print(f"  Has 'Logs':                {has_logs:3d} ({has_logs*100//total}%)")
print(f"  Has customField4 (Steps):  {has_cf4:3d} ({has_cf4*100//total}%)")

# ─────────────────────────────────────────
# 3. Device name patterns
# ─────────────────────────────────────────
print("\n" + "=" * 80)
print("3. DEVICE NAMES USED")
print("=" * 80)
dev_counts = {}
for d in device_names:
    d_clean = d.strip().rstrip('*').strip()
    dev_counts[d_clean] = dev_counts.get(d_clean, 0) + 1
for k, v in sorted(dev_counts.items(), key=lambda x: -x[1])[:30]:
    print(f"  [{v:3d}] {k}")

# ─────────────────────────────────────────
# 4. OS patterns
# ─────────────────────────────────────────
print("\n" + "=" * 80)
print("4. OS NAMES USED")
print("=" * 80)
os_counts = {}
for o in os_names:
    o_clean = o.strip().rstrip('*').strip()
    os_counts[o_clean] = os_counts.get(o_clean, 0) + 1
for k, v in sorted(os_counts.items(), key=lambda x: -x[1])[:20]:
    print(f"  [{v:3d}] {k}")

# ─────────────────────────────────────────
# 5. HIGH priority bugs (detailed)
# ─────────────────────────────────────────
print("\n" + "=" * 80)
print("5. ALL HIGH PRIORITY BUGS (30 total)")
print("=" * 80)
high_bugs = [b for b in bugs if b.get("_links", {}).get("priority", {}).get("title") == "High"]
for b in high_bugs:
    desc = (b.get("description", {}) or {}).get("raw", "") or ""
    proj = b.get("_links", {}).get("project", {}).get("title", "?")
    bt = (b.get("_links", {}).get("customField6", {}) or {}).get("title", "?")
    cat = (b.get("_links", {}).get("category", {}) or {}).get("title", "?")
    print(f"\n  BUG #{b['id']} | {proj} | {bt} | Cat: {cat}")
    print(f"  Title: {b['subject']}")
    print(f"  Desc preview: {desc[:250]}")

# ─────────────────────────────────────────
# 6. Steps count analysis
# ─────────────────────────────────────────
print("\n" + "=" * 80)
print("6. STEPS TO REPRODUCE ANALYSIS")
print("=" * 80)
step_counts = []
for b in bugs:
    desc = (b.get("description", {}) or {}).get("raw", "") or ""
    # Count numbered steps (1. 2. 3. etc)
    steps = re.findall(r'^\d+\.', desc, re.MULTILINE)
    if steps:
        step_counts.append(len(steps))

if step_counts:
    print(f"  Bugs with numbered steps: {len(step_counts)}")
    print(f"  Min steps: {min(step_counts)}")
    print(f"  Max steps: {max(step_counts)}")
    print(f"  Avg steps: {sum(step_counts) / len(step_counts):.1f}")
    # Distribution
    dist = {}
    for s in step_counts:
        dist[s] = dist.get(s, 0) + 1
    print("  Distribution:")
    for k, v in sorted(dist.items()):
        print(f"    {k} steps: {v} bugs")

# ─────────────────────────────────────────
# 7. Sample BEST formatted bugs (complete)
# ─────────────────────────────────────────
print("\n" + "=" * 80)
print("7. SAMPLE WELL-FORMATTED BUGS (complete description)")
print("=" * 80)

# Find bugs with all sections
best = []
for b in bugs:
    desc = (b.get("description", {}) or {}).get("raw", "") or ""
    if ("Actual Behavior" in desc and "Expected Behavior" in desc 
        and "Steps to reproduce" in desc and "Test Environment" in desc
        and "Device" in desc and "Operating System" in desc
        and len(desc) > 300):
        best.append(b)

print(f"\nFound {len(best)} well-formatted bugs (all sections present)")
# Show 10 diverse examples
shown = 0
seen_cats = set()
for b in best:
    cat = (b.get("_links", {}).get("category", {}) or {}).get("title", "?")
    proj = b.get("_links", {}).get("project", {}).get("title", "?")
    if cat not in seen_cats or shown < 5:
        seen_cats.add(cat)
        desc = (b.get("description", {}) or {}).get("raw", "") or ""
        bt = (b.get("_links", {}).get("customField6", {}) or {}).get("title", "?")
        prio = b.get("_links", {}).get("priority", {}).get("title", "?")
        print(f"\n{'~'*60}")
        print(f"BUG #{b['id']} | {proj} | {prio} | {bt} | Cat: {cat}")
        print(f"Title: {b['subject']}")
        print(f"Description:\n{desc}")
        print(f"{'~'*60}")
        shown += 1
        if shown >= 15:
            break
