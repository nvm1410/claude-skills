#!/usr/bin/env python3
"""Parse the live listing docs and verify the keyword-driven fields.

Reads docs/store-listing-ios.md + docs/store-listing-android.md, extracts the
per-locale App name / Subtitle / Keywords / Short description straight from the
markdown, and checks the App Store / Play hard limits + the iOS no-duplicate-word
rule. Prints a per-locale table. Exit 0 = all within limits.
"""
from __future__ import annotations
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "docs" / "store-listing-ios.md"
AND = ROOT / "docs" / "store-listing-android.md"
LOCALES = ["en","vi","es","pt","de","fr","ja","hi","id","th"]
LIM = {"name":30,"subtitle":30,"keywords":100,"short":80}

def sections(text: str) -> dict[str,str]:
    """Split a doc into per-locale chunks keyed by the locale code in '## xx — ...'."""
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+([a-z]{2})\s+—", line)
        if m:
            if cur: out[cur] = "\n".join(buf)
            cur, buf = m.group(1), []
        elif cur is not None:
            buf.append(line)
    if cur: out[cur] = "\n".join(buf)
    return out

def grab(chunk: str, label: str) -> str | None:
    # value is the first backtick-quoted string at/after the label line
    m = re.search(re.escape(label) + r"[^\n`]*\n*`([^`]*)`", chunk)
    return m.group(1) if m else None

def tok(s): return {t for t in re.split(r"[\s,&]+", s.lower()) if t}

def main():
    ios = sections(IOS.read_text(encoding="utf-8"))
    andr = sections(AND.read_text(encoding="utf-8"))
    bad = 0
    print(f"{'loc':4} {'name':>6} {'sub':>6} {'kw':>7} {'short':>7}")
    rows = {}
    for loc in LOCALES:
        i, a = ios.get(loc,""), andr.get(loc,"")
        name = grab(i, "**App name")
        sub = grab(i, "**Subtitle")
        kw = grab(i, "**Keywords")
        short = grab(a, "**Short description")
        vals = {"name":name,"subtitle":sub,"keywords":kw,"short":short}
        rows[loc] = vals
        cells = []
        for k in ("name","subtitle","keywords","short"):
            v = vals[k]
            if v is None:
                cells.append("MISS"); bad += 1; continue
            n = len(v); over = n > LIM[k]
            if over: bad += 1
            cells.append(f"{n}{'!' if over else ''}")
        print(f"{loc:4} {cells[0]:>6} {cells[1]:>6} {cells[2]:>7} {cells[3]:>7}")
        # iOS no-dup keyword vs name/subtitle
        if name and sub and kw:
            ktoks = {t for part in kw.split(",") for t in re.split(r"\s+", part.strip()) if t}
            dup = (ktoks & (tok(name)|tok(sub))) - {"ai","ia","ki"}
            if dup:
                print(f"     DUP {loc}: {sorted(dup)}"); bad += 1
    print("\n" + ("ALL WITHIN LIMITS" if bad==0 else f"{bad} PROBLEM(S)"))
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
