# ASC REST API Reference — Kachack

Base URL: `https://api.appstoreconnect.apple.com/v1`

## Auth

```python
import jwt, time

def token():
    now = int(time.time())
    return jwt.encode(
        {'iss': ISSUER_ID, 'iat': now, 'exp': now + 1100, 'aud': 'appstoreconnect-v1'},
        KEY_PEM, algorithm='ES256', headers={'kid': KEY_ID},
    )
```

Always regenerate per request. 30 s timeout on `urlopen`. 3 retries with exponential back-off on 500/503.

---

## Text Metadata

### GET existing localizations

```
GET /appInfos/{APP_INFO_ID}/appInfoLocalizations?fields[appInfoLocalizations]=locale
GET /appStoreVersions/{VERSION_ID}/appStoreVersionLocalizations?fields[appStoreVersionLocalizations]=locale
```

### PATCH AppInfoLocalization (name + subtitle)

```
PATCH /appInfoLocalizations/{id}
{
  "data": {
    "type": "appInfoLocalizations",
    "id": "{id}",
    "attributes": { "name": "...", "subtitle": "..." }
  }
}
```

Skip PATCH if `name` and `subtitle` already match — ASC rejects redundant subtitle updates with STATE_ERROR when app is in PREPARE_FOR_SUBMISSION.

### PATCH AppStoreVersionLocalization (description, keywords, promo, whatsNew)

```
PATCH /appStoreVersionLocalizations/{id}
{
  "data": {
    "type": "appStoreVersionLocalizations",
    "id": "{id}",
    "attributes": {
      "description": "...",
      "keywords": "...",
      "promotionalText": "...",
      "whatsNew": "..."    ← blocked on first submission; set after first approval
    }
  }
}
```

---

## Screenshots

### Create screenshot set

```
POST /appScreenshotSets
{
  "data": {
    "type": "appScreenshotSets",
    "attributes": { "screenshotDisplayType": "APP_IPHONE_67" },
    "relationships": {
      "appStoreVersionLocalization": {
        "data": { "type": "appStoreVersionLocalizations", "id": "{ver_loc_id}" }
      }
    }
  }
}
```

Display types: `APP_IPHONE_67` (1290×2796), `APP_IPHONE_65` (1284×2778), `APP_IPAD_PRO_3GEN_129`, etc.

### Check existing sets

```
GET /appStoreVersionLocalizations/{id}/appScreenshotSets?filter[screenshotDisplayType]=APP_IPHONE_67
GET /appScreenshotSets/{id}/appScreenshots?fields[appScreenshots]=fileName&limit=50
```

### Upload screenshot (3 steps)

**Step 1 — Reserve:**
```
POST /appScreenshots
{
  "data": {
    "type": "appScreenshots",
    "attributes": { "fileSize": 240160, "fileName": "01_ai_capture.png" },
    "relationships": {
      "appScreenshotSet": { "data": { "type": "appScreenshotSets", "id": "{set_id}" } }
    }
  }
}
```
Response includes `uploadOperations: [{url, method, requestHeaders, offset, length}]`.

**Step 2 — PUT binary:**
```
PUT {op.url}
Content-Type: image/png
(binary data from offset to offset+length)
```
May be multi-part (multiple ops). Send each chunk separately.

**Step 3 — Commit:**
```
PATCH /appScreenshots/{id}
{
  "data": {
    "type": "appScreenshots",
    "id": "{id}",
    "attributes": { "uploaded": true, "sourceFileChecksum": "{md5_hex}" }
  }
}
```
Checksum is MD5 hex of the full file. ASC processes asynchronously — allow 1–2 min.

### Delete screenshot

```
DELETE /appScreenshots/{id}
```

---

## Subscription Pricing

### Fetch all territories

```
GET /territories?limit=200
```
Returns 175 territories (ISO alpha-3 codes: USA, GBR, VNM, …).

### Fetch price ladder (one territory)

```
GET /subscriptions/{sub_id}/pricePoints
  ?filter[territory]={territory}
  &fields[subscriptionPricePoints]=customerPrice
  &limit=200
```

Paginated. Monthly tier targets (T1 $9.99 → index 126) fit in 1 page.  
Annual tier targets (T1 $69.99 → index 386) need 2 pages.  
Full ladder has ~800 points.

