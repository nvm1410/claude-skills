---
name: revenuecat
description: >
  Use when the user wants to integrate RevenueCat into a Flutter app with a NestJS
  backend: what to automate via RC REST API v2, what requires dashboard clicks, how
  to wire the Flutter SDK (purchases_flutter), and how to build a backend entitlement
  service (3-path fast-path DB → RC REST fallback → free). Covers iOS App Store +
  Google Play product creation, entitlement/offering/package setup, webhook auth,
  sandbox testing, and the pre-production checklist — derived from building the
  full Kachak billing stack end-to-end.
---

# RevenueCat Integration — AI Skill

## 1. When to use / what this produces

Use this when the user needs to add subscription billing to a Flutter app and wants
RevenueCat as the billing seam. Covers the full stack:

- **RC project configuration** — project, apps (iOS + Android), entitlement, offering,
  packages, products, and all the inter-object attachments
- **Flutter SDK wiring** (`purchases_flutter`) — init, setUser, purchase, restore,
  real price display, paywall CTA lifecycle
- **NestJS backend** — `RevenueCatService` (REST API subscriber lookup),
  `EntitlementService` (3-path resolution), webhook endpoint, env var setup
- **What can be automated** vs what requires the RC dashboard or App Store Console

What gets built:
1. A configured RC project with iOS + Android apps, `pro` entitlement, `default`
   offering, `$rc_monthly` / `$rc_annual` packages wired to real store products
2. `BillingService` in Flutter (full implementation, not a stub)
3. `RevenueCatService` + updated `EntitlementService` in NestJS
4. A webhook endpoint with shared-secret auth

---

## 2. What can be automated (RC REST API v2)

The RC REST API v2 (`https://api.revenuecat.com/v2/`) covers almost all project
configuration. All calls use `Authorization: Bearer <sk_xxx>` (the **secret key**
from RC dashboard → Project Settings → API Keys → Secret keys).

### Automatable via API

| Action | Endpoint | Notes |
|--------|----------|-------|
| Create project | `POST /v2/projects` | `{"name": "..."}` |
| Create iOS app | `POST /v2/projects/{id}/apps` | Nested format: `{"type":"app_store","app_store":{"bundle_id":"..."}}` |
| Create Android app | `POST /v2/projects/{id}/apps` | `{"type":"play_store","play_store":{"package_name":"..."}}` |
| Create entitlement | `POST /v2/projects/{id}/entitlements` | `{"lookup_key":"pro","display_name":"Pro"}` — `lookup_key` **must match** the string in `_kEntitlementId` in `BillingService` |
| Create offering | `POST /v2/projects/{id}/offerings` | `{"lookup_key":"default","display_name":"Default"}` |
| Create packages | `POST /v2/projects/{id}/offerings/{id}/packages` | One call each for `$rc_monthly` and `$rc_annual` |
| Create products (iOS) | `POST /v2/projects/{id}/products` | `{"store_identifier":"<bundle>.pro.monthly","type":"subscription","app_id":"<app_id>"}` — **omit** `subscription` duration field (RC infers from store) |
| Create products (Android) | `POST /v2/projects/{id}/products` | `store_identifier` must be `subscriptionId:basePlanId` (e.g. `kachak_pro_monthly:base`) |
| Attach product → entitlement | `POST /v2/projects/{id}/entitlements/{id}/actions/attach_products` | Body: `{"product_ids":["<product_id>",...]}` |
| Attach product → package | `POST /v2/projects/{id}/packages/{id}/actions/attach_products` | Body: `{"products":[{"product_id":"<id>","eligibility_criteria":"all"}]}` — note `products` array with objects, NOT `product_ids` |

**Critical gotcha — two different body formats:**
- Entitlement → product: `{"product_ids": ["id1", "id2"]}` (flat array of strings)
- Package → product: `{"products": [{"product_id": "id1", "eligibility_criteria": "all"}]}` (array of objects)

Mixing these up gives 4xx errors that look identical until you read the field names in the error body.

### Must be done in the RC dashboard

