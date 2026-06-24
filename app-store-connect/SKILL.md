---
name: app-store-connect
description: Use this skill when the user asks to submit an iOS app to the App Store, clear "Add for Review" blockers, upload metadata/screenshots, set pricing, manage subscriptions, or automate anything in App Store Connect via the REST API.
version: 2.0.0
---

# App Store Connect — Full Submission Flow

## Overview

This skill covers the complete journey from a ready build to "Submitted for Review". Most steps can be automated via the ASC REST API. A few are portal-only (noted below).

---

## 1. Credentials Setup

All API calls need an ES256 JWT signed with an ASC API key.

**Get the key:** ASC → Users and Access → Integrations → App Store Connect API → generate a key. Download the `.p8` once (cannot re-download). Note the Key ID and Issuer ID.

**JWT generation (Node.js — most reliable):**

```bash
node -e "
const fs=require('fs'),{createSign}=require('crypto');
const pem=fs.readFileSync('/path/to/AuthKey_KEYID.p8','utf8');
const enc=o=>Buffer.from(JSON.stringify(o)).toString('base64url');
const now=Math.floor(Date.now()/1000);
const s=enc({alg:'ES256',kid:'KEY_ID',typ:'JWT'})+'.'+enc({iss:'ISSUER_UUID',iat:now,exp:now+1200,aud:'appstoreconnect-v1'});
fs.writeFileSync('/tmp/asc_jwt.txt',s+'.'+createSign('sha256').update(s).sign({key:pem,dsaEncoding:'ieee-p1363'},'base64url'));
"
JWT=$(cat /tmp/asc_jwt.txt)
```

**JWT generation (Python — alternative):**

```python
import jwt, time
token = jwt.encode(
    {'iss': ISSUER_ID, 'iat': int(time.time()), 'exp': int(time.time())+1100, 'aud': 'appstoreconnect-v1'},
    KEY_PEM, algorithm='ES256', headers={'kid': KEY_ID}
)
```

**Rules:**
- Regenerate per request — tokens expire in 20 min, reuse risks 401
- Always use `curl -g` when the URL contains `[...]` (e.g. `?fields[apps]=bundleId`) — without `-g`, curl treats `[apps]` as a glob and fails silently with HTTP 000
- 3 retries with exponential back-off on 500/503
- 30s timeout per request

**Health check before any script run:**
```bash
CODE=$(curl --max-time 15 -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $JWT" \
  "https://api.appstoreconnect.apple.com/v1/apps/APP_ID?fields[apps]=bundleId")
[[ "$CODE" != "200" ]] && echo "ASC down ($CODE) — abort" && exit 1
```

ASC has real outages (check Reddit/developer forums). All 500s during an outage look identical to app-specific errors — always health-check first.

---

## 2. Find App Constants

```bash
# App ID
curl -g -s -H "Authorization: Bearer $JWT" \
  "https://api.appstoreconnect.apple.com/v1/apps?filter[bundleId]=YOUR.BUNDLE.ID&fields[apps]=id" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['data'][0]['id'])"

# App Info ID (needed for category, age rating, privacy URL)
curl -s -H "Authorization: Bearer $JWT" \
  "https://api.appstoreconnect.apple.com/v1/apps/APP_ID/appInfos?limit=1" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['data'][0]['id'])"

# Version ID (for current PREPARE_FOR_SUBMISSION version)
curl -s -H "Authorization: Bearer $JWT" \
  "https://api.appstoreconnect.apple.com/v1/apps/APP_ID/appStoreVersions?filter[appStoreState]=PREPARE_FOR_SUBMISSION" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['data'][0]['id'])"
```

---

## 3. App Information (one-time setup)

### Content Rights
```bash
PATCH /apps/APP_ID
{"data":{"type":"apps","id":"APP_ID","attributes":{"contentRightsDeclaration":"DOES_NOT_USE_THIRD_PARTY_CONTENT"}}}
# or "USES_THIRD_PARTY_CONTENT" if the app contains licensed content
```

