# Mobile App Handoff — June 4 2026 (Session 2)

Kotlin Multiplatform (KMP) iOS + Android companion app for the SDR satellite
capture system. iOS is the primary target; Android app scaffolded but has no
UI screens yet.

---

## Build setup (Mac required for iOS)

Mac: `MacBook-Pro-3.local` — SSH access available.
Repo on Mac: `/Volumes/vela/src/satellites-overhead` (external drive, `/Volumes/vela/`)
Xcode project: `mobile/iosApp/SatellitesApp.xcodeproj`

### After every `git pull` on Mac — REQUIRED

```bash
cd /Volumes/vela/src/satellites-overhead

# 1. Reset and pull (Mac repo drifts from local token patch)
git reset --hard origin/master && git pull --ff-only

# 2. Patch the bearer token (NEVER committed — see Token section below)
TOKEN="sdr_tok_893c1e6b86324d86_c0JG27sWfLNTAkr_IdPfUT6V5edKbwYnwnoxNDPglyA"
sed -i '' 's|let token = UserDefaults.standard.string(forKey: "bearer_token") ?? ""|let token = UserDefaults.standard.string(forKey: "bearer_token") ?? "'$TOKEN'"|g' \
  mobile/iosApp/SatellitesApp/ViewModels/AppState.swift

# 3. Rebuild XCFramework — ONLY if shared/ Kotlin code changed
cd mobile
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export ANDROID_HOME=$HOME/Library/Android/sdk
./gradlew :shared:assembleSharedXCFramework

# 4. Regenerate Xcode project — ONLY if new Swift files added to SOURCES dict
cd iosApp && python3 gen_xcodeproj.py

# 5. Build iOS app
xcodebuild -project SatellitesApp.xcodeproj -target SatellitesApp \
  -sdk iphonesimulator26.5 -configuration Debug CODE_SIGNING_ALLOWED=NO
```

### Adding new Swift files
Add to the `SOURCES` dict in `mobile/iosApp/gen_xcodeproj.py`, then re-run
`python3 gen_xcodeproj.py`. The script fully regenerates `project.pbxproj`.

---

## Bearer token

**NEVER commit.** Token `tok_893c1e6b86324d86` was created after the previous
token (`tok_7c9873925e18470c`) was accidentally committed and immediately
revoked. The raw token value is patched locally via sed after every pull.

- Token ID: `tok_893c1e6b86324d86`
- Raw token: `sdr_tok_893c1e6b86324d86_c0JG27sWfLNTAkr_IdPfUT6V5edKbwYnwnoxNDPglyA`
- Managed with `manage_api_tokens.py` on Linux
- Saved at: `~/sdr_mobile_bootstrap_token.json` on Linux

The token defaults in `AppState.swift` in git read `?? ""`. The sed patch
replaces both occurrences (in `init()` and `rebuildApi()`).

---

## Architecture

```
mobile/
├── shared/                         # KMP shared module (Kotlin)
│   └── src/commonMain/kotlin/com/sdr/satellites/
│       ├── api/SatellitesApi.kt    # Ktor HTTP client, all API calls
│       ├── model/Models.kt         # @Serializable data classes
│       └── store/Settings.kt       # expect/actual persistent settings
├── androidApp/                     # Android shell (Jetpack Compose TODO)
└── iosApp/
    ├── gen_xcodeproj.py            # Generates project.pbxproj
    └── SatellitesApp/
        ├── SatellitesApp.swift     # @main entry point
        ├── ContentView.swift       # TabView (6 tabs)
        ├── Extensions.swift        # String.shortTime helper
        ├── Assets.xcassets/
        │   └── AppIcon.appiconset/
        │       ├── AppIcon.png     # committed — dark navy + green signal rings
        │       └── Contents.json   # written by gen_xcodeproj.py (includes filename)
        ├── ViewModels/
        │   └── AppState.swift      # @MainActor ObservableObject — all app data
        └── Views/
            ├── StatusView.swift    # Tab 0 — sky plot + state + capture info
            ├── PassesView.swift    # Tab 1 — upcoming passes list
            ├── PassDetailView.swift # Pass detail: sky plot arc + MapKit ground track
            ├── SkyPlotView.swift   # Canvas polar az/el chart (used in PassDetailView)
            ├── CapturesView.swift  # Tab 2 — capture history log
            ├── RulesView.swift     # Tab 3 — recurring rules with enable toggle
            ├── EventsView.swift    # Tab 4 — scheduler event log
            └── SettingsView.swift  # Tab 5 — server URL, token, lat/lon/alt
```

