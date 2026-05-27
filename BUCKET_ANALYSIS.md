# Multi-Platform Bucket Analysis

## Summary

After analyzing 200+ recent bugs (from 1,744 in the last 30 days) across the IndiaMART OpenProject instance, here's the complete picture of how QA teams raise bugs across different platforms/buckets.

---

## Top Bug Buckets (Last 30 Days)

| # | Project (Bucket) | Bug Count | Platform Type | What It Covers |
|---|---|---|---|---|
| 1 | **Android** | 36 | Mobile App | Native Android app + webviews inside app |
| 2 | **Product Approval & AI Audit** | 24 | Internal Tools | ML audit, photo/video accuracy, category QA |
| 3 | **WebERP - Core** | 23 | Desktop/Internal | Backend ERP system, CSD, Finance, HR tools |
| 4 | **MobileSite_M** | 15 | Mobile Web (m.indiamart.com) | Mobile browser site — PDP, Company, Home |
| 5 | **Catalog AI Auditor** | 12 | Internal Tools | AI audit product reviews |
| 6 | **IM-iOS Native** | 10 | Mobile App | Native iOS app + webviews inside app |
| 7 | **Online Payments** | 7 | Cross-platform | Payment flows |
| 8 | **APP Webview Lead Manager** | 6 | Webview (in App) | LMS/Lead Manager webview bugs |
| 9 | **FCP/MDC** | 6 | Desktop Web | Free Content Provider pages |
| 10 | **WhatsApp-9696** | 5 | Communication | WhatsApp integration |
| 11 | **Product Detail Page** | 5 | Desktop Web | Desktop PDP (dir.indiamart.com) |
| 12 | **Seller Dashboard/Products/Settings** | 5 | Desktop Web | Seller tools on desktop |
| 13 | **Desktop search UI** | 4 | Desktop Web | Search page on desktop |
| 14 | **Desktop Identification/Login** | 4 | Desktop Web | Login, OTP, verification on desktop |
| 15 | **Clients Templates** | 4 | Mobile Web | Client landing page templates |

---

## Platform Types Identified

### 1. **Mobile App (Native)**
- **Buckets:** `Android` (ID: 3), `IM-iOS Native` (ID: 85)
- **How to identify:** Device names (Samsung, iPhone, IQOO, Realme, etc.), mentions of "app", "native", APK/IPA, specific app screens
- **Test Environment fields:** Device model, OS version, App Version
- **Already supported** ✅

### 2. **App Webview (Inside Mobile App)**
- **Buckets:** `APP Webview Lead Manager` (ID: 476)
- **How to identify:** "LMS Webview", "webview", "LMS chat screen", features accessed via app but rendered as webview
- **Category:** Android or IOS (within the project)
- **Test Environment fields:** Device model, OS version

### 3. **Mobile Site (m.indiamart.com)**
- **Bucket:** `MobileSite_M` (ID: 71)
- **How to identify:** "m.indiamart.com", "msite", mobile browser, "Mobile" device + browser mention
- **Categories:** Product Detail, Company Pages, Home Page, Foreign, etc.
- **Test Environment fields:** Device: Mobile, Browser/Version, OS

### 4. **Desktop Website (dir.indiamart.com / www.indiamart.com)**
- **Buckets:** 
  - `Desktop search UI` (ID: 47) — Search page bugs
  - `Product Detail Page` (ID: 55) — Desktop PDP
  - `Desktop Identification,Login and Verification` (ID: 62) — Login/OTP on desktop
  - `Indiamart homepage` (ID: 50) — Homepage bugs
  - `Centralized Header & Footer` (ID: 44) — Header/footer across pages
  - `FCP/MDC` (ID: 54) — Free Content Provider pages
  - `DIR` (ID: 58) — Directory pages
  - `Seller - Dashboard, Products, Profile, Buyer Tools, Settings` (ID: 84) — Seller desktop tools
  - `Seller Latest Buy Leads` (ID: 83) — Seller BL pages
  - `Clients Templates` (ID: 53) — Client page templates
  - `Buyer MY.IM` (ID: 64) — Buyer dashboard pages
  - `Buyer My-Messages` (ID: 393) — Buyer message center
- **How to identify:** "Desktop", "dir.indiamart.com", "www.indiamart.com", browser + resolution mentions, no device model
- **Test Environment fields:** Device: Desktop, Browser/Version, OS (Windows/Mac), Resolution

### 5. **Internal Tools / Backend**
- **Buckets:**
  - `WebERP - Core` (ID: 77) — Internal ERP system
  - `Product Approval & AI Audit` (ID: 470) — ML/AI audit
  - `Catalog AI Auditor` (ID: 477) — Product catalog AI
  - `MERP` (ID: 76) — Mobile ERP
  - `Leap CRM` (ID: 73) — CRM system
  - `Online Payments` (ID: 61) — Payment infrastructure
- **How to identify:** Internal tools, admin panels, API errors, data validation, ML accuracy reports

### 6. **Communication/Messaging**
- **Buckets:**
  - `WhatsApp-9696` (ID: 431) — WhatsApp integration
  - `Desktop Lead Manager` (ID: 70) — Desktop LMS
- **How to identify:** "WhatsApp", "9696", "XMPP", messaging-related

---

