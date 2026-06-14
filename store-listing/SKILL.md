---
name: store-listing
description: >
  Use when the user wants to research ASO keywords and generate or refresh localized
  app store listing copy (Apple App Store + Google Play) across many languages. Covers
  the Apify keyword pipeline (discover → score → select) with budget discipline, the
  hard-won actor gotchas, why autocomplete output needs manual topical curation, the
  localization decision framework (localize names per locale; scoped vs full refresh),
  per-store field rules and char limits, the iOS no-duplicate-word + truthfulness rules,
  and a deterministic validate-then-verify loop — derived from building the Kachak
  10-language listing end-to-end. Bundles the actual scripts as reusable templates.
---

# Store Listing (ASO keywords + localized copy) — AI Skill

## 1. When to use / what this produces

Use this when the user needs **localized store listing content driven by real keyword
data** — app name, subtitle (iOS), keyword field (iOS), short + full descriptions —
for one or many languages, without paid ASO suites (AppTweak/Sensor Tower) and without
paid ads.

Two artifacts come out:
1. **Keyword research** — per-locale ranked CSVs (`keyword, popularity, difficulty,
   composite`) + a `summary.md`, produced by an Apify-actor pipeline. Cost ~$2 for a
   10-locale sweep.
2. **Refreshed listing docs** — `docs/store-listing-ios.md` + `docs/store-listing-android.md`
   with every keyword-bearing field rewritten from the curated data and **machine-verified
   against the stores' hard limits**.

The keyword pipeline is a script. The copy generation is done **in-session by the agent**
(no LLM API key, no per-run token cost) — the script stops at the keyword set; the agent
curates and writes the localized prose, gated by a deterministic validator.

Bundled in `scripts/` (copy into `<app-repo>/tool/`):
- `aso_research.py` — the Apify pipeline (pilot/discover/score/select).
- `aso_listing_validate.py` — validate **proposed** fields before writing them.
- `aso_listing_verify.py` — re-parse the **live docs** and confirm limits/rules.
- `requirements.txt` — `apify-client`, `python-dotenv`.

The bundled scripts contain the **Kachak instance** (its seeds, storefronts, and the
final 10-locale field set) as a worked example — adapt the config blocks at the top.


## 2. The pipeline (Apify actor, pay-per-use)

Actor: **`slothtechlabs/aso-keyword-rank-tracker`** — $1 / 1,000 result rows, both
stores, 60+ storefronts, locale-correct. Three modes (`action`):

| Mode | Input | Use |
|---|---|---|
| `keyword-recommendations` | `seedKeyword`, `limit` (1–80) | **Discover** — native autocomplete terms per storefront |
| `keyword-top-apps` | `keywords` (≤100), `topN` (1–20) | **Score** — returns `popularityEstimate` + `difficultyEstimate` (0–100) + `totalResults`, `top10*` |
| `app-rank-tracking` | `apps`, `keywords` | **Later** — track your own rank monthly |

Stages (each independently runnable, all cached & resumable):
1. **Seeds** — an English seed list + rough per-locale translations. Seeds feed discovery
   **only**; they are never final candidates (ASO terms don't translate 1:1 — the native
   store autocomplete is what surfaces real terms).
2. **Discover** — per locale, run `keyword-recommendations` for each seed → dedupe.
3. **Score** — feed ≤100 deduped candidates to `keyword-top-apps` → popularity/difficulty.
4. **Select** — composite `= popularity − w·difficulty`, export ranked CSV + summary.

```
python -m pip install -r tool/requirements.txt
cp tool/.env.example tool/.env   # APIFY_TOKEN=...
python tool/aso_research.py pilot                 # ~$0.01, verify schema FIRST
python tool/aso_research.py discover              # all locales
python tool/aso_research.py score
python tool/aso_research.py select                # free, writes docs/aso/
```


## 3. ★ Pilot first — always verify the live schema before scaling

Run `pilot` (one tiny scoring call, ~8 rows, ~$0.01) and **read the raw JSON** before
spending real money. Output field names are not in the actor docs and differ by mode.
The pilot dumps `First-row fields` and resolves popularity/difficulty so you catch a
field-name mismatch for one cent instead of after a full sweep.