### Primary & Secondary Category
Categories live on `appInfos`, NOT on `apps`. Do NOT try `PATCH /apps/APP_ID` with category relationships — it will 409.

```bash
PATCH /appInfos/APP_INFO_ID
{
  "data": {
    "type": "appInfos",
    "id": "APP_INFO_ID",
    "relationships": {
      "primaryCategory":   {"data": {"type": "appCategories", "id": "FINANCE"}},
      "secondaryCategory": {"data": {"type": "appCategories", "id": "PRODUCTIVITY"}}
    }
  }
}
```

Common category IDs: `FINANCE`, `PRODUCTIVITY`, `UTILITIES`, `LIFESTYLE`, `HEALTH_AND_FITNESS`, `BUSINESS`, `EDUCATION`, `ENTERTAINMENT`, `SOCIAL_NETWORKING`.

### Price — Free App
```bash
# 1. Find the Free price point for USA
curl -g -s -H "Authorization: Bearer $JWT" \
  "https://api.appstoreconnect.apple.com/v1/apps/APP_ID/appPricePoints?filter[territory]=USA&limit=10" \
  | python3 -c "
import json,sys
for p in json.load(sys.stdin)['data']:
    if p['attributes']['customerPrice']=='0.00':
        print(p['id']); break"

# 2. Create price schedule
POST /appPriceSchedules
{
  "data": {
    "type": "appPriceSchedules",
    "relationships": {
      "app":            {"data": {"type": "apps",           "id": "APP_ID"}},
      "basePricePoint": {"data": {"type": "appPricePoints", "id": "FREE_PRICE_POINT_ID"}}
    }
  }
}
```

If `GET /apps/APP_ID/appPriceSchedule` returns 200, a schedule already exists — no action needed.

### Privacy Policy URL
Privacy URL lives on `appInfoLocalizations` (per-locale, under appInfos), NOT on `apps`.

```bash
# Get all localization IDs
GET /appInfos/APP_INFO_ID/appInfoLocalizations?limit=25

# Patch each locale
PATCH /appInfoLocalizations/LOC_ID
{"data":{"type":"appInfoLocalizations","id":"LOC_ID","attributes":{"privacyPolicyUrl":"https://yoursite.com/privacy.html"}}}
```

### Support URL
Support URL lives on `appStoreVersionLocalizations` (per-locale, under the version).

```bash
# Get all version localization IDs
GET /appStoreVersions/VERSION_ID/appStoreVersionLocalizations?limit=50

# Patch each locale
PATCH /appStoreVersionLocalizations/VER_LOC_ID
{"data":{"type":"appStoreVersionLocalizations","id":"VER_LOC_ID","attributes":{"supportUrl":"https://yoursite.com/support"}}}
```

### iPhone-Only (no iPad)
In `ios/Runner.xcodeproj/project.pbxproj`, set all occurrences:
```
TARGETED_DEVICE_FAMILY = "1";   ← iPhone only
TARGETED_DEVICE_FAMILY = "1,2"; ← iPhone + iPad (default Flutter)
```

Change all 3 occurrences (Debug, Release, Profile build configs). Requires a new build upload — the portal reflects whatever the binary declares. ASC will stop requiring iPad screenshots once a new iPhone-only binary is processed.

Verify after build:
```bash
grep -r "UIDeviceFamily" build/ios/archive/Runner.xcarchive/Products/Applications/Runner.app/Info.plist
# Should show only <integer>1</integer>
```

---

## 4. Age Rating

The `ageRatingDeclaration` ID is **the same as `APP_INFO_ID`**.

