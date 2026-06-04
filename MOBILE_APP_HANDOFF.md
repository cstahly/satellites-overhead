# Mobile App Handoff — June 4 2026

Kotlin Multiplatform (KMP) iOS + Android companion app for the SDR satellite
capture system. iOS is the primary target; Android app scaffolded but not yet
wired to UI screens.

---

## Build setup (Mac required for iOS)

Mac: `MacBook-Pro-3.local` — SSH access available.
Repo on Mac: `/Volumes/vela/src/satellites-overhead` (external drive mount)
Xcode project lives at: `mobile/iosApp/SatellitesApp.xcodeproj`

### After every `git pull` on Mac — required steps

```bash
# 1. Re-apply the bearer token (local only, never committed)
TOKEN="sdr_tok_893c1e6b86324d86_c0JG27sWfLNTAkr_IdPfUT6V5edKbwYnwnoxNDPglyA"
sed -i '' 's|let token = UserDefaults.standard.string(forKey: "bearer_token") ?? ""|let token = UserDefaults.standard.string(forKey: "bearer_token") ?? "'$TOKEN'"|g' \
  mobile/iosApp/SatellitesApp/ViewModels/AppState.swift

# 2. Rebuild XCFramework if shared/ KMP code changed
cd mobile
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export ANDROID_HOME=$HOME/Library/Android/sdk
./gradlew :shared:assembleSharedXCFramework

# 3. Regenerate Xcode project if new Swift files were added
cd iosApp && python3 gen_xcodeproj.py

# 4. Build iOS app
xcodebuild -project SatellitesApp.xcodeproj -target SatellitesApp \
  -sdk iphonesimulator26.5 -configuration Debug CODE_SIGNING_ALLOWED=NO
```

### Why the manual token patch?
The bearer token must NOT be committed to the public GitHub repo (it was
accidentally committed once, immediately revoked, and force-pushed out of
history). The live token is patched into AppState.swift locally after each
pull. The token default in AppState.swift in git reads `?? ""`.

### New Swift files
Add any new `.swift` file to the `SOURCES` dict in `mobile/iosApp/gen_xcodeproj.py`
then re-run `python3 gen_xcodeproj.py`. The script generates
`SatellitesApp.xcodeproj/project.pbxproj` from scratch.

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
        ├── ViewModels/
        │   └── AppState.swift      # @MainActor ObservableObject, all data
        └── Views/
            ├── StatusView.swift    # Tab 0 — scheduler state + next pass
            ├── PassesView.swift    # Tab 1 — upcoming passes list
            ├── PassDetailView.swift # Pass detail: sky plot + map
            ├── SkyPlotView.swift   # Canvas polar az/el chart
            ├── CapturesView.swift  # Tab 2 — capture history
            ├── RulesView.swift     # Tab 3 — recurring rules with enable toggle
            ├── EventsView.swift    # Tab 4 — scheduler event log
            └── SettingsView.swift  # Tab 5 — server URL, token, lat/lon/alt