## 4. ★ Actor gotchas (these will silently waste money or produce empty output)

These cost real time to discover. The bundled `aso_research.py` already encodes the fixes:

- **`storefront` must be lowercase** ISO codes (`us`, `vn`, `jp`…). Uppercase → hard
  `Input is not valid` error.
- **The keyword field name differs by mode**: `keyword-recommendations` returns the term
  under **`recommendedKeyword`**; `keyword-top-apps` returns **`keyword`**. If your
  extractor only knows `keyword`, discovery saves *empty caches* while logs say it found
  terms. (Use a field list: `["keyword","recommendedKeyword",…]`.)
- **apify-client ≥3 returns a typed `Run`**, not a dict — use `run.default_dataset_id`,
  not `run["defaultDatasetId"]`.
- **Google Play `keyword-top-apps` returns ~0 rows** (`totalResults=0`); usable data is
  effectively **Apple-only**. Cost-free (0 rows = $0) and selection takes max across
  stores, so it's fine — but know your scoring is Apple-driven.
- **Re-reading an already-executed run's dataset is FREE.** If a bug ate your discovery
  output, list recent runs (`cl.runs().list(...)`), filter by `action`, group rows by
  `storefront` → locale, and rebuild the caches without re-spending. (Saved ~$1.22 on
  Kachak after the `recommendedKeyword` bug.)


## 5. ★ Budget discipline

Free Apify credit is $5 = 5,000 rows. The cost driver is `rows ≈ keywords × topN × stores`.

- **Smallest `topN` that still returns the estimates** — target `topN=1`. Popularity and
  difficulty are *keyword-level*, identical regardless of `topN`; you don't need the apps.
- **One storefront per language**, not per country: `en→us, vi→vn, es→mx, pt→br, de→de,
  fr→fr, ja→jp, hi→in, id→id, th→th`.
- **Hard `--max-rows` guard** (default 3500): the script projects rows and **aborts before
  any paid call** that would exceed it. Run `discover` and `score` as separate processes
  so each gate resets (`discover` ≈3000 projected, `score` ≈2000 — both under 3500).
- **Resumable cache** (`docs/aso/cache/<locale>-<mode>.json`): re-runs skip fetched data.
- A full 10-locale sweep is ~$2 of the $5. Projected ceilings are worst-case (actual is
  far lower because Google returns nothing and dedupe shrinks candidate sets).


## 6. ★ The output is brand-heavy — the data is an input, not the answer

**The biggest trap.** The composite ranking (`popularity − w·difficulty`) does **not**
hand you a keyword set. Two reasons:

1. **Popularity and difficulty are tightly correlated** (most relevant terms cluster at
   pop 70–95 / dif 70–95), so the composite barely separates them and raw popularity
   wins.
2. **Autocomplete is dominated by local bank/retailer brands and generic fragments** —
   the top "keywords" for Kachak came back as VPBank, TOMI (vi), Walmart (es), Snapdeal,
   OYO, hotels, flights (hi), SCB, KBank (th), DeutschlandCard, Klarna (de), Moneytree
   (ja), plus fragments like "Easy", "Cash", "Mon", "der", "com". An exact-match brand
   blocklist can't catch arbitrary local brands.

So **keyword selection is a manual topical curation** from the CSVs:
- Read each `keywords-<locale>.csv` (sorted by composite).
- Drop brands (competitor apps, banks, wallets, retailers — Apple & Google both ban
  brand terms in keyword fields anyway) and off-topic terms (travel/hotel/fashion).
- Keep the **relevant** terms with high popularity. The CSV's real value is *the
  popularity ranking among the topical terms*, plus high-value localized long-tail
  phrases the autocomplete surfaces (e.g. ja `レシート読み取り` 89, de `haushaltsbuch`/
  `belege`/`kassenbon`, vi `sổ chi tiêu cá nhân`/`app theo dõi chi tiêu`).

Treat `summary.md`'s auto-picked "Primary/Secondary" as raw, not final.


## 7. ★ Localization decision framework

Ask the user two things before writing copy — the answers change scope and risk:

