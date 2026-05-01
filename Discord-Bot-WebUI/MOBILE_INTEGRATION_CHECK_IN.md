# Mobile Integration: Membership QR + Match Check-In

This is the contract handoff for the Flutter app's match check-in feature.
The original spec the Flutter team wrote is implemented as described, with
**one intentional deviation** flagged below.

## Deviation from the original spec

The spec used flat `/api/v1/matches/{match_id}/attendance`. The webui has
**two physical match tables** — `matches` (Pub League) and `ecs_fc_matches`
(ECS FC) — with overlapping integer IDs, so a flat URL is ambiguous.

**The implemented endpoints carry `league_type` as a path segment:**

```
POST /api/v1/matches/{league_type}/{match_id}/attendance
GET  /api/v1/matches/{league_type}/{match_id}/attendance
```

Where `{league_type}` is `pub_league` or `ecs_fc`. The Flutter app needs
to thread this value through based on which match the user is scanning.

If your `Match` model already distinguishes the two flavors (e.g. via
`match.leagueKind` or similar), this should be a one-line change in your
HTTP client wrapper.

---

## Endpoint summary

All require `Authorization: Bearer <jwt>` and `X-API-Key: ecs-soccer-mobile-key`.
Business-rule rejections return **200 with a `status` field** — HTTP code
is secondary, exactly as the spec recommended.

| Method | Path | Status |
|---|---|---|
| `GET` | `/api/v1/membership/pass/lookup?token=<member_token>` | live |
| `POST` | `/api/v1/check-in/<venue_token>` | live |
| `POST` | `/api/v1/matches/<league_type>/<id>/attendance` | live (path deviation) |
| `GET` | `/api/v1/matches/<league_type>/<id>/attendance` | live (path deviation) |
| `POST` | `/api/v1/events/<id>/check_in` | **501** — Phase 4 deferred |

`GET /api/v1/app_config` now exposes `feature_toggles.admin_points_events_enabled`.
Default is `false`; flips when the admin toggles it. Use this to gate the
More→Admin "Points Events" entry.

---

## Member tokens

The QR encoded in a player's pass is now `WalletPass.barcode_data`
(format: `ECSFC-{TYPE}-{SHORT_SERIAL}`, e.g. `ECSFC-PUB-ABC123DEF456`).

Previously the mobile API generated a synthetic value that **rotated on
every fetch** — that was a bug; same player, two fetches, two different
QRs. Fixed: `GET /api/v1/membership/pass` now returns the stable
`barcode_data` value when a `WalletPass` row exists for the user.

**Edge case for legacy users**: if a player has no `WalletPass` row yet,
the API returns a deterministic synthetic (`ECS2025{hash}`) so the QR
doesn't rotate, but **`/membership/pass/lookup` will 404 for those tokens**
(they aren't persisted). The webui has an admin "Backfill member passes"
button on `/admin-panel/match-operations/check-in` that creates rows for
active Pub League players. Once that's run, lookups work for everyone.

---

## Universal links

The webui serves `/.well-known/apple-app-site-association` with the new
paths added:

```
/m/*           — member identity card (player QR camera-app scan)
/check-in/*    — venue check-in (printed QR / NFC sticker at the pitch)
```

The Flutter app needs:
1. **iOS**: `applinks:portal.ecsfc.com` in Associated Domains entitlement
   (probably already there for the existing paths).
2. **Android**: catch-all is already declared via
   `delegate_permission/common.handle_all_urls` — no change needed.
3. **Routes**: handle `/m/<token>` (member identity) and
   `/check-in/<token>` (venue check-in) in the deep-link router.

If the env vars `IOS_TEAM_ID`, `IOS_BUNDLE_ID`, `ANDROID_PACKAGE_NAME`,
and `ANDROID_SHA256_FINGERPRINTS` aren't set on the webui server, the
AASA file serves placeholder values and link verification fails. Confirm
with the webui ops folks before testing.

---

## Status taxonomy

`POST /api/v1/check-in/<venue_token>` and
`POST /api/v1/matches/<lt>/<id>/attendance` return a `status` field:

| Value | When |
|---|---|
| `success` | First successful check-in for this player+match |
| `already_checked_in` | Player was already in `match_attendance` |
| `outside_window` | More than ±2h from kickoff |
| `not_rsvp_yes` | Player isn't on the YES list (self / coach scan) |
| `unknown_member` | Scanned `player_token` didn't resolve |
| `unauthorized` | Caller isn't a coach for this match nor admin (coach scan) |

`coach_manual` source on the coach scan endpoint **bypasses the RSVP
requirement** — that's the long-press-from-Not-Yet-list flow when a
player forgot their phone.

`coach_manual` also accepts a stringified integer player_id in the
`player_token` body field, since the Flutter app sends `Player.id` rather
than scanning a QR in that case. The backend tries `member_token` resolution
first, falls back to integer parse.

---

## Phase 4 stub

`POST /api/v1/events/<id>/check_in` returns:

```json
HTTP 501
{
  "status": "not_implemented",
  "message": "Points events backend not yet built. Track via the admin_points_events_enabled feature toggle."
}
```

The Flutter app should treat 501 / `status: not_implemented` as a soft
"Coming Soon" rather than a hard error. The corresponding admin toggle
(`admin_points_events_enabled`) can be flipped to expose UI without
backend changes once Phase 4 ships.

---

## Wallet pass relevance

The `.pkpass` now includes:

- `relevantDate`: ISO 8601 with offset, set to the player's next upcoming
  match within 14 days (e.g. `2026-05-04T14:00:00-08:00`).
- An additional entry in `locations[]` for the next match's venue,
  alongside the existing partner-bar list.

This is **bake-in only** for v1 — passes go stale after the next match
ends. PassKit web service push (re-issuing passes when the next match
changes) is a follow-up.

No Flutter change required — the wallet behavior is OS-level. Just verify
on a test device that the pass surfaces near the venue around match time.

---

## Test the deviation

A two-line smoke test for the path-segment change:

```dart
// pub_league
final r1 = await api.post('/api/v1/matches/pub_league/302/attendance',
    body: {'player_token': memberToken, 'source': 'coach'});

// ecs_fc — same shape, different path segment
final r2 = await api.post('/api/v1/matches/ecs_fc/15/attendance',
    body: {'player_token': memberToken, 'source': 'coach'});
```

If both round-trip successfully, the deviation is handled.

---

## Out-of-scope (not built yet)

- Points events backend (Phase 4)
- PassKit web service push for next-match relevance
- Player-perspective "my upcoming check-in window" calendar entry