```

---

## KMP ↔ Swift type mapping (critical — past source of many bugs)

| Kotlin type | Swift type | Access |
|-------------|------------|--------|
| `Int` (non-optional) | `Int32` | direct |
| `Long` (non-optional) | `Int64` | direct |
| `Double` (non-optional) | `Double` | direct |
| `Int?` | `KotlinInt?` | `.int32Value` |
| `Long?` | `KotlinLong?` | `.int64Value` |
| `Double?` | `KotlinDouble?` | `.doubleValue` |
| `List<T>` | `NSArray` | `as? [T] ?? []` |
| `suspend fun` | `async throws` | requires `@Throws(Exception::class)` |

Without `@Throws(Exception::class)` on Kotlin suspend functions, Swift sees
them as non-throwing and `catch` blocks are unreachable (compile warning /
silent swallow).

---

## API authentication

All `/api/v1/` endpoints require:
```
Authorization: Bearer <token>
```

Tokens managed with `manage_api_tokens.py` on the Linux server.
Current mobile token: `tok_893c1e6b86324d86` (name: mobile-bootstrap, scopes: *)
Raw token file on Linux: `~/sdr_mobile_bootstrap_token.json`

The Ktor client has `expectSuccess = true` — non-2xx responses throw
`ResponseException` before body deserialization. Without this, 401 errors
cause confusing serialization crashes.

---

## API endpoints used by the app

| Method | Path | Model | Notes |
|--------|------|-------|-------|
| GET | `/api/v1/status` | `SchedulerStatus` | Scheduler heartbeat |
| GET | `/api/v1/passes` | `List<Pass>` | `?norad=N&lat=&lon=&alt_m=&hours=&min_el=&track_step_s=30` |
| GET | `/api/v1/captures` | `List<Capture>` | `?norad=N&limit=50` |
| GET | `/api/v1/rules` | `List<Rule>` | All recurring capture rules |
| POST | `/api/v1/rules` | — | Update rule (enable/disable via enabled field) |
| POST | `/api/v1/scan-now` | — | Queue immediate capture |
| GET | `/api/v1/events` | `List<SdrEvent>` | Scheduler lifecycle events |

Pass track data: each `Pass` includes a `track: List<TrackPoint>` with
`az`, `el`, `sub_lat`, `sub_lon` at 30s intervals. `predict.py` was updated
to emit `sub_lat`/`sub_lon` (satellite ground position) via `ephem.sublat`/
`ephem.sublong`. The web service must be restarted after `predict.py` changes
to pick them up (`systemctl --user restart satellites-overhead.service`).

---

## Screen state (as of this session)

### Status (tab 0)
- Live/idle indicator (green dot) + state text
- `status.message` from server (e.g. "next capture pending")
- If idle and passes available: tappable countdown row showing time-to-AOS
  and sat name → taps to Passes tab. Ticks every second via `Timer.publish`.
- "Pending queue" count → taps to Captures tab
- "Scan now…" button → bottom sheet with rule picker (or manual NORAD entry)
- "Running" section shown only when `status.live == true`

### Passes (tab 1)
- Lists passes for all NORAD IDs found in active rules (not hardcoded)
- Rules load first in `refreshAll()`, then passes fetch uses rule norads
- Tapping a pass → `PassDetailView`

### PassDetailView
- **Sky plot**: `SkyPlotView` — dark polar Canvas, concentric rings at 0/30/60°,
  N/S/E/W labels, pass arc in green, AOS (green dot), LOS (orange dot), peak
  labeled in white. Uses `az`/`el` from track points.
- **Ground track map**: MapKit `Map` with `MapPolyline` of `sub_lat`/`sub_lon`
  points, AOS/LOS markers, observer antenna marker.
- Pass details grid + "Queue Capture" button.

### Captures (tab 2)
- Capture history list with size, frequency, gains.

### Rules (tab 3)
- List all rules with enable/disable toggle. Toggle calls `setRuleEnabled`.

### Events (tab 4)
- Scheduler event log (lifecycle events).

### Settings (tab 5)
- Server URL, bearer token, lat/lon/alt. "Save & Reconnect" rebuilds the API client.

---

## App icon

Generated by `/tmp/make_icon.py` (Python, pure stdlib) — dark navy background
with green concentric signal rings and antenna stem. 1024×1024 PNG stored at
`mobile/iosApp/SatellitesApp/Assets.xcassets/AppIcon.appiconset/AppIcon.png`.
This file IS committed (it's a binary asset, not a secret).

Run on Mac to regenerate:
```bash
ssh MacBook-Pro-3.local "python3 /tmp/make_icon.py"
```

---

## Xcode project settings

| Setting | Value |
|---------|-------|
| Deployment target | iOS 17.0 |
| Bundle ID | `com.sdr.satellites` |
| Team ID | `634QAM3ZHG` |
| Framework | `Shared.xcframework` (static, no embed phase) |
| Info.plist | Generated (`GENERATE_INFOPLIST_FILE = YES`) |
| Scheme/target | `SatellitesApp` (use `-target`, not `-scheme`, for xcodebuild) |

The XCFramework is built at:
`mobile/shared/build/XCFrameworks/release/Shared.xcframework`

---

## Known issues / incomplete items

1. **Android UI** — `androidApp` has the shell (`SatellitesApp.kt`, settings)
   but no Compose screens. All the API and model code is shared and works;
   only the UI screens need to be written.

2. **Passes only shows rule norads** — by design. If the user adds more rules,
   those sats automatically appear. If they want an arbitrary sat, add a rule.

3. **Scan-now hardcoded satellite list** — the scan sheet shows active rules as
   targets. Works well. If rules list is empty on first load, defaults to M2-4.

4. **Push notifications** — device registration endpoint exists at
   `/api/v1/devices` (POST). The app has no device registration UI or
   notification handling yet.

5. **Bearer token workflow** — token is patched locally post-pull. Could be
   improved with a gitignored `Secrets.swift` file that is generated from a
   template, so new devs get a clear error rather than an auth failure.

6. **`rebuildApi()` in AppState** — called from SettingsView after saving.
   Currently `api.close()` is called but `SatellitesApi.close()` just calls
   `client.close()` on the Ktor HttpClient. Works correctly.

7. **No auto-refresh / background polling** — the app only fetches on launch
   and pull-to-refresh. Could add a periodic timer in AppState (e.g. 30s
   status poll, 5m passes poll).

---

## Gradle notes

- Kotlin: 2.0.21, AGP: 8.7.3, Ktor: 2.3.12, kotlinx.serialization: 1.7.3
- AGP 8.7.3 is incompatible with Gradle 9.x — the wrapper uses Gradle 8.9
- The `gradle-wrapper.jar` was bootstrapped from another project on the Mac
- `kotlin.mpp.androidGradlePluginCompatibility.nowarn=true` suppresses compat warning

---

## Git hygiene

- Token commit was accidentally pushed to public GitHub, immediately revoked,
  and force-pushed out of history (commit `5c5206e` no longer exists remotely)
- `.tlecache/active.tle` is gitignored and shows as modified in `git status` —
  it is updated at runtime by CelesTrak fetches, do not commit it
- The Mac repo frequently has divergent branches due to the local token patch.
  Always use `git reset --hard origin/master` before pulling on Mac, then
  re-apply the token patch.