```bash
# Get current (to confirm the ID)
GET /appInfos/APP_INFO_ID/ageRatingDeclaration

# Set 4+ (finance/productivity app with no mature content)
PATCH /ageRatingDeclarations/APP_INFO_ID
{
  "data": {
    "type": "ageRatingDeclarations",
    "id": "APP_INFO_ID",
    "attributes": {
      "ageAssurance": false,
      "advertising": false,
      "alcoholTobaccoOrDrugUseOrReferences": "NONE",
      "contests": "NONE",
      "gambling": false,
      "gamblingSimulated": "NONE",
      "gunsOrOtherWeapons": "NONE",
      "healthOrWellnessTopics": false,
      "horrorOrFearThemes": "NONE",
      "kidsAgeBand": null,
      "lootBox": false,
      "matureOrSuggestiveThemes": "NONE",
      "medicalOrTreatmentInformation": "NONE",
      "messagingAndChat": false,
      "parentalControls": false,
      "profanityOrCrudeHumor": "NONE",
      "sexualContentGraphicAndNudity": "NONE",
      "sexualContentOrNudity": "NONE",
      "unrestrictedWebAccess": false,
      "userGeneratedContent": false,
      "violenceCartoonOrFantasy": "NONE",
      "violenceRealistic": "NONE",
      "violenceRealisticProlongedGraphicOrSadistic": "NONE"
    }
  }
}
```

**Critical gotchas:**
- `ageAssurance` is **required** — omitting it returns 409 "You must provide a value for 'ageAssurance'"
- Attribute names changed in ~2024. Old names like `alcoholTobaccoDrugs` return 409 ENTITY_ERROR.ATTRIBUTE.UNKNOWN. Use the full new names above.
- Types are mixed: booleans (`gambling`, `unrestrictedWebAccess`) vs strings (`"NONE"`, `"MILD"`, `"FREQUENT_AND_INTENSE"`). Sending the wrong type returns 409.

---

## 5. App Privacy Nutrition Labels

**⚠️ Portal-only — the `appDataUsages` API endpoint was removed from the ASC REST API (returns 404 PATH_ERROR).**

Do this manually in ASC portal: App Privacy section → answer the questionnaire → Publish.

**Do NOT forget to click Publish** — unpublished labels are a submission blocker.

Typical answers for a finance app with AI/backend processing:
- Contact Info: Name, Email → App Functionality, linked to identity
- Identifiers: User ID, Device ID → App Functionality, linked
- Financial Info: Other Financial Info (user-entered expenses) → App Functionality, linked
- User Content: Photos or Videos (screenshots for AI), Audio Data (voice capture) → App Functionality, not linked
- Usage Data: Product Interaction (analytics) → Analytics, not linked
- Diagnostics: Crash Data, Performance Data → App Functionality, not linked
- Not used for tracking (no ad/cross-app SDKs)

For "Do you or your third-party partners use [data type] for tracking?" — answer **No** for each data type if no ad network or cross-app tracking SDKs are integrated.

---

## 6. Text Metadata

### App Info Localizations (name, subtitle, privacy URL)
```bash
GET /appInfos/APP_INFO_ID/appInfoLocalizations?limit=25
PATCH /appInfoLocalizations/LOC_ID
{"data":{"type":"appInfoLocalizations","id":"LOC_ID","attributes":{"name":"App Name","subtitle":"Short tagline","privacyPolicyUrl":"https://..."}}}
```

### Version Localizations (description, keywords, whatsNew, supportUrl)
```bash
GET /appStoreVersions/VERSION_ID/appStoreVersionLocalizations?limit=50
PATCH /appStoreVersionLocalizations/VER_LOC_ID
{"data":{"type":"appStoreVersionLocalizations","id":"VER_LOC_ID","attributes":{"description":"...","keywords":"...","promotionalText":"...","supportUrl":"https://..."}}}
```

`whatsNew` is blocked on first submission — set it after the first version is approved.

Skip PATCH if value already matches — ASC returns STATE_ERROR on redundant subtitle updates when app is in PREPARE_FOR_SUBMISSION.

---

## 7. Screenshots

Display type for iPhone 16 Pro Max: `APP_IPHONE_67` (1290×2796).

**3-step upload:**

