---
name: app-store-connect
description: This skill should be used when the user asks to "upload screenshots to App Store", "set App Store pricing", "manage subscriptions in ASC", "upload store listing metadata", "automate App Store Connect", "set subscription prices for all territories", "upload subscription image", or anything involving the App Store Connect REST API.
version: 1.0.0
---

# App Store Connect Automation

Most of the iOS App Store listing can be automated via the ASC REST API. No Xcode or App Store Connect UI required for metadata, screenshots, pricing, and subscriptions.

## What Can Be Automated

| Task | Script | API resource |
|------|--------|--------------|
| Text metadata (name, subtitle, description, keywords) | `tool/asc_upload_listing.py` | `appInfoLocalizations`, `appStoreVersionLocalizations` |
| Screenshots (all locales) | `tool/asc_upload_screenshots.py` | `appScreenshotSets`, `appScreenshots` |
| Subscription pricing (all 175 territories) | `tool/asc_price_all_territories.py` | `subscriptionPrices`, `subscriptionPricePoints` |
| Subscription review screenshot | inline script (see references) | `subscriptionAppStoreReviewScreenshots` |
| Subscription availability | `POST /subscriptionPlanAvailabilities` | `subscriptionPlanAvailabilities` |
| Introductory offers / free trial | `POST /subscriptionIntroductoryOffers` | `subscriptionIntroductoryOffers` |

**Cannot be automated via API:**
- App icon — comes from the submitted build binary (IPA). Upload via Xcode.
- App Privacy nutrition label — portal-only questionnaire.

## Credentials

All scripts read from `/tmp/`:

```
/tmp/asc_key.p8       — ES256 private key (downloaded from ASC → Users & Access → Keys)
/tmp/asc_key_id.txt   — Key ID (e.g. R7U77NV4U2)
/tmp/asc_issuer_id.txt — Issuer ID (UUID from same page)
```

JWT token: ES256, `aud=appstoreconnect-v1`, `exp=now+1100`. Regenerate per request — no caching needed (SDK auto-refreshes).

## Kachack App Constants

```
APP_ID      = '6780402754'
APP_INFO_ID = 'c81e812c-bdd2-48d9-80f4-9b8fc33381ff'
VERSION_ID  = '3c871617-abf8-4430-bb81-fcc640aaaf83'
MONTHLY     = '6780403485'
ANNUAL      = '6780403462'
```

Version localization IDs (10 locales, all exist):

```
en-US  995d0e55-c3b6-45c1-b1a7-8dfc7e90d23b
de-DE  809225a1-a4ed-477f-8fd1-ce9d520fc7c3
es-ES  ae78c18d-bd4f-4bcf-92ed-97a7d21b6b1d
fr-FR  ca87e5aa-2434-4c2b-9d87-1559cdff0803
hi     b5b052a9-67c4-47da-ab53-4fe72fa4abff
id     4326273f-ab8e-4564-b80b-18bccc549f52
ja     4772b0fd-4e01-410a-b752-ad8a6dcd019d
pt-BR  86177cfc-c7d4-440d-b7cf-df26b864953d
th     482f949f-f358-45a5-9b8c-b3654bace257
vi     d1d65c94-583d-4c30-a449-2425734d46d3
```

## Running the Scripts

```bash
# Dry-run first, then live
python3 tool/asc_upload_listing.py --dry-run
python3 tool/asc_upload_listing.py

python3 tool/asc_upload_screenshots.py --dry-run
python3 tool/asc_upload_screenshots.py
python3 tool/asc_upload_screenshots.py --locale ja        # single locale
python3 tool/asc_upload_screenshots.py --force            # re-upload existing

python3 tool/asc_price_all_territories.py --dry-run
python3 tool/asc_price_all_territories.py
```

## Screenshots — iOS-Specific Rules

Display type: `APP_IPHONE_67` (1290×2796).  
Source: `screenshots/appstore/` (en-US root) + `screenshots/appstore/{locale}/` (others).

**iOS order** (08 first; skip 01 and 03 — Android-only features):
```
08_ios_capture.png   ← first (iOS share-sheet capture story)
02_transactions.png
04_dashboard.png
05_review_queue.png
06_budgets.png
07_insights.png
```

**Android** (7 frames, skip 08): `01–07_*.png` in order.

## Pricing — Tier-Index Method

Apple's price ladder is consistent across currencies: same index = same relative tier.

1. Fetch USA price ladder for each subscription (monthly + annual).
2. Find the index of each USD tier target ($9.99, $6.99, $4.99, $2.99).
3. For every other territory, fetch its ladder and pick the same index.

Tier targets:

| Tier | Monthly | Annual | Countries |
|------|---------|--------|-----------|
| T1 | $9.99 | $69.99 | US, EU core, JP, SG, AU, Gulf |
| T2 | $6.99 | $49.99 | ES, KR, Baltics, ROU/BGR, Gulf T2 |
| T3 | $4.99 | $34.99 | LatAm, ASEAN-mid, CIS, MENA |
| T4 | $2.99 | $19.99 | South/SE Asia, Africa |

**Page budget**: monthly tier targets fit in 1 page (max index 126 / 200). Annual needs 2 pages (max index 386 / 400). The script handles this automatically.

## Key API Gotchas

- `subscriptionAvailabilities` (without "plan") is **deprecated**. Use `subscriptionPlanAvailabilities`.
- `preserved` attribute is **not allowed** in `subscriptionPrices` POST — omit it entirely.
- Screenshot upload is 3-step: reserve → PUT binary → PATCH with MD5 checksum.
- Introductory offers require a `territory` relationship — one POST per territory (175 POSTs).
- `appStoreVersionIcon` (app icon) cannot be uploaded via REST API for iOS — comes from the IPA binary.
- Subscription **review screenshot** = `subscriptionAppStoreReviewScreenshots` (required by App Store review). `subscriptionImages` is a separate promotional image — do not confuse the two. Subscription state shows `MISSING_METADATA` until the review screenshot is uploaded. POST one per plan (monthly + annual). `GET_COLLECTION` is not allowed on this resource.

## Additional Resources

- **`references/api-reference.md`** — full endpoint reference, request/response shapes, all known error codes and fixes