| Action | Where | Notes |
|--------|-------|-------|
| Get SDK public keys | Dashboard → Project → API Keys → Public SDK keys | `appl_xxx` (iOS), `goog_xxx` (Android) — passed as `--dart-define` at build time, intentionally embeddable |
| Configure webhook | Dashboard → Project → Integrations → Webhooks | URL + Authorization header; no API endpoint for this |
| Add iOS In-App Purchase key | Dashboard → iOS app → App Store Connect | Generate `.p8` in ASC → Users and Access → Integrations → In-App Purchase; paste Key ID, Issuer ID, key content. **Skip for sandbox.** |
| Add Google Play service account | Dashboard → Android app → Google Play | Upload service account JSON from Google Cloud Console. **Skip for sandbox.** |
| Check webhook delivery logs | Dashboard → Integrations → Webhooks | Delivery history, retry, inspect payloads |

### Must be done outside RC entirely

| Action | Where |
|--------|-------|
| Create App Store subscriptions | App Store Connect → Monetization → Subscriptions |
| Create Google Play subscriptions | Google Play Console → Monetization → Subscriptions → create base plan |
| Create sandbox tester | ASC → Users and Access → Sandbox Testers (use `+sandbox` email alias; existing Apple IDs cannot be sandbox testers) |
| Set regional pricing | ASC or Play Console per-territory price editor |

---

## 3. RC project setup (full automation script)

Prerequisite: drop the RC secret key into `/tmp/rc_secret.txt` (single line, no newline).

```bash
RC_SECRET=$(cat /tmp/rc_secret.txt)
RC_API="https://api.revenuecat.com/v2"
AUTH="Authorization: Bearer $RC_SECRET"

# 1. Create project (skip if already exists — note the project ID from response)
curl -s -X POST "$RC_API/projects" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"name":"<AppName>"}' | jq '{id:.id,name:.name}'

PROJECT_ID="<id from above>"

# 2. iOS app
curl -s -X POST "$RC_API/projects/$PROJECT_ID/apps" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"type":"app_store","app_store":{"bundle_id":"<bundle.id>"}}' | jq '{id:.id}'

IOS_APP_ID="<id from above>"

# 3. Android app
curl -s -X POST "$RC_API/projects/$PROJECT_ID/apps" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"type":"play_store","play_store":{"package_name":"<package.name>"}}' | jq '{id:.id}'

ANDROID_APP_ID="<id from above>"

# 4. Entitlement (lookup_key MUST match _kEntitlementId in BillingService)
curl -s -X POST "$RC_API/projects/$PROJECT_ID/entitlements" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"lookup_key":"pro","display_name":"Pro"}' | jq '{id:.id}'

ENTITLEMENT_ID="<id from above>"

# 5. Default offering
curl -s -X POST "$RC_API/projects/$PROJECT_ID/offerings" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"lookup_key":"default","display_name":"Default"}' | jq '{id:.id}'

OFFERING_ID="<id from above>"

# 6. Packages ($rc_monthly and $rc_annual are RC reserved identifiers)
curl -s -X POST "$RC_API/projects/$PROJECT_ID/offerings/$OFFERING_ID/packages" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"lookup_key":"$rc_monthly","display_name":"Monthly"}' | jq '{id:.id}'

MONTHLY_PKG_ID="<id from above>"

curl -s -X POST "$RC_API/projects/$PROJECT_ID/offerings/$OFFERING_ID/packages" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"lookup_key":"$rc_annual","display_name":"Annual"}' | jq '{id:.id}'

ANNUAL_PKG_ID="<id from above>"

# 7. Products — iOS
curl -s -X POST "$RC_API/projects/$PROJECT_ID/products" -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"store_identifier\":\"<bundle>.pro.monthly\",\"type\":\"subscription\",\"app_id\":\"$IOS_APP_ID\"}" | jq '{id:.id}'

IOS_MONTHLY_PRODUCT_ID="<id from above>"

curl -s -X POST "$RC_API/projects/$PROJECT_ID/products" -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"store_identifier\":\"<bundle>.pro.annual\",\"type\":\"subscription\",\"app_id\":\"$IOS_APP_ID\"}" | jq '{id:.id}'

IOS_ANNUAL_PRODUCT_ID="<id from above>"

# 8. Products — Android (store_identifier = subscriptionId:basePlanId)
curl -s -X POST "$RC_API/projects/$PROJECT_ID/products" -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"store_identifier\":\"<app>_pro_monthly:base\",\"type\":\"subscription\",\"app_id\":\"$ANDROID_APP_ID\"}" | jq '{id:.id}'

ANDROID_MONTHLY_PRODUCT_ID="<id from above>"

curl -s -X POST "$RC_API/projects/$PROJECT_ID/products" -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"store_identifier\":\"<app>_pro_annual:base\",\"type\":\"subscription\",\"app_id\":\"$ANDROID_APP_ID\"}" | jq '{id:.id}'

ANDROID_ANNUAL_PRODUCT_ID="<id from above>"

# 9. Attach products → entitlement (flat product_ids array)
curl -s -X POST "$RC_API/projects/$PROJECT_ID/entitlements/$ENTITLEMENT_ID/actions/attach_products" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"product_ids\":[\"$IOS_MONTHLY_PRODUCT_ID\",\"$IOS_ANNUAL_PRODUCT_ID\",\"$ANDROID_MONTHLY_PRODUCT_ID\",\"$ANDROID_ANNUAL_PRODUCT_ID\"]}"

# 10. Attach products → packages (products array with objects — different format!)
curl -s -X POST "$RC_API/projects/$PROJECT_ID/packages/$MONTHLY_PKG_ID/actions/attach_products" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"products\":[{\"product_id\":\"$IOS_MONTHLY_PRODUCT_ID\",\"eligibility_criteria\":\"all\"},{\"product_id\":\"$ANDROID_MONTHLY_PRODUCT_ID\",\"eligibility_criteria\":\"all\"}]}"

curl -s -X POST "$RC_API/projects/$PROJECT_ID/packages/$ANNUAL_PKG_ID/actions/attach_products" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"products\":[{\"product_id\":\"$IOS_ANNUAL_PRODUCT_ID\",\"eligibility_criteria\":\"all\"},{\"product_id\":\"$ANDROID_ANNUAL_PRODUCT_ID\",\"eligibility_criteria\":\"all\"}]}"
```