**(a) Refresh depth.** If the listings already exist and are polished/accurate, the
**scoped keyword refresh** is almost always right: rewrite only the algorithm-weighted,
keyword-bearing fields (iOS name + subtitle + keyword field; Android name + short
description; promo) and weave a few high-value localized phrases into the descriptions
where natural. A **full from-scratch rewrite** of 10× ~4000-char descriptions is high
effort and high risk (fluency, accuracy, iOS truthfulness) for little extra ASO gain —
descriptions already contain the relevant keywords. Recommend scoped; only go full if the
existing copy is weak or absent.

**(b) App name localization.** The app name is the **most heavily weighted** ASO field.
Localizing the keyword-bearing part per locale is the strongest lever (e.g. de
`Kachak: KI Ausgaben Scanner`, ja `Kachak: AIレシート家計簿`, vi `Kachak: Quản Lý Chi
Tiêu`, es `Kachak: Escáner de Gastos`). Keep the brand token (`Kachak:`) for
recognizability. The alternative — one English name everywhere — is simpler and keeps
brand consistency, with the subtitle + keyword field carrying the localized terms. Default
recommendation: **localize**, keep the brand prefix.


## 8. ★ Per-store field rules & limits

| Field | Store | Limit | Notes |
|---|---|---|---|
| App name | both | 30 | Localize keyword part; keep `Brand:` prefix |
| Subtitle | iOS | 30 | Keyword-rich; **no words repeated from name** |
| Keyword field | iOS | 100 | lowercase, comma-separated, **no spaces between tokens**, **no words from name/subtitle**, no brands; fill it |
| Promotional text | iOS | 170 | Not indexed; editable without review |
| Short description | Android | 80 | Indexed and weighted; keyword-rich; Play truncates silently |
| Full description | both | 4000 | iOS not indexed by Google's algo to the same degree; Android full text IS indexed |

iOS-specific rules baked into the validator:
- **No word duplication across name / subtitle / keyword field** — Apple already indexes
  name+subtitle words, so repeating them in the keyword field wastes characters. Apple
  also auto-combines tokens into phrases and stems singular/plural, so don't include both
  `budget` and `budgets`, and split multi-word terms into atomic tokens in the field.
