#!/usr/bin/env python3
"""ASO keyword research pipeline for Kachak.

Drives the Apify actor `slothtechlabs/aso-keyword-rank-tracker` to discover,
score, and select keywords per locale, then exports ranked CSVs + a summary.
Listing copy generation is done in-session by the agent (not here) — this script
stops at the keyword set + a deterministically-packed iOS keyword field.

Design goals (see docs/aso-keyword-plan.md):
  * Pilot-first: inspect the real output schema before scaling.
  * Budget-capped: the actor bills $1 / 1,000 result rows; free credit = $5.
    Every paid call is projected and gated by --max-rows.
  * Resumable: each (locale, mode) result is cached to docs/aso/cache/ so a
    re-run never pays twice.

Usage:
  python -m pip install -r tool/aso_requirements.txt
  cp tool/.env.example tool/.env   # then fill APIFY_TOKEN
  python tool/aso_research.py pilot                  # ~20 rows, verify schema
  python tool/aso_research.py discover               # all locales
  python tool/aso_research.py score                  # all locales
  python tool/aso_research.py select                 # no API cost
  python tool/aso_research.py all --locale vi        # one locale end-to-end
Flags:
  --locale xx     restrict to a single locale
  --max-rows N    hard budget guard (default 3500); abort before exceeding
  --top-n N       apps returned per keyword when scoring (default 1; raise only
                  if the pilot shows the estimates need it)
  --force         ignore cache and re-fetch (re-spends credit)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

try:
    from apify_client import ApifyClient
except ImportError:
    sys.exit("Missing deps. Run: python -m pip install -r tool/aso_requirements.txt")

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
ACTOR_ID = "slothtechlabs/aso-keyword-rank-tracker"
STORES = ["apple", "google"]
COST_PER_1000_ROWS = 1.00  # USD

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "aso"
CACHE_DIR = OUT_DIR / "cache"

# One representative storefront per app locale (language). Country, not locale.
STOREFRONTS = {
    "en": "us", "vi": "vn", "es": "mx", "pt": "br", "de": "de",
    "fr": "fr", "ja": "jp", "hi": "in", "id": "id", "th": "th",
}

# Seeds feed DISCOVERY only — they are never final candidates (ASO terms do not
# translate 1:1; the actor's recommendations surface the real native terms).
# Edit freely; rough translations are fine.
SEEDS = {
    "en": ["expense tracker", "budget app", "receipt scanner", "spending tracker", "money manager"],
    "vi": ["theo dõi chi tiêu", "ứng dụng ngân sách", "quét hóa đơn", "quản lý tiền", "sổ chi tiêu"],
    "es": ["control de gastos", "app de presupuesto", "escáner de recibos", "gestor de dinero", "registro de gastos"],
    "pt": ["controle de gastos", "app de orçamento", "scanner de recibos", "gerenciador de dinheiro", "registro de despesas"],
    "de": ["ausgaben tracker", "haushaltsbuch", "budget app", "geld verwalten", "kassenbon scanner"],
    "fr": ["suivi des dépenses", "gestion budget", "scanner de reçus", "gestion d'argent", "carnet de dépenses"],
    "ja": ["家計簿", "支出管理", "予算 アプリ", "レシート 読み取り", "お金 管理"],
    "hi": ["खर्च ट्रैकर", "बजट ऐप", "रसीद स्कैनर", "पैसे का प्रबंधन", "खर्च प्रबंधन"],
    "id": ["pelacak pengeluaran", "aplikasi anggaran", "pemindai struk", "pengelola uang", "catatan keuangan"],
    "th": ["บันทึกรายจ่าย", "แอพงบประมาณ", "สแกนใบเสร็จ", "จัดการเงิน", "ติดตามค่าใช้จ่าย"],
}

RECO_LIMIT = 30          # related terms per seed per store (discovery)
PRIMARY_COUNT = 5
SECONDARY_COUNT = 15
DIFFICULTY_WEIGHT = 0.5  # composite = popularity - w * difficulty
MIN_POPULARITY = 5       # drop near-zero-demand terms

# Brand / trademark blocklist — never put competitor or bank/wallet brands in a
# keyword field (repo trademark rule + Apple/Google both ban it). Extend freely.
BRAND_BLOCKLIST = {
    "momo", "gcash", "paypal", "venmo", "cashapp", "revolut", "wise", "zelle",
    "mint", "ynab", "monzo", "wallet by", "google pay", "apple pay", "vcb",
    "techcombank", "mbbank", "zalopay", "shopeepay", "grabpay", "truemoney",
    # Competitor expense/budget apps surfaced by the actor's autocomplete.
    "expensify", "everydollar", "rocket", "pocketguard", "spendee", "monefy",
    "goodbudget", "emma", "copilot", "fudget", "moneylover", "splitwise",
    "quickbooks", "freshbooks", "walnut", "buddy", "fastbudget", "wallet",
    "money lover", "rocket money", "buddy budget",
}

# Candidate field names for the two estimates — confirmed/adjusted after pilot.
POPULARITY_FIELDS = ["popularityEstimate", "popularity", "popularityScore", "volume"]
DIFFICULTY_FIELDS = ["difficultyEstimate", "difficulty", "difficultyScore"]
# `keyword-top-apps` rows use `keyword`; `keyword-recommendations` rows use
# `recommendedKeyword`. List both so discover + score share one extractor.
KEYWORD_FIELDS = ["keyword", "recommendedKeyword", "term", "query"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def client() -> ApifyClient:
    if load_dotenv:
        load_dotenv(ROOT / "tool" / ".env")
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("APIFY_TOKEN not set. Copy tool/.env.example to tool/.env and fill it.")
    return ApifyClient(token)


def first_field(item: dict, names: list[str], default=None):
    for n in names:
        if n in item and item[n] not in (None, ""):
            return item[n]
    return default


def cache_path(locale: str, mode: str) -> Path:
    return CACHE_DIR / f"{locale}-{mode}.json"


def load_cache(locale: str, mode: str):
    p = cache_path(locale, mode)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save_cache(locale: str, mode: str, items: list):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(locale, mode).write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class Budget:
    """Tracks projected/spent rows and aborts before exceeding --max-rows."""

    def __init__(self, max_rows: int):
        self.max_rows = max_rows
        self.spent = 0

    def gate(self, projected: int, label: str):
        total = self.spent + projected
        cost = total / 1000 * COST_PER_1000_ROWS
        print(f"  [budget] {label}: +{projected} rows -> {total} total (~${cost:.2f})")
        if total > self.max_rows:
            sys.exit(f"ABORT: would exceed --max-rows ({self.max_rows}). "
                     f"Raise it deliberately or narrow --locale.")

    def charge(self, rows: int):
        self.spent += rows


def run_actor(cl: ApifyClient, run_input: dict) -> list[dict]:
    run = cl.actor(ACTOR_ID).call(run_input=run_input)
    if not run:
        return []
    # apify-client <2 returns a dict; >=3 returns a typed Run model.
    ds_id = run["defaultDatasetId"] if isinstance(run, dict) else run.default_dataset_id
    return list(cl.dataset(ds_id).iterate_items())


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #
def cmd_pilot(cl: ApifyClient, args, budget: Budget):
    """Tiny scoring call to confirm the real output schema before scaling."""
    kws = SEEDS["en"][:4]
    projected = len(kws) * args.top_n * len(STORES)
    budget.gate(projected, "pilot score (en/US)")
    items = run_actor(cl, {
        "action": "keyword-top-apps",
        "stores": STORES,
        "storefront": STOREFRONTS["en"],
        "keywords": kws,
        "topN": args.top_n,
    })
    budget.charge(len(items))
    raw = CACHE_DIR / "pilot_raw.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGot {len(items)} rows. Saved raw output -> {raw}")
    if items:
        keys = sorted(items[0].keys())
        print("First-row fields:", keys)
        pop = first_field(items[0], POPULARITY_FIELDS, "<MISSING>")
        dif = first_field(items[0], DIFFICULTY_FIELDS, "<MISSING>")
        print(f"popularity -> {pop} | difficulty -> {dif}")
        if pop == "<MISSING>" or dif == "<MISSING>":
            print("ADJUST POPULARITY_FIELDS / DIFFICULTY_FIELDS at the top of this "
                  "script to match the real field names above, then re-run.")


def cmd_discover(cl: ApifyClient, args, budget: Budget):
    for locale in target_locales(args):
        if not args.force and load_cache(locale, "discover") is not None:
            print(f"[{locale}] discover: cached, skipping")
            continue
        seeds = SEEDS.get(locale, SEEDS["en"])
        projected = len(seeds) * RECO_LIMIT * len(STORES)
        budget.gate(projected, f"{locale} discover")
        found: dict[str, dict] = {}
        for seed in seeds:
            items = run_actor(cl, {
                "action": "keyword-recommendations",
                "stores": STORES,
                "storefront": STOREFRONTS[locale],
                "seedKeyword": seed,
                "limit": RECO_LIMIT,
            })
            budget.charge(len(items))
            for it in items:
                kw = first_field(it, KEYWORD_FIELDS)
                if kw:
                    found.setdefault(kw.strip().lower(), it)
        save_cache(locale, "discover", list(found.values()))
        print(f"[{locale}] discover: {len(found)} unique candidates")


def cmd_score(cl: ApifyClient, args, budget: Budget):
    for locale in target_locales(args):
        if not args.force and load_cache(locale, "score") is not None:
            print(f"[{locale}] score: cached, skipping")
            continue
        disc = load_cache(locale, "discover")
        if disc is None:
            print(f"[{locale}] score: no discovery cache — run discover first")
            continue
        candidates = []
        for it in disc:
            kw = first_field(it, KEYWORD_FIELDS)
            if kw and kw.strip().lower() not in {b.lower() for b in BRAND_BLOCKLIST}:
                candidates.append(kw.strip())
        candidates = list(dict.fromkeys(candidates))[:100]  # actor cap
        projected = len(candidates) * args.top_n * len(STORES)
        budget.gate(projected, f"{locale} score ({len(candidates)} kw)")
        items = run_actor(cl, {
            "action": "keyword-top-apps",
            "stores": STORES,
            "storefront": STOREFRONTS[locale],
            "keywords": candidates,
            "topN": args.top_n,
        })
        budget.charge(len(items))
        save_cache(locale, "score", items)
        print(f"[{locale}] score: {len(items)} rows")


def cmd_select(cl, args, budget):
    """No API cost: compute composite, export CSV + summary."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = ["# ASO keyword selection\n",
               "_Generated by tool/aso_research.py. Seeds/weights in the script._\n"]
    for locale in target_locales(args):
        rows = load_cache(locale, "score")
        if rows is None:
            print(f"[{locale}] select: no score cache — run score first")
            continue
        # Collapse to one record per keyword (max popularity across stores/apps).
        agg: dict[str, dict] = {}
        for it in rows:
            kw = first_field(it, KEYWORD_FIELDS)
            if not kw:
                continue
            pop = _num(first_field(it, POPULARITY_FIELDS, 0))
            dif = _num(first_field(it, DIFFICULTY_FIELDS, 0))
            cur = agg.setdefault(kw.strip(), {"keyword": kw.strip(), "pop": 0, "dif": 0})
            cur["pop"] = max(cur["pop"], pop)
            cur["dif"] = max(cur["dif"], dif)
        scored = []
        for r in agg.values():
            if r["pop"] < MIN_POPULARITY:
                continue
            if r["keyword"].lower() in {b.lower() for b in BRAND_BLOCKLIST}:
                continue
            r["composite"] = round(r["pop"] - DIFFICULTY_WEIGHT * r["dif"], 2)
            scored.append(r)
        scored.sort(key=lambda r: r["composite"], reverse=True)

        csv_path = OUT_DIR / f"keywords-{locale}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["keyword", "pop", "dif", "composite"])
            w.writeheader()
            w.writerows(scored)

        primary = [r["keyword"] for r in scored[:PRIMARY_COUNT]]
        secondary = [r["keyword"] for r in scored[PRIMARY_COUNT:PRIMARY_COUNT + SECONDARY_COUNT]]
        ios_field = pack_ios_keyword_field(primary + secondary)
        summary += [
            f"\n## {locale} (storefront {STOREFRONTS[locale]})\n",
            f"- **Primary:** {', '.join(primary) or '—'}",
            f"- **Secondary:** {', '.join(secondary) or '—'}",
            f"- **iOS keyword field ({len(ios_field)}/100):** `{ios_field}`",
            f"- Full ranked list: `docs/aso/keywords-{locale}.csv` ({len(scored)} terms)",
        ]
        print(f"[{locale}] select: {len(scored)} scored -> {csv_path.name}")

    (OUT_DIR / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT_DIR / 'summary.md'}")