---

## KMP ↔ Swift type mapping (source of many past bugs)

| Kotlin type | Swift type | Access |
|-------------|------------|--------|
| `Int` | `Int32` | direct |
| `Long` | `Int64` | direct |
| `Double` | `Double` | direct |
| `Int?` | `KotlinInt?` | `.int32Value` |
| `Long?` | `KotlinLong?` | `.int64Value` |
| `Double?` | `KotlinDouble?` | `.doubleValue` |
| `List<T>` | `NSArray` | `as? [T] ?? []` |
| `suspend fun` | `async throws` | requires `@Throws(Exception::class)` |

Without `@Throws(Exception::class)` on Kotlin suspend functions, catch blocks
in Swift are unreachable (compiler warning, errors silently swallowed).

Kotlin `Int` in a model class → Swift `Int32` (NOT `Int`). Saw this in
`OverheadSat.id` where `public var id: Int32 { norad }` is required.

---

## API endpoints used by the app

| Method | Path | Model | Notes |
|--------|------|-------|-------|
| GET | `/api/v1/status` | `SchedulerStatus` | Scheduler heartbeat |
| GET | `/api/v1/passes` | `List<Pass>` | `?norad=N&lat=&lon=&alt_m=&hours=&min_el=&track_step_s=30` |
| GET | `/api/v1/captures` | `List<Capture>` | `?norad=N&limit=50` |
| GET | `/api/v1/rules` | `List<Rule>` | All recurring capture rules |
| POST | `/api/v1/rules` | — | Update rule (enable/disable) |
| POST | `/api/v1/scan-now` | — | Queue immediate capture |
| GET | `/api/v1/events` | `List<SdrEvent>` | Scheduler lifecycle events |
| GET | `/api/v1/overhead` | `List<OverheadSat>` | Live overhead sats (NEW this session) |

### /api/v1/overhead
Added to `predict.py` as `overhead_now()` and wired into `serve.py`.
Returns all satellites currently above `min_el` (default 0°) with az, el,
range_km. Computed from the full active TLE set via PyEphem. Returns ~600-700
sats over Lafayette IN typically. **Restart `satellites-overhead.service` after
changes to `predict.py`.**

### Pass track data
Each `Pass` has `track: List<TrackPoint>` with `az`, `el`, `sub_lat`,
`sub_lon` at 30s intervals (`track_step_s=30`). `predict.py` was updated to
emit `sub_lat`/`sub_lon` from `sat.sublat`/`sat.sublong`.

### Passes: do NOT fetch without norad filter
Calling `/api/v1/passes` without `?norad=N` triggers pass prediction for ALL
active TLEs (thousands), which times out → 502. Always pass rule norads.
Current approach: load rules first in `refreshAll()`, then fetch passes for
each rule's norad separately.

---

## Screen status

### Status (tab 0)
- **Sky plot** — `OverheadSkyPlot` Canvas in top section. Dark bg, concentric
  rings, N/E/S/W labels, blue dots (brightness ∝ elevation). Refreshes every
  30s via `Timer.publish`. Tap a dot → bottom sheet with sat name, el, az,
  range, NORAD ID. Selected satellite turns green.
- **Scheduler state** — live/idle dot + state text
- **When live** (`status.live == true`): shows job label, frequency+gains,
  live countdown `Xm Ys remaining` (ticks every 1s via `ticker`), "View
  captures ›" → Captures tab
- **When idle**: shows `status.message`, next pass countdown → Passes tab
- **"Scan now…"** → sheet with rule picker or manual NORAD entry

### Passes (tab 1)
- Fetches per rule-norad (rules load first in `refreshAll()`)
- Row layout: elevation pill (left, colored green/yellow/gray), sat name +
  AOS + az track (middle), tracking antenna icon (right, green=enabled rule)
- Tap row content → `PassDetailView`; tap antenna icon → toggles rule enabled

### PassDetailView
- `SkyPlotView` — polar canvas showing the pass arc (az/el from track points),
  AOS (green dot), LOS (orange dot), peak labeled