### Fetch existing prices

```
GET /subscriptions/{sub_id}/prices
  ?include=territory
  &fields[territories]=currency
  &limit=200
```

Paginated. Returns territory codes for all set prices.

### Set price

```
POST /subscriptionPrices
{
  "data": {
    "type": "subscriptionPrices",
    "attributes": { "startDate": null },
    "relationships": {
      "subscription":           { "data": { "type": "subscriptions",           "id": "{sub_id}" } },
      "subscriptionPricePoint": { "data": { "type": "subscriptionPricePoints", "id": "{pp_id}" } }
    }
  }
}
```

**Do NOT include `preserved` attribute** — causes 409 ENTITY_ERROR.ATTRIBUTE.NOT_ALLOWED.

---

## Subscription Availability

`subscriptionAvailabilities` (without "plan") is **deprecated**.

```
POST /subscriptionPlanAvailabilities
{
  "data": {
    "type": "subscriptionPlanAvailabilities",
    "attributes": { "availableInNewTerritories": true },
    "relationships": {
      "subscription": { "data": { "type": "subscriptions", "id": "{sub_id}" } },
      "availableTerritories": { "data": [] }   ← empty = all territories
    }
  }
}
```

---

## Introductory Offers (Free Trial)

Territory relationship is **required** — one POST per territory (175 per subscription).

```
POST /subscriptionIntroductoryOffers
{
  "data": {
    "type": "subscriptionIntroductoryOffers",
    "attributes": {
      "offerMode": "FREE_TRIAL",
      "duration": "ONE_WEEK",
      "numberOfPeriods": 1,
      "startDate": null,
      "endDate": null
    },
    "relationships": {
      "subscription": { "data": { "type": "subscriptions", "id": "{sub_id}" } },
      "territory":    { "data": { "type": "territories",   "id": "{territory_3letter}" } }
    }
  }
}
```

Duration values: `ONE_DAY`, `THREE_DAYS`, `ONE_WEEK`, `TWO_WEEKS`, `ONE_MONTH`, `TWO_MONTHS`, `THREE_MONTHS`, `SIX_MONTHS`, `ONE_YEAR`.  
Offer modes: `FREE_TRIAL`, `PAY_AS_YOU_GO`, `PAY_UP_FRONT`.

### Delete introductory offer

```
DELETE /subscriptionIntroductoryOffers/{id}
```

### List existing offers

```
GET /subscriptions/{sub_id}/introductoryOffers?include=territory&limit=200
```

---

## Subscription Promotional Image

```
POST /subscriptionImages
{
  "data": {
    "type": "subscriptionImages",
    "attributes": { "fileSize": 240160, "fileName": "promo.png" },
    "relationships": {
      "subscription": { "data": { "type": "subscriptions", "id": "{sub_id}" } }
    }
  }
}
```

Same 3-step upload as screenshots (reserve → PUT → PATCH with `uploaded:true` + MD5).

---

## Known Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| 409 ENTITY_ERROR.ATTRIBUTE.NOT_ALLOWED | `preserved: false` in subscriptionPrices POST | Remove `preserved` entirely |
| 409 "must provide territory relationship" | introductoryOffer POST without territory | POST one offer per territory |
| 403 FORBIDDEN_ERROR on subscriptionAvailabilities | Endpoint is deprecated | Use `subscriptionPlanAvailabilities` |
| 500 UNEXPECTED_ERROR | Transient ASC server error | Retry with exponential back-off (10s × attempt) |
| STATE_ERROR on subtitle PATCH | App in PREPARE_FOR_SUBMISSION, no change | Fetch current value first; skip if unchanged |
| Empty price ladder | Some territories (e.g. BMU) have no price points | Skip gracefully with `continue` |

---

## Pagination Pattern

```python
results = []
url = '/some/endpoint?limit=200'
while url:
    resp = get(url)
    results.extend(resp.get('data', []))
    url = resp.get('links', {}).get('next')
```

---

## Performance Notes

- Parallel workers (8 concurrent) safe for pricing and screenshot uploads.
- Rate limits: not officially documented; 8 concurrent requests observed without throttling.
- Skip already-set records before fetching ladders — biggest speedup on re-runs.
- Single page (200 items) sufficient for monthly price targets; 2 pages for annual.