def cmd_all(cl, args, budget):
    cmd_discover(cl, args, budget)
    cmd_score(cl, args, budget)
    cmd_select(cl, args, budget)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def pack_ios_keyword_field(keywords: list[str], limit: int = 100) -> str:
    """Greedily pack atomic, deduped tokens into <=limit chars, comma-separated,
    no spaces. Apple auto-combines tokens into phrases, so split to words."""
    seen, tokens = set(), []
    for kw in keywords:
        for tok in re.split(r"\s+", kw.strip().lower()):
            tok = tok.strip(",")
            if tok and tok not in seen and len(tok) > 1:
                seen.add(tok)
                tokens.append(tok)
    out = ""
    for tok in tokens:
        cand = tok if not out else out + "," + tok
        if len(cand) > limit:
            continue
        out = cand
    return out


def target_locales(args) -> list[str]:
    if args.locale:
        if args.locale not in STOREFRONTS:
            sys.exit(f"Unknown locale '{args.locale}'. Known: {', '.join(STOREFRONTS)}")
        return [args.locale]
    return list(STOREFRONTS)


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="Kachak ASO keyword research pipeline")
    p.add_argument("command", choices=["pilot", "discover", "score", "select", "all"])
    p.add_argument("--locale", help="restrict to one locale (e.g. vi)")
    p.add_argument("--max-rows", type=int, default=3500, help="budget guard (rows)")
    p.add_argument("--top-n", type=int, default=1, help="apps per keyword when scoring")
    p.add_argument("--force", action="store_true", help="ignore cache, re-fetch")
    args = p.parse_args()

    budget = Budget(args.max_rows)
    needs_api = args.command != "select"
    cl = client() if needs_api else None

    {
        "pilot": cmd_pilot, "discover": cmd_discover, "score": cmd_score,
        "select": cmd_select, "all": cmd_all,
    }[args.command](cl, args, budget)

    if needs_api:
        cost = budget.spent / 1000 * COST_PER_1000_ROWS
        print(f"\nDone. Rows this run: {budget.spent} (~${cost:.2f}).")


if __name__ == "__main__":
    main()