---

## 4. Flutter SDK wiring (`purchases_flutter`)

### pubspec.yaml
```yaml
dependencies:
  purchases_flutter: ^8.0.0
```

RC public SDK keys are passed as **dart-defines** at build time — they are intentionally
embeddable (not secrets). Never put the secret key (`sk_xxx`) in the app.

```bash
flutter run \
  --dart-define=REVENUECAT_IOS_KEY=appl_xxx \
  --dart-define=REVENUECAT_ANDROID_KEY=goog_xxx \
  --dart-define=API_BASE_URL=...
```

### BillingService (complete implementation)

```dart
import 'package:flutter/foundation.dart';
import 'package:purchases_flutter/purchases_flutter.dart';

const _kIosKey     = String.fromEnvironment('REVENUECAT_IOS_KEY');
const _kAndroidKey = String.fromEnvironment('REVENUECAT_ANDROID_KEY');
const _kEntitlementId = 'pro'; // must match RC entitlement lookup_key

class BillingService extends ChangeNotifier {
  static final BillingService instance = BillingService._();
  BillingService._();

  Offering? _offering;
  bool _purchasing = false;

  bool get isPurchaseAvailable => _offering != null;
  bool get isPurchasing => _purchasing;

  /// Store-fetched prices. Falls back to baseline strings until offering loads.
  BillingPrices get prices => _derivePrices(_offering);

  Future<void> init() async {
    final key = Platform.isIOS ? _kIosKey : _kAndroidKey;
    if (key.isEmpty) return; // billing disabled (dev build without defines)
    await Purchases.setLogLevel(LogLevel.error);
    await Purchases.configure(PurchasesConfiguration(key));
    Purchases.addCustomerInfoUpdateListener(_onCustomerInfo);
    await _fetchOffering();
  }

  /// Call on every auth state change so purchases are linked to the Firebase UID.
  Future<void> setUser(String? uid) async {
    if (uid != null) {
      await Purchases.logIn(uid);
      await _fetchOffering();
    } else {
      await Purchases.logOut();
    }
  }

  Future<void> purchase(bool annual) async {
    final pkg = annual ? _offering?.annual : _offering?.monthly;
    if (pkg == null) return;
    _setPurchasing(true);
    try {
      await Purchases.purchasePackage(pkg);
      // CustomerInfoUpdateListener fires and notifies; no explicit state set needed.
    } on PurchasesErrorCode catch (e) {
      if (e != PurchasesErrorCode.purchaseCancelledError) rethrow;
    } finally {
      _setPurchasing(false);
    }
  }

  Future<void> restorePurchases() async {
    _setPurchasing(true);
    try {
      await Purchases.restorePurchases();
    } finally {
      _setPurchasing(false);
    }
  }

  void _onCustomerInfo(CustomerInfo info) {
    final active = info.entitlements.active.containsKey(_kEntitlementId);
    // Notify your EntitlementService here to invalidate its cache.
    notifyListeners();
  }

  Future<void> _fetchOffering() async {
    final offerings = await Purchases.getOfferings();
    _offering = offerings.current;
    notifyListeners();
  }

  void _setPurchasing(bool v) {
    _purchasing = v;
    notifyListeners();
  }
}
```