- **iOS truthfulness** — never claim `notification` capture, `background` service,
  `real-time`/`automatic`/`instant` capture, and never put the `$49.99`-type intro price
  (Android-only) in iOS copy. (Android may legitimately describe notification/background
  capture if the app does it.) Watch negations ("no background tracking") and unrelated
  uses ("recurring transactions generated automatically", "subscription renews
  automatically") — those are fine.
- **Trademark** — no bank/wallet/competitor brand names in any keyword field.


## 9. ★ The validate → write → verify loop

Never hand-count CJK/Thai/Devanagari char limits — automate it. Two scripts, two phases:

1. **Before writing**: put your proposed per-locale fields into `aso_listing_validate.py`
   (the `FIELDS` dict) and run it. It checks every limit, the iOS no-dup rule, brands, and
   forbidden truthfulness terms. Iterate until `ALL GREEN`. Filling under-used keyword
   fields with more curated native terms here is good ASO.
2. **After writing** into the docs: run `aso_listing_verify.py`, which **re-parses the
   live markdown** (not your hardcoded values) and re-checks everything. This catches edit
   mistakes and pre-existing overflows. (On Kachak it caught a German promo at 173/170
   that predated this work.)

`len()` equals Apple's visible-character count for Latin scripts and is a **safe upper
bound** for CJK/Thai/Devanagari (ASC may count slightly fewer) — so green on `len()`
means safe. Always keep the "verify in App Store Connect / Play Console live preview"
note; the store's own counter is the only authority before submit.

**Editing technique for the docs**: the app-name value is identical across locales, so to
change it per-locale match it together with the adjacent (unique) subtitle/short-desc
value as one `old_string` block — that makes each edit unambiguous.


## 10. Kachak worked example (the final set)

10 locales (`en vi es pt de fr ja hi id th`), scoped refresh, localized names.

| loc | App name | iOS subtitle | iOS keyword field (excerpt) |
|---|---|---|---|
| en | Kachak: AI Expense Tracker | Receipt Scanner & Budgets | money,spending,bills,planner,manager,finance,wallet… |
| vi | Kachak: Quản Lý Chi Tiêu | Quét hóa đơn & ngân sách AI | tài chính,tiết kiệm,thu nhập,ví tiền,dòng tiền… |
| es | Kachak: Escáner de Gastos | Presupuesto y dinero con IA | finanzas,control,ingresos,recibos,ahorro… |
| de | Kachak: KI Ausgaben Scanner | Belege & Haushaltsbuch | finanzen,steuer,konten,geld,sparen,budget,kassenbon… |
| ja | Kachak: AIレシート家計簿 | 支出管理をシンプルに | 予算,貯金,節約,収入,お金,家計,カテゴリ,定期… |
| th | Kachak: AI สแกนใบเสร็จ | จัดการเงินและงบประมาณ | รายจ่าย,การเงิน,เงิน,ออมเงิน,รายได้… |

(pt/fr/hi/id follow the same pattern.) All fields machine-verified within limits, no iOS
dups, no brands. Note how each name leads with the locale's single highest-value relevant
term (de `Scanner`, ja `家計簿`/`レシート`, es/pt the local word for expenses).


## 11. Reproduction workflow (new app)

1. **Config the pipeline** — in `aso_research.py` set `SEEDS` (English + rough
   translations), `STOREFRONTS` (one per language, lowercase), `BRAND_BLOCKLIST`.
2. **Pilot** (§3) — verify the live output schema for one cent; patch field-name lists if
   the actor changed.
3. **Discover → Score → Select** (§2, §5) — separate processes; review the CSVs.
4. **Curate** (§6) — per locale, pull the relevant high-popularity terms from each CSV;
   discard brands/fragments/off-topic.
5. **Decide scope + name localization** with the user (§7).
6. **Draft fields** into `aso_listing_validate.py`; iterate to `ALL GREEN` (§8, §9).
7. **Write** the fields into `docs/store-listing-{ios,android}.md`, preserving structure,
   the subscription/publish-gate blocks, privacy/terms URLs, and (scoped) the descriptions.
8. **Verify** with `aso_listing_verify.py`; refresh the char-limit QA tables + the iOS
   truthfulness checklist from the real numbers.

`.env` holds `APIFY_TOKEN` — gitignore `tool/.env`, `tool/.env.*`, and root `/.env`.
Rotate any token ever pasted into a chat/log.


## 12. Verification checklist

Before handing off / uploading:

- [ ] Pilot confirmed the real output schema before any full-scale spend.
- [ ] Each paid stage's projected rows < `--max-rows` and within remaining credit; final
  "Rows this run" reconciles with the Apify console.
- [ ] CSVs spot-checked for 2–3 locales: scores sane; no branded/off-topic terms in the
  curated set.
- [ ] `aso_listing_verify.py` parses the live docs → `ALL WITHIN LIMITS`, no iOS dups.
- [ ] App names ≤30 and localized (brand prefix kept); iOS subtitle ≤30; iOS keyword
  field ≤100, lowercase, comma-separated, no name/subtitle words, no brands; Android
  short ≤80 (watch ones sitting exactly at 80).
- [ ] iOS truthfulness checklist all checked: no notification/background/real-time/
  automatic *capture* claims, no `$49.99` intro price in iOS copy.
- [ ] Privacy/Terms URLs present per store; subscription auto-renew disclosure intact;
  publish-gate note for any not-yet-live Pro/IAP block preserved.
- [ ] Char-limit QA tables in both docs refreshed from the real `len()` numbers.
- [ ] Final human diff + App Store Connect / Play Console live preview before submit.


---

*Reference implementation*: `tool/aso_research.py`, `tool/aso_listing_validate.py`,
`tool/aso_listing_verify.py`, plan `docs/aso-keyword-plan.md`, and the live
`docs/store-listing-{ios,android}.md` in the Kachak repo (`D:\Code\kachak`). The bundled
`scripts/` are copies of those — the per-app config lives in the dicts at the top of each.