## Bug Description Patterns by Platform

### Mobile App (Android/iOS) — Current Format
```
### Actual Behavior
[What's wrong]

### Expected Behavior
[What should happen]

### Steps to reproduce:
1. Login as [user_id]
2. Navigate to [screen]
3. [Action]
4. Observe [issue]

### Test Environment:
1. Device: Samsung S23 / iPhone 13
2. Environment: STAGE
3. Operating System: Android 15 / iOS 26.3
4. App Version: 13.4.2 (if known)
```

### Mobile Site (m.indiamart.com) — Different Format
```
### Actual Behavior
[What's wrong]
URL: [m.indiamart.com/...]

### Expected Behavior
[What should happen]

### Steps to reproduce:
1. Go to m.indiamart.com
2. Navigate to [page]
3. [Action]
4. Observe [issue]

### Test Environment:
1. Device: Mobile
2. Environment: Production
3. Operating System: Android 13
4. Browser/Version: Google Chrome 148

### Bug Source
[User Journey Testing / Regression / etc.]
```

### Desktop Website — Different Format
```
### Actual Behavior
[What's wrong]
URL: [dir.indiamart.com/... or www.indiamart.com/...]

### Expected Behavior
[What should happen]

### Steps to reproduce:
1. Go to [www.indiamart.com / dir.indiamart.com]
2. [Navigate/click]
3. Observe [issue]

### Test Environment:
1. Device: Desktop
2. Environment: Stage/Production
3. Operating System: Windows 10 Pro
4. Browser/Version: Google Chrome 130
5. Resolution: 1920x1080, Scale: 150% (optional)
```

### Internal Tools (WebERP/MERP) — Less Structured
```
[Issue description]
[Screenshots/data]
GLID: [number]
[Error details]
```

---

## Key Differences Between Platforms

| Aspect | Mobile App | App Webview | Mobile Site | Desktop Web | Internal Tools |
|---|---|---|---|---|---|
| Device field | Phone model | Phone model | "Mobile" | "Desktop" | "Desktop" or N/A |
| OS field | Android/iOS version | Android/iOS | Android/iOS | Windows/Mac | Windows |
| URL | N/A | N/A | m.indiamart.com | dir/www.indiamart.com | Internal URLs |
| Browser | N/A | N/A | Chrome, Safari | Chrome, Firefox, Edge | Chrome |
| App Version | Yes | Sometimes | N/A | N/A | N/A |
| Steps style | "Login as [id]" | "Login as [id]" | "Go to m.indiamart.com" | "Go to [url]" | Varies |
| Category field | Feature-specific (56 options) | Android/IOS | Page-type | Page/Feature | Module |

---

## Routing Decision Logic (Proposed)

```
IF tester mentions device (Samsung, iPhone, IQOO, etc.) AND no URL:
    → It's a MOBILE APP bug
    IF LMS/Lead Manager/webview context:
        → Project: app-webview-lead-manager (476)
        → Category: Android or IOS
    ELSE:
        → Project: android (3) or iosnative (85)
        → Category: Based on feature mentioned

ELSE IF URL contains "m.indiamart.com" OR "msite" mentioned:
    → Project: MobileSite_M (71)
    → Category: Based on page (PDP, Company, Home, Foreign)

ELSE IF URL contains "dir.indiamart.com" OR "www.indiamart.com" OR "Desktop" mentioned:
    → Route based on feature:
    IF search page / search UI:
        → Project: Desktop search UI (47)
    ELSE IF PDP / product detail:
        → Project: Product Detail Page (55)
    ELSE IF login / OTP / verification:
        → Project: Desktop Identification,Login and Verification (62)
    ELSE IF homepage / dashboard:
        → Project: Indiamart homepage (50)
    ELSE IF header / footer:
        → Project: Centralized Header & Footer (44)
    ELSE IF seller dashboard / products / settings:
        → Project: Seller - Dashboard, Products, Profile... (84)
    ELSE IF FCP / MDC / company page:
        → Project: FCP/MDC (54)
    ELSE:
        → Default desktop bucket

ELSE IF internal tool / ERP / admin:
    → Project: WebERP - Core (77) or specific tool project

ELSE IF WhatsApp / 9696 mentioned:
    → Project: WhatsApp-9696 (431)
```

---

## Implementation Approach

### Option: Tester provides bucket tag in message

Format: `[LMS Webview]`, `[Msite]`, `[Desktop Search]`, `[Android]`, `[iOS]`

The LLM will:
1. Look for an explicit tag first
2. If no tag, infer from context (URL, device, keywords)
3. Map to the correct OpenProject project + category

### Required Changes:
1. **`config.py`** — Add all project mappings (IDs, slugs, categories)
2. **`models.py`** — Expand `PlatformType` enum OR add a new `ProjectBucket` field
3. **`gemini_client.py`** — Update system prompt with multi-bucket routing rules
4. **`openproject_client.py`** — Route to correct project based on bucket
5. **`main.py`** — No changes needed (pipeline stays the same)

---

## Next Steps

1. Confirm which buckets your QA team wants to support initially
2. Define the tag format or keywords for each bucket
3. Update the LLM system prompt with routing examples
4. Test locally before deploying
5. Deploy → if issues → rollback to `qa-bugbot-00026-btk`