- MapKit `Map` with `MapPolyline` of `sub_lat`/`sub_lon` ground track, AOS/LOS
  markers, observer antenna marker
- Pass detail grid + "Queue Capture" button

### Captures (tab 2)
- Capture history list (log only, no summaries yet)

### Rules (tab 3)
- List all rules with enable/disable toggle
- No "add rule" UI yet (too complex for now per user)

### Events (tab 4)
- Scheduler event log

### Settings (tab 5)
- Server URL, bearer token, lat/lon/alt. Save & Reconnect rebuilds API client.

---

## Server-side changes in this session

### predict.py
- `look_at()` now emits `sub_lat` and `sub_lon` (sat ground position)
- New `overhead_now()` function: computes current positions of all active TLEs

### serve.py
- Imports `overhead_now` from predict
- New `/api/v1/overhead` endpoint: `?lat=&lon=&alt_m=&min_el=&group=`
- **Restart required** after predict.py changes:
  `systemctl --user restart satellites-overhead.service`

---

## App icon

1024×1024 PNG committed at
`mobile/iosApp/SatellitesApp/Assets.xcassets/AppIcon.appiconset/AppIcon.png`.
Dark navy background, green concentric signal rings, antenna stem.
Generated with pure Python (no PIL). `gen_xcodeproj.py` writes `Contents.json`
with `"filename":"AppIcon.png"` each time it runs.

**If icon still appears blank on simulator**: delete the app from the simulator
and reinstall fresh. The simulator caches the blank icon from before the PNG
was added to the repo.
```bash
xcrun simctl uninstall booted com.sdr.satellites
# then build and run again
```

---

## Xcode project settings

| Setting | Value |
|---------|-------|
| Deployment target | iOS 17.0 |
| Bundle ID | `com.sdr.satellites` |
| Team ID | `634QAM3ZHG` |
| Framework | `Shared.xcframework` (static, no embed) |
| Info.plist | Generated (`GENERATE_INFOPLIST_FILE = YES`) |
| Build cmd | `xcodebuild -target SatellitesApp` (NOT `-scheme`) |

XCFramework built at:
`mobile/shared/build/XCFrameworks/release/Shared.xcframework`

---

## Gradle notes

- Kotlin 2.0.21, AGP 8.7.3, Ktor 2.3.12, kotlinx.serialization 1.7.3
- AGP 8.7.3 incompatible with Gradle 9.x → wrapper uses Gradle 8.9
- `kotlin.mpp.androidGradlePluginCompatibility.nowarn=true` in gradle.properties
- `gradle-wrapper.jar` was bootstrapped from another project on Mac

---

## Known issues / TODO

1. **Android UI** — no Compose screens. All API/model code is shared and works.
2. **All-satellites passes** — disabled (timeouts). Passes only show rule norads.
   To see more satellites, add rules for them. A "watchlist" concept (add norad
   without full rule) would be a good future feature.
3. **Push notifications** — `/api/v1/devices` POST endpoint exists. No device
   registration UI in the app.
4. **Token workflow** — manual sed patch after every pull. Could be improved
   with a gitignored `Secrets.swift` file.
5. **Auto-refresh** — overhead refreshes every 30s, status/passes only on
   launch and pull-to-refresh. Could add periodic status polling.
6. **Rules "+" button** — user wants it eventually, deferred as too complex.
7. **Captures summaries** — currently just a log list; user said that's fine
   for now, add summaries later.

---

## Recent commit history

```
af18f57 Fix OverheadSat.id type to Int32
f56cb40 Fix 502, tappable sky plot, running capture countdown + clickthrough
7b64c21 Add missing OverheadSat import
f129501 Live sky plot, all-sat passes, elevation pill, tracking fix, overhead API
dfb27a9 Fix Identifiable conformance and AppIcon Contents.json filename
a93e7e4 Add overhead sats, fix queue color, tracking toggle, commit app icon PNG
1737794 All-rule passes, inline next-pass countdown, team ID 634QAM3ZHG
2191dd1 Make TrackPoint sub_lat/sub_lon optional with defaults
9084d47 Add sky plot + ground track map; next-capture countdown; scan-now picker
7e5bc64 Fix idle current job, queue tap, icons, add Rules + scan-now
df8da76 Add expectSuccess=true to throw on HTTP 4xx/5xx before body deserialization
0ef72b5 Scaffold KMP mobile app (Android + iOS)
```
