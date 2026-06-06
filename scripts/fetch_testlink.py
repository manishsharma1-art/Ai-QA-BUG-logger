#!/usr/bin/env python3
"""
fetch_testlink.py – Pull all sanity test cases from TestLink and save to JSON.

Re-run whenever TestLink content is updated; overwrites the output file each time.

Usage:
    python scripts/fetch_testlink.py [--key KEY] [--suite-id ID] [--out PATH]

Defaults:
    --key      env TESTLINK_API_KEY  (falls back to built-in default)
    --suite-id 26691
    --out      assets/testlink_cases.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import warnings
import xmlrpc.client
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_URL = "https://testlink.intermesh.net/lib/api/xmlrpc/v1/xmlrpc.php"
_DEFAULT_KEY = "cd116deb373b2257d244ab81e43243ce"
_DEFAULT_SUITE_ID = 26691
_DEFAULT_OUT = "assets/testlink_cases.json"
_TC_ID_PREFIX = "AND-"


# ---------------------------------------------------------------------------
# HTML → plain-text conversion (stdlib only)
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    """Minimal, dependency-free HTML-to-plaintext converter.

    Strategy
    --------
    * ``convert_charrefs=True`` decodes all HTML entities at parse time
      (``&amp;`` → ``&``, ``&nbsp;`` → U+00A0, ``&gt;`` → ``>``, etc.).
    * Block-level tags (``<p>``, ``<br>``, ``<div>``, …) are turned into a
      single space so sentences do not run together.
    * ``<li>`` items get a leading newline so they can be processed as
      discrete segments before the final whitespace-collapse pass.
    * The caller calls ``get_text()`` which collapses every run of
      whitespace (including newlines) into a single space and strips
      surrounding whitespace.
    """

    _BLOCK_TAGS = frozenset(
        {
            "p",
            "div",
            "br",
            "ol",
            "ul",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "table",
            "tr",
            "td",
            "th",
            "blockquote",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        tag = tag.lower()
        if tag == "li":
            # Newline before each list item so segments stay separable
            self._buf.append("\n")
        elif tag in self._BLOCK_TAGS:
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._BLOCK_TAGS or tag == "li":
            self._buf.append(" ")

    def handle_data(self, data: str) -> None:
        # convert_charrefs=True already decoded entities; normalise NBSP → space
        self._buf.append(data.replace("\u00a0", " "))

    def get_text(self) -> str:
        raw = "".join(self._buf)
        # First pass: clean each newline-delimited segment (li items are segments)
        segments = [re.sub(r"[ \t]+", " ", seg).strip() for seg in raw.split("\n")]
        segments = [s for s in segments if s]
        # Join with a space; collapse any residual multi-space runs
        joined = " ".join(segments)
        return re.sub(r" {2,}", " ", joined).strip()


def _strip_html(raw: str) -> str:
    """Strip HTML markup and return clean plain text.

    * Unescapes all HTML entities (``&gt;``, ``&lt;``, ``&quot;``, ``&#39;``,
      ``&nbsp;``, etc.) via *convert_charrefs*.
    * Converts ``<li>`` items to newline-separated plain text then collapses
      all whitespace to a single space.
    * Is tolerant of malformed HTML (best-effort).
    * Returns ``""`` for falsy input.
    """
    if not raw or not raw.strip():
        return ""
    stripper = _HTMLStripper()
    try:
        stripper.feed(raw)
    except Exception:
        # Malformed HTML: return whatever text was extracted so far
        pass
    return stripper.get_text()


# ---------------------------------------------------------------------------
# Suite traversal
# ---------------------------------------------------------------------------


def _get_all_suites(
    server: xmlrpc.client.ServerProxy,
    key: str,
    parent_id: int,
    depth: int = 0,
) -> list[dict]:
    """Recursively fetch every descendant test suite of *parent_id*.

    Returns a flat list of::

        {suite_id: int, name: str, parent_id: int, depth: int}

    ``depth`` starts at 1 for direct children of *parent_id*.
    Handles an empty or error response from the API gracefully.
    """
    try:
        result = server.tl.getTestSuitesForTestSuite(
            {"devKey": key, "testsuiteid": parent_id}
        )
    except Exception as exc:
        warnings.warn(f"Could not fetch child suites of suite {parent_id}: {exc}")
        return []

    # The API returns a dict keyed by suite_id, or an empty list/dict on no children
    if not result or not isinstance(result, dict):
        return []

    suites: list[dict] = []
    for _, suite in result.items():
        try:
            sid = int(suite["id"])
            entry: dict = {
                "suite_id": sid,
                "name": str(suite.get("name", "")),
                "parent_id": int(suite.get("parent_id", parent_id)),
                "depth": depth + 1,
            }
            suites.append(entry)
            # Recurse into this suite's children
            suites.extend(_get_all_suites(server, key, sid, depth + 1))
        except Exception:
            continue

    return suites


# ---------------------------------------------------------------------------
# Test-case parsing helpers
# ---------------------------------------------------------------------------


def _is_disabled_action(text: str) -> bool:
    """Return True when a step action has been marked disabled in TestLink."""
    return text.strip().lower().startswith("(disabled)")


def _parse_tc(tc: dict) -> dict | None:
    """Convert a raw TestLink TC dict into the normalised output schema.

    Returns ``None`` if the TC is too malformed to be useful.
    """
    tc_external_id = str(tc.get("tc_external_id", "")).strip()
    if not tc_external_id:
        return None

    tc_id = f"{_TC_ID_PREFIX}{tc_external_id}"
    name = str(tc.get("name", "")).strip()
    module = _strip_html(str(tc.get("tsuite_name", ""))).strip()
    preconditions = _strip_html(str(tc.get("preconditions", ""))).strip()

    raw_steps: list = tc.get("steps") or []
    if not isinstance(raw_steps, list):
        raw_steps = []

    # Guarantee step ordering regardless of API return order
    try:
        raw_steps = sorted(raw_steps, key=lambda s: int(s.get("step_number", 0)))
    except Exception:
        pass

    steps: list[str] = []
    expected_outcomes: list[str] = []

    for step in raw_steps:
        if not isinstance(step, dict):
            continue

        # Skip steps explicitly marked inactive in TestLink
        if str(step.get("active", "1")) == "0":
            continue

        action = _strip_html(str(step.get("actions", ""))).strip()

        # Skip placeholder "(Disabled)" steps
        if not action or _is_disabled_action(action):
            continue

        expected = _strip_html(str(step.get("expected_results", ""))).strip()

        steps.append(action)
        expected_outcomes.append(expected)

    return {
        "tc_id": tc_id,
        "name": name,
        "module": module,
        "preconditions": preconditions,
        "steps": steps,
        "expected_outcomes": expected_outcomes,
        "step_count": len(steps),
    }


# ---------------------------------------------------------------------------
# Main data-pipeline
# ---------------------------------------------------------------------------


def _fetch_all(
    server: xmlrpc.client.ServerProxy,
    key: str,
    root_suite_id: int,
) -> tuple[list[dict], int]:
    """Traverse the root suite module-by-module and return (records, skipped).

    Fetches test cases per top-level suite with ``deep=True`` (not on the
    root suite itself – that call is too slow) so each module's entire
    sub-tree is retrieved in one request.
    """

    # ── Step 1: discover the 44 top-level module suites ──────────────────────
    print(f"Fetching top-level suites under root {root_suite_id}…", flush=True)
    try:
        raw_suites = server.tl.getTestSuitesForTestSuite(
            {"devKey": key, "testsuiteid": root_suite_id}
        )
    except Exception as exc:
        print(f"ERROR: Could not fetch root suites: {exc}", file=sys.stderr)
        sys.exit(1)

    if not raw_suites or not isinstance(raw_suites, dict):
        print("ERROR: Root suite returned no child suites.", file=sys.stderr)
        sys.exit(1)

    top_suites: list[dict] = []
    for _, suite in raw_suites.items():
        try:
            top_suites.append(
                {"suite_id": int(suite["id"]), "name": str(suite.get("name", ""))}
            )
        except Exception:
            continue

    top_suites.sort(key=lambda s: s["suite_id"])
    total = len(top_suites)
    print(f"Found {total} top-level module suites.\n", flush=True)

    # ── Step 2: fetch TCs module by module ───────────────────────────────────
    results: list[dict] = []
    seen_ids: set[str] = set()  # keyed by tc_external_id for deduplication
    skipped = 0

    for idx, suite in enumerate(top_suites, start=1):
        sid: int = suite["suite_id"]
        sname: str = suite["name"]
        print(f"[{idx}/{total}] Fetching: {sname} ({sid})…", flush=True)

        try:
            raw_tcs = server.tl.getTestCasesForTestSuite(
                {
                    "devKey": key,
                    "testsuiteid": sid,
                    "deep": True,
                    "details": "full",
                }
            )
        except Exception as exc:
            warnings.warn(f"  Skipping suite {sid} ({sname}): {exc}")
            continue

        if not raw_tcs or not isinstance(raw_tcs, list):
            print(f"  → No test cases returned.", flush=True)
            continue

        suite_count = 0

        for tc in raw_tcs:
            if not isinstance(tc, dict):
                continue

            tc_external_id = str(tc.get("tc_external_id", "")).strip()

            if not tc_external_id:
                skipped += 1
                continue

            # Deduplicate across modules (deep=True can surface the same TC in
            # both parent and child suite responses)
            if tc_external_id in seen_ids:
                skipped += 1
                continue
            seen_ids.add(tc_external_id)

            try:
                parsed = _parse_tc(tc)
            except Exception as exc:
                warnings.warn(f"  Warning: failed to parse TC {tc_external_id}: {exc}")
                skipped += 1
                continue

            if parsed is None:
                skipped += 1
                continue

            results.append(parsed)
            suite_count += 1

        print(f"  → {suite_count} test cases collected.", flush=True)

    return results, skipped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_testlink",
        description=(
            "Fetch all sanity test cases from TestLink (XML-RPC) and write "
            "them to a JSON file for downstream use."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--key",
        default=os.environ.get("TESTLINK_API_KEY", _DEFAULT_KEY),
        metavar="KEY",
        help="TestLink developer API key (env: TESTLINK_API_KEY)",
    )
    parser.add_argument(
        "--suite-id",
        type=int,
        default=_DEFAULT_SUITE_ID,
        dest="suite_id",
        metavar="ID",
        help="Root test-suite ID to traverse",
    )
    parser.add_argument(
        "--out",
        default=_DEFAULT_OUT,
        metavar="PATH",
        help="Destination JSON file path",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    api_key: str = args.key
    root_suite_id: int = args.suite_id
    out_path = Path(args.out)

    print(f"TestLink fetch started", flush=True)
    print(f"  API URL   : {_API_URL}", flush=True)
    print(f"  Suite ID  : {root_suite_id}", flush=True)
    print(f"  Output    : {out_path}\n", flush=True)

    server = xmlrpc.client.ServerProxy(_API_URL, allow_none=True)

    # Quick sanity-check that the endpoint is reachable; non-fatal if it fails
    try:
        ping = server.tl.sayHello()
        print(f"API ping: {ping}", flush=True)
    except Exception as exc:
        print(
            f"Warning: sayHello() failed ({exc}); attempting data fetch anyway.",
            flush=True,
        )

    records, skipped = _fetch_all(server, api_key, root_suite_id)

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    module_count = len({r["module"] for r in records})
    print(f"\nSaved {len(records)} test cases from {module_count} modules → {out_path}")
    if skipped:
        print(
            f"Skipped {skipped} entry/entries "
            "(duplicates, missing ID, parse errors, or disabled steps)."
        )


if __name__ == "__main__":
    main()