Key rules:
- `BillingService` extends `ChangeNotifier` so the paywall rebuilds reactively.
- `$rc_monthly` / `$rc_annual` map to `Offering.monthly` / `Offering.annual` — these
  are RC reserved package identifiers, not configurable names.
- Never hardcode prices in the paywall — always read from `BillingService.prices`
  which derives them from `storeProduct.priceString`.
- `Purchases.purchasePackage` throws `PurchasesErrorCode.purchaseCancelledError` when
  the user dismisses the system sheet — treat that as a no-op, not an error.

### Paywall CTA (reactive)

```dart
ListenableBuilder(
  listenable: BillingService.instance,
  builder: (context, _) {
    final billing = BillingService.instance;
    return Column(children: [
      FilledButton(
        onPressed: billing.isPurchaseAvailable && !billing.isPurchasing
            ? () => billing.purchase(_annualSelected)
            : null,
        child: billing.isPurchasing
            ? const SizedBox(width: 20, height: 20,
                child: CircularProgressIndicator(strokeWidth: 2))
            : Text(billing.isPurchaseAvailable
                ? 'Subscribe now'
                : 'Coming soon'),
      ),
      if (billing.isPurchaseAvailable)
        TextButton(
          onPressed: billing.isPurchasing ? null : () => billing.restorePurchases(),
          child: const Text('Restore purchases'),
        ),
    ]);
  },
)
```

---

## 5. NestJS backend

### RevenueCatService

Verifies subscriber state directly from the RC REST API v1 (the billing source of truth).