```bash
# Step 1 — Reserve
POST /appScreenshots
{"data":{"type":"appScreenshots","attributes":{"fileSize":240160,"fileName":"01_screen.png"},
 "relationships":{"appScreenshotSet":{"data":{"type":"appScreenshotSets","id":"SET_ID"}}}}}
# Response: uploadOperations with presigned URL

# Step 2 — PUT binary
PUT {uploadOperation.url}   (Content-Type: image/png, raw bytes)

# Step 3 — Commit
PATCH /appScreenshots/SCREENSHOT_ID
{"data":{"type":"appScreenshots","id":"SCREENSHOT_ID","attributes":{"uploaded":true,"sourceFileChecksum":"MD5_HEX"}}}
```

Checksum = MD5 hex of the full file. ASC processes asynchronously after commit (allow 1–2 min).

To create a screenshot set first:
```bash
POST /appScreenshotSets
{"data":{"type":"appScreenshotSets","attributes":{"screenshotDisplayType":"APP_IPHONE_67"},
 "relationships":{"appStoreVersionLocalization":{"data":{"type":"appStoreVersionLocalizations","id":"VER_LOC_ID"}}}}}
```

---

## 8. Subscriptions

See `references/api-reference.md` for full subscription pricing, group localizations, availability, introductory offers, and review screenshot flows.

**Quick checklist for subscription readiness:**
- [ ] Subscription group has at least one `subscriptionGroupLocalization` → clears `MISSING_METADATA`
- [ ] Each plan has a `subscriptionAppStoreReviewScreenshot` uploaded → clears `MISSING_METADATA`
- [ ] Prices set for all desired territories via `subscriptionPrices`
- [ ] Availability set via `subscriptionPlanAvailabilities` (NOT deprecated `subscriptionAvailabilities`)
- [ ] Introductory offers (free trial) set per territory if desired

---

## 9. Build Upload & Attachment

**Build the IPA (Flutter):**
```bash
flutter build ipa --release \
  --dart-define=API_BASE_URL=https://yourapi.com/api \
  --dart-define=REVENUECAT_IOS_KEY=appl_xxx
```

**Upload:**
```bash
xcrun altool --upload-app -f build/ios/ipa/*.ipa \
  --apiKey KEY_ID --apiIssuer ISSUER_UUID
```
Or open Xcode Organizer → Distribute App → App Store Connect.

**Wait for processing, then attach to version:**
```bash
# Find the build
GET /apps/APP_ID/builds?sort=-uploadedDate&limit=1&fields[builds]=version,processingState
# Wait for processingState = VALID

# Attach
PATCH /appStoreVersions/VERSION_ID
{"data":{"type":"appStoreVersions","id":"VERSION_ID",
 "relationships":{"build":{"data":{"type":"builds","id":"BUILD_ID"}}}}}
```

---

## 10. Pre-Submission Checklist

Run these via API to confirm everything is in order before clicking Submit:

```bash
# Content rights
GET /apps/APP_ID?fields[apps]=contentRightsDeclaration

# Category
GET /apps/APP_ID/appInfos?limit=1&include=primaryCategory

# Price
GET /apps/APP_ID/appPriceSchedule

# Privacy URLs (all locales)
GET /appInfos/APP_INFO_ID/appInfoLocalizations?limit=25

# Support URLs (all locales)
GET /appStoreVersions/VERSION_ID/appStoreVersionLocalizations?limit=50

# Age rating
GET /appInfos/APP_INFO_ID/ageRatingDeclaration

# Build attached
GET /appStoreVersions/VERSION_ID?include=build
```

**Portal-only checks (must verify in browser):**
- App Privacy published (not just saved)
- Price shows "Free" or correct tier in Pricing and Availability
- Device availability matches binary (iPhone-only if TARGETED_DEVICE_FAMILY=1)

---

## 11. Final Submission