```typescript
// src/billing/revenuecat.service.ts
@Injectable()
export class RevenueCatService {
  private readonly secretKey: string;
  static readonly ENTITLEMENT_ID = 'pro';

  constructor(private config: ConfigService) {
    this.secretKey = config.get('revenuecat.secretKey', { infer: true }) ?? '';
  }

  get isConfigured() { return this.secretKey.length > 0; }

  async getSubscriberState(userId: string): Promise<StoreSubscriptionState | null> {
    if (!this.isConfigured) return null;
    const res = await fetch(
      `https://api.revenuecat.com/v1/subscribers/${encodeURIComponent(userId)}`,
      { headers: { Authorization: `Bearer ${this.secretKey}` } },
    );
    if (!res.ok) return null;
    const body = await res.json();
    const ent = body.subscriber?.entitlements?.[RevenueCatService.ENTITLEMENT_ID];
    if (!ent || !ent.expires_date) return null;
    const expires = new Date(ent.expires_date);
    const now = new Date();
    if (expires <= now) return { state: 'expired', autoRenewing: false, expiresAt: expires };
    // is_sandbox, unsubscribe_detected_at, billing_issues_detected_at etc.
    const autoRenewing = !ent.unsubscribe_detected_at && !ent.billing_issues_detected_at;
    return { state: 'active', autoRenewing, expiresAt: expires };
  }

  parseWebhookEvent(event: any): { userId: string; state: StoreSubscriptionState } | null {
    const userId = event.app_user_id;
    if (!userId) return null;
    switch (event.type) {
      case 'INITIAL_PURCHASE':
      case 'RENEWAL':
      case 'UNCANCELLATION':
      case 'PRODUCT_CHANGE':
        return { userId, state: { state: 'active', autoRenewing: true } };
      case 'CANCELLATION':
        return { userId, state: { state: 'active', autoRenewing: false } };
      case 'EXPIRATION':
        return { userId, state: { state: 'expired', autoRenewing: false } };
      case 'BILLING_ISSUE':
        return { userId, state: { state: 'grace', autoRenewing: true } };
      default:
        return null; // SUBSCRIBER_ALIAS, TRANSFER, TEST — ignore
    }
  }
}
```

### EntitlementService — 3-path resolution

```typescript
async getEntitlement(userId: string): Promise<EntitlementDto> {
  const now = Date.now();

  // Fast path: local DB has active unexpired pro subscription
  const sub = await this.db.subscription.findUnique({ where: { userId } });
  if (sub?.tier === 'pro' && (!sub.expiresAt || sub.expiresAt.getTime() > now)) {
    return { tier: 'pro', state: sub.state, expiresAt: sub.expiresAt, ... };
  }

  // Slow path: check RC (authoritative; covers first purchase before webhook fires)
  const rcState = await this.revenuecat.getSubscriberState(userId);
  if (rcState && EntitlementService.tierFor(rcState.state) === 'pro') {
    this.apply(userId, rcState).catch(e => logger.error(e)); // async back-fill
    return { tier: 'pro', state: rcState.state, expiresAt: rcState.expiresAt, ... };
  }

  // No active sub
  return { tier: 'free', state: sub?.state ?? 'none', ... };
}
```

### Webhook endpoint

```typescript
// in billing.controller.ts
@Public()
@Post('revenuecat/webhook')
@HttpCode(200)
async revenuecatWebhook(
  @Body() body: any,
  @Headers('authorization') authorization?: string,
) {
  // RC sends the Authorization header verbatim as configured in the dashboard.
  // Backend stores the secret WITHOUT "Bearer " prefix; comparison prepends it.
  if (this.rcWebhookSecret &&
      authorization !== `Bearer ${this.rcWebhookSecret}`) {
    throw new UnauthorizedException('invalid_webhook_secret');
  }
  const event = body.event;
  if (!event) return {};
  const parsed = this.revenuecat.parseWebhookEvent(event);
  if (parsed) await this.entitlement.apply(parsed.userId, parsed.state);
  return {};
}
```

**Webhook auth gotcha:** RC sends the `Authorization` header exactly as you type it in
the dashboard. If you paste `Bearer abc123`, the header arrives as `Bearer Bearer abc123`
when your backend prepends "Bearer ". So: store only the raw secret in `REVENUECAT_WEBHOOK_SECRET`,
and configure the dashboard value as `Bearer <secret>`.

### Environment variables

```env
# .env
REVENUECAT_SECRET_KEY=sk_xxx     # secret key, never in the app
REVENUECAT_WEBHOOK_SECRET=abc123 # raw token (dashboard gets "Bearer abc123")
```

```typescript
// configuration.ts
revenuecat: {
  secretKey:     process.env.REVENUECAT_SECRET_KEY    ?? '',
  webhookSecret: process.env.REVENUECAT_WEBHOOK_SECRET ?? '',
},
```

---

## 6. Webhook setup (dashboard only — no API)

app.revenuecat.com → Project → **Integrations → Webhooks → Add endpoint**:
- URL: `https://<your-domain>/api/v1/billing/revenuecat/webhook`
- Authorization header: `Bearer <REVENUECAT_WEBHOOK_SECRET>` (the full "Bearer ..." value)

Events to handle: `INITIAL_PURCHASE`, `RENEWAL`, `CANCELLATION`, `UNCANCELLATION`,
`EXPIRATION`, `BILLING_ISSUE`, `PRODUCT_CHANGE`. The endpoint must return `200` within
a few seconds or RC will retry.

The webhook keeps the local `subscriptions` table warm, but the 3-path entitlement
check (§5) means a missed webhook is self-healing — the RC REST API call on the slow
path recovers it.

---

## 7. Sandbox testing checklist

1. **Create sandbox tester**: ASC → Users and Access → Sandbox Testers → `+` → use
   a `+sandbox` email alias (e.g. `you+sandbox@gmail.com`). Existing Apple IDs
   cannot be sandbox testers — creating a real new Apple ID just for sandbox is the
   other option.

2. **Build with RC keys**:
   ```bash
   flutter run \
     --dart-define=API_BASE_URL=https://<your-api>/api \
     --dart-define=REVENUECAT_IOS_KEY=appl_xxx \
     --dart-define=REVENUECAT_ANDROID_KEY=goog_xxx
   ```

3. **Verify offering loads**: open the paywall — prices should show real store values
   (`$9.99/mo`, `$69.99/yr`), not fallback strings. If they show fallbacks, the RC
   public key or the store product IDs are wrong.

4. **Complete a sandbox purchase**: sign in with the sandbox Apple ID on device →
   open paywall → Subscribe → system sheet appears → confirm with sandbox Apple ID →
   purchase completes. Check `GET /v1/entitlement` returns `tier: pro`.

5. **Verify webhook fired**: RC dashboard → Integrations → Webhooks → delivery history
   should show a green `INITIAL_PURCHASE` event. If the backend returned 401, check
   the Authorization header format.

6. **Restore purchases**: sign out on device, sign back in, open paywall → Restore →
   should restore to pro without a new charge.

---

## 8. Pre-production checklist

- [ ] RC iOS app: add **In-App Purchase key** (ASC → Integrations → In-App Purchase → `.p8`)
- [ ] RC Android app: add **Google Play service account** JSON
- [ ] ASC: expand territory availability beyond initial market
- [ ] ASC / Play Console: set regional pricing tiers (T2/T3/T4)
- [ ] Webhook secret set in both VPS `.env` and RC dashboard
- [ ] `GET /v1/entitlement` tested with a real production purchase
- [ ] `APPLE_ENVIRONMENT=production` set in backend env (if you proxy Apple receipts)
- [ ] Webhook delivery confirmed in RC dashboard logs for at least one production event

---

## 9. Common errors and fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `'app_store' is a required property` | Flat app body format | Use nested: `{"type":"app_store","app_store":{"bundle_id":"..."}}` |
| `Subscription parameters are only supported for simulated store products` | `subscription` field in product body | Omit the `subscription` field — RC infers from the store |
| `Play Store subscription product's store_identifier must follow format subscriptionId:basePlanId` | Android product ID without base plan | Use `yourProduct:base` not just `yourProduct` |
| 405 on package product attach | Wrong URL path | Use `/packages/{id}/actions/attach_products` not `/offerings/{offeringId}/packages/{id}/products` |
| 4xx on package attach with `product_ids` | Wrong body key | Packages use `{"products":[{"product_id":"...","eligibility_criteria":"all"}]}`, entitlements use `{"product_ids":["..."]}` |
| Webhook returns 401 | Double "Bearer" prefix | Store raw secret in env var; dashboard gets `Bearer <secret>` |
| Prices show fallback strings | Offering not loading | Check RC public key is correct and store products exist in the store (not just RC) |
| `purchaseCancelledError` thrown | User dismissed system purchase sheet | Catch and ignore this specific error code |
| `logOut` fails | No logged-in user | Guard: only call `Purchases.logOut()` when a user was previously logged in |