Export compliance (if app uses HTTPS/TLS — standard exemption):
```bash
POST /appEncryptionDeclarations
{"data":{"type":"appEncryptionDeclarations","attributes":{"usesEncryption":true,"exempt":true,
 "containsThirdPartyEncryption":false,"containsProprietaryCryptography":false,"availableOnFrenchStore":true,"platform":"IOS"},
 "relationships":{"app":{"data":{"type":"apps","id":"APP_ID"}}}}}

# Link to version
PATCH /appStoreVersions/VERSION_ID
{"data":{"type":"appStoreVersions","id":"VERSION_ID",
 "relationships":{"appEncryptionDeclaration":{"data":{"type":"appEncryptionDeclarations","id":"DECL_ID"}}}}}
```

App Review contact:
```bash
POST /appStoreReviewDetails
{"data":{"type":"appStoreReviewDetails","attributes":{
  "contactFirstName":"First","contactLastName":"Last",
  "contactPhone":"+1...","contactEmail":"email@example.com",
  "demoAccountRequired":false,"notes":""},
 "relationships":{"appStoreVersion":{"data":{"type":"appStoreVersions","id":"VERSION_ID"}}}}}
```

**Submit for Review: portal only** — ASC portal → version → Submit for Review. There is no API endpoint to trigger submission.

---

## What Cannot Be Automated (Portal-Only)

| Task | Why |
|------|-----|
| App Privacy nutrition labels | `appDataUsages` API endpoint removed (~2024) |
| Final "Submit for Review" | No API endpoint |
| App icon | Comes from the IPA binary |
| `whatsNew` on first submission | ASC blocks it until v1 is approved |

---

## Known API Gotchas

| Symptom | Cause | Fix |
|---------|-------|-----|
| curl HTTP 000, no response | URL has `[...]` and `-g` flag missing | Always use `curl -g` |
| 409 ENTITY_ERROR.ATTRIBUTE.UNKNOWN on age rating | Old attribute names (e.g. `alcoholTobaccoDrugs`) | Use new names from the full list above |
| 409 "must provide value for 'ageAssurance'" | Missing required field | Add `"ageAssurance": false` |
| 409 on category PATCH via `/apps` | Categories are not on the `apps` resource | Use `PATCH /appInfos/APP_INFO_ID` |
| 404 on `appDataUsages` | Endpoint removed from API | Do App Privacy in portal |
| 409 ENTITY_ERROR.ATTRIBUTE.NOT_ALLOWED on subscriptionPrices | `preserved` field included | Omit `preserved` entirely |
| MISSING_METADATA on subscription | Review screenshot not uploaded OR group missing locale | POST to `subscriptionAppStoreReviewScreenshots`; POST `subscriptionGroupLocalizations` |
| 403 on `subscriptionAvailabilities` | Endpoint deprecated | Use `subscriptionPlanAvailabilities` |
| STATE_ERROR on subtitle PATCH | Value unchanged in PREPARE_FOR_SUBMISSION | Fetch current first; skip if same |
| 500 on specific locale records | Apple server-side shard issue | Retry later; if persistent during outage wait for ASC recovery |
| Broad 500s across all endpoints | ASC outage | Check Reddit/Apple developer forums; wait |

---

## Kachak App Constants

```
APP_ID      = '6780402754'
APP_INFO_ID = 'c81e812c-bdd2-48d9-80f4-9b8fc33381ff'
VERSION_ID  = '3c871617-abf8-4430-bb81-fcc640aaaf83'
BUNDLE_ID   = 'site.devtor.kachakapp'
MONTHLY_SUB = '6780403485'
ANNUAL_SUB  = '6780403462'

KEY_ID      = '7A4R6NKH7R'
KEY_PATH    = '/Users/admin/Downloads/AuthKey_7A4R6NKH7R.p8'
ISSUER_ID   = 'b6f1bf4f-ad53-4391-94c3-402ae1622742'
```

App Info Localizations (under appInfos — for name, subtitle, privacy URL):
```
en-US  (query GET /appInfos/APP_INFO_ID/appInfoLocalizations to get IDs)
```

Version Localizations (under appStoreVersions — for description, supportUrl):
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
