# ECS Soccer Mobile API - Missing Endpoints Addendum

These 47 endpoints were missing from `MOBILE_API_DOCUMENTATION.md`. All are part of the `/api/v1` mobile API unless noted otherwise.

---

## Table of Contents

1. [Admin - League Management](#1-admin---league-management)
2. [Admin - Player Notes](#2-admin---player-notes)
3. [Admin - Player Profile Management](#3-admin---player-profile-management)
4. [Draft - Full Draft System](#4-draft---full-draft-system)
5. [Store - Orders & Eligibility](#5-store---orders--eligibility)
6. [ECS FC - Availability & RSVP](#6-ecs-fc---availability--rsvp)
7. [ECS FC - Match Reporting & Events](#7-ecs-fc---match-reporting--events)
8. [ECS FC - Coach RSVP](#8-ecs-fc---coach-rsvp)
9. [ECS FC - Substitute System](#9-ecs-fc---substitute-system)
10. [Predictions URL Correction](#10-predictions-url-correction)

---

## 1. Admin - League Management

### `POST /admin/players/<player_id>/leagues`

Add a player to a league.

**Auth:** JWT required + Role: `Pub League Admin` or `Global Admin`

**Path Parameters:** `player_id` (int)

**Request Body:**

```json
{
  "league_id": 5
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Added to Premier League",
  "player_id": 789,
  "player_name": "John Smith",
  "league_id": 5,
  "league_name": "Premier League",
  "auto_assigned_role": "Pub League Player"
}
```

**Errors:** `400` missing league_id, `404` player/league not found, `409` already in league

---

### `DELETE /admin/players/<player_id>/leagues/<league_id>`

Remove a player from a league.

**Auth:** JWT required + Role: `Pub League Admin` or `Global Admin`

**Path Parameters:** `player_id` (int), `league_id` (int)

**Response (200):**

```json
{
  "success": true,
  "message": "Removed from Premier League",
  "player_id": 789,
  "player_name": "John Smith",
  "league_id": 5,
  "league_name": "Premier League",
  "removed_role": "Pub League Player"
}
```

**Errors:** `404` player/league not found or player not in league

---

### `GET /admin/leagues`

Get all available leagues (for assigning players to).

**Auth:** JWT required + Role: `Pub League Admin` or `Global Admin`

**Response (200):**

```json
{
  "leagues": [
    {
      "id": 5,
      "name": "Premier League",
      "season_id": 5
    }
  ]
}
```

---

## 2. Admin - Player Notes

**Role requirement for all notes endpoints:** `Pub League Admin`, `Global Admin`, or `Pub League Coach`

### `GET /admin/players/<player_id>/notes`

Get admin notes for a player.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `player_id` (int)

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max notes (1-100) |
| `offset` | int | 0 | Pagination offset |

**Response (200):**

```json
{
  "player_id": 789,
  "player_name": "John Smith",
  "notes": [
    {
      "id": 1,
      "content": "Great attitude at tryouts",
      "author_id": 123,
      "author_name": "Coach Jane",
      "created_at": "2026-03-20T10:00:00Z",
      "updated_at": null
    }
  ],
  "total": 5,
  "limit": 50,
  "offset": 0
}
```

---

### `POST /admin/players/<player_id>/notes`

Create an admin note for a player.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `player_id` (int)

**Request Body:**

```json
{
  "content": "Showed strong leadership during practice"
}
```

**Response (201):**

```json
{
  "success": true,
  "message": "Note created successfully",
  "note": {
    "id": 10,
    "player_id": 789,
    "content": "Showed strong leadership during practice",
    "author_id": 123,
    "author_name": "Coach Jane",
    "created_at": "2026-03-27T10:00:00Z"
  }
}
```

**Errors:** `400` missing/empty content, `404` player not found

---

### `PUT /admin/players/<player_id>/notes/<note_id>`

Update an admin note. Only the author can edit (unless Global Admin).

**Auth:** JWT required + Role (see above)

**Path Parameters:** `player_id` (int), `note_id` (int)

**Request Body:**

```json
{
  "content": "Updated note content"
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Note updated successfully",
  "note": {
    "id": 10,
    "player_id": 789,
    "content": "Updated note content",
    "author_id": 123,
    "author_name": "Coach Jane",
    "created_at": "2026-03-27T10:00:00Z",
    "updated_at": "2026-03-27T14:00:00Z"
  }
}
```

**Errors:** `400` missing/empty content, `403` not the author, `404` note not found

---

### `DELETE /admin/players/<player_id>/notes/<note_id>`

Delete an admin note. Only the author can delete (unless Global Admin).

**Auth:** JWT required + Role (see above)

**Path Parameters:** `player_id` (int), `note_id` (int)

**Response (200):**

```json
{
  "success": true,
  "message": "Note deleted successfully",
  "note_id": 10,
  "player_id": 789
}
```

**Errors:** `403` not the author, `404` note not found

---

## 3. Admin - Player Profile Management

**Role requirement:** `Pub League Admin`, `Global Admin`, or `Pub League Coach`

### `GET /admin/players/<player_id>/profile`

Get full player profile (admin view with extra fields).

**Auth:** JWT required + Role (see above)

**Path Parameters:** `player_id` (int)

**Response (200):**

```json
{
  "player_id": 789,
  "player_name": "John Smith",
  "phone": "2065551234",
  "jersey_size": "L",
  "jersey_number": 10,
  "pronouns": "he/him",
  "favorite_position": "Midfielder",
  "other_positions": "Defender",
  "positions_not_to_play": "Goalkeeper",
  "frequency_play_goal": "never",
  "expected_weeks_available": "10",
  "unavailable_dates": "April 5-12",
  "willing_to_referee": true,
  "additional_info": "Recovering from knee injury",
  "player_notes": "Internal notes here",
  "is_coach": false,
  "is_ref": false,
  "is_current_player": true,
  "profile_picture_url": "https://...",
  "user_account": {
    "id": 123,
    "username": "jsmith",
    "email": "john@example.com"
  },
  "recent_notes": [
    {
      "id": 1,
      "content": "Great attitude",
      "author_name": "Coach Jane",
      "created_at": "2026-03-20T10:00:00Z"
    }
  ]
}
```

**Errors:** `404` player not found

---

### `PUT /admin/players/<player_id>/profile`

Update a player's profile (admin edit).

**Auth:** JWT required + Role (see above)

**Path Parameters:** `player_id` (int)

**Request Body (all fields optional):**

```json
{
  "name": "John Smith",
  "phone": "2065551234",
  "jersey_size": "L",
  "jersey_number": 10,
  "pronouns": "he/him",
  "favorite_position": "Midfielder",
  "other_positions": "Defender",
  "positions_not_to_play": "Goalkeeper",
  "frequency_play_goal": "never",
  "expected_weeks_available": "10",
  "unavailable_dates": "April 5-12",
  "willing_to_referee": true,
  "additional_info": "Notes",
  "player_notes": "Internal admin notes",
  "is_coach": false,
  "is_ref": false,
  "is_current_player": true
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Profile updated successfully",
  "player_id": 789,
  "player_name": "John Smith",
  "updated_fields": ["jersey_number", "favorite_position"],
  "updated_data": {
    "jersey_number": 10,
    "favorite_position": "Midfielder"
  }
}
```

**Errors:** `404` player not found

---

### `POST /admin/players/<player_id>/profile-picture`

Upload a profile picture for a player (admin).

**Auth:** JWT required + Role (see above)

**Path Parameters:** `player_id` (int)

**Option 1 - JSON:**

```json
{
  "cropped_image_data": "data:image/png;base64,iVBOR..."
}
```

**Option 2 - Multipart Form:**

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | Image (PNG, JPG, JPEG, WebP, max 5MB) |

**Response (200):**

```json
{
  "success": true,
  "message": "Profile picture updated successfully",
  "player_id": 789,
  "player_name": "John Smith",
  "profile_picture_url": "https://..."
}
```

**Errors:** `400` no file/invalid type/too large, `404` player not found

---

### `DELETE /admin/players/<player_id>/profile-picture`

Delete a player's profile picture (admin).

**Auth:** JWT required + Role (see above)

**Path Parameters:** `player_id` (int)

**Response (200):**

```json
{
  "success": true,
  "message": "Profile picture deleted successfully",
  "player_id": 789,
  "player_name": "John Smith",
  "profile_picture_url": "https://portal.ecsfc.com/static/default_player.png"
}
```

**Errors:** `404` player not found or no picture to delete

---

## 4. Draft - Full Draft System

**Role requirement for all draft endpoints:** `Pub League Coach`, `ECS FC Coach`, `Pub League Admin`, or `Global Admin`

### `GET /draft/<league_name>/available`

Get available (undrafted) players for a league.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `league_name` (string): `classic`, `premier`, `ecs_fc`

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `search` | string | - | Filter by player name |
| `position` | string | - | Filter by position |
| `page` | int | 1 | Page number |
| `per_page` | int | 50 | Results per page (1-100) |

**Response (200):**

```json
{
  "players": [
    {
      "id": 789,
      "name": "John Smith",
      "favorite_position": "Midfielder",
      "career_stats": { "goals": 45, "assists": 22 },
      "season_stats": { "goals": 12, "assists": 5 },
      "existing_ecs_fc_teams": [
        { "id": 10, "name": "ECS FC Men's" }
      ]
    }
  ],
  "total": 30,
  "page": 1,
  "per_page": 50,
  "total_pages": 1,
  "is_ecs_fc_league": false
}
```

**Note:** `existing_ecs_fc_teams` only included for ECS FC leagues.

**Errors:** `400` invalid league name, `404` no current league

---

### `GET /draft/<league_name>/teams`

Get teams in a league with position breakdown.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `league_name` (string)

**Response (200):**

```json
{
  "teams": [
    {
      "id": 1,
      "name": "FC Ballard",
      "player_count": 15,
      "position_breakdown": {
        "GK": 1,
        "DEF": 4,
        "MID": 6,
        "FWD": 4
      }
    }
  ]
}
```

---

### `GET /draft/<league_name>/team/<team_id>/roster`

Get a team's drafted roster.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `league_name` (string), `team_id` (int)

**Response (200):**

```json
{
  "team_id": 1,
  "team_name": "FC Ballard",
  "player_count": 15,
  "players": [
    {
      "id": 789,
      "name": "John Smith",
      "favorite_position": "Midfielder",
      "career_stats": {},
      "season_stats": {}
    }
  ]
}
```

**Errors:** `400` invalid league, `404` league/team not found

---

### `POST /draft/<league_name>/pick`

Draft a player to a team.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `league_name` (string)

**Request Body:**

```json
{
  "player_id": 789,
  "team_id": 1
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "John Smith drafted to FC Ballard",
  "player": {
    "id": 789,
    "name": "John Smith",
    "position": "Midfielder"
  },
  "team": {
    "id": 1,
    "name": "FC Ballard"
  },
  "draft_position": 121
}
```

**Errors:** `400` invalid league/missing fields/already on team, `404` player/team/league not found

---

### `DELETE /draft/<league_name>/pick/<player_id>`

Remove a player from their drafted team.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `league_name` (string), `player_id` (int)

**Response (200):**

```json
{
  "success": true,
  "message": "John Smith removed from FC Ballard",
  "player_id": 789,
  "player_name": "John Smith"
}
```

**Errors:** `400` invalid league/not on a team, `404` league/player not found

---

### `GET /draft/<league_name>/team/<team_id>/analysis`

Get position needs analysis and player recommendations for a team.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `league_name` (string), `team_id` (int)

**Response (200):**

```json
{
  "team_id": 1,
  "team_name": "FC Ballard",
  "current_roster_size": 12,
  "position_needs": {
    "GK": {
      "need_level": "high",
      "current_count": 0,
      "target_count": 1
    },
    "DEF": {
      "need_level": "low",
      "current_count": 4,
      "target_count": 4
    }
  },
  "recommended_players": [
    {
      "player_id": 800,
      "player_name": "New Keeper",
      "position": "GK",
      "fit_score": 0.95,
      "fit_category": "excellent"
    }
  ]
}
```

**Errors:** `400` invalid league, `404` league/team not found, `500` analyzer unavailable

---

### `GET /draft/<league_name>/history`

Get draft pick history.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `league_name` (string)

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number |
| `per_page` | int | 50 | Results per page (1-100) |

**Response (200):**

```json
{
  "history": [
    {
      "position": 1,
      "player": { "id": 789, "name": "John Smith" },
      "team": { "id": 1, "name": "FC Ballard" },
      "drafted_by": "coach_username",
      "drafted_at": "2026-03-15T10:00:00Z"
    }
  ],
  "total": 120,
  "page": 1,
  "per_page": 50,
  "total_pages": 3
}
```

---

## 5. Store - Orders & Eligibility

**Role requirement for all store endpoints:** `Pub League Coach`, `Pub League Admin`, or `Global Admin`

### `GET /store/eligibility`

Check if the user can place a store order this season (one order per season limit).

**Auth:** JWT required + Role (see above)

**Response (200) - Eligible:**

```json
{
  "eligible": true,
  "reason": null,
  "season": { "id": 5, "name": "Spring 2026" },
  "existing_order": null
}
```

**Response (200) - Not eligible:**

```json
{
  "eligible": false,
  "reason": "You have already placed an order this season (Spring 2026). Only one order per season is allowed.",
  "season": { "id": 5, "name": "Spring 2026" },
  "existing_order": {
    "id": 100,
    "item_id": 1,
    "status": "pending",
    "order_date": "2026-03-01T10:00:00Z"
  }
}
```

---

### `POST /store/orders`

Place a store order (one per season).

**Auth:** JWT required + Role (see above)

**Request Body:**

```json
{
  "item_id": 1,
  "quantity": 1,
  "color": "blue",
  "size": "L",
  "notes": "Please include extra socks"
}
```

**Field Notes:**
- `item_id` (required)
- `quantity` (optional, default 1, min 1)
- `color` (required if item has `available_colors`)
- `size` (required if item has `available_sizes`)

**Response (201):**

```json
{
  "success": true,
  "message": "Order placed successfully for 1x ECS Soccer Jersey",
  "order": {
    "id": 100,
    "item_id": 1,
    "item_name": "ECS Soccer Jersey",
    "quantity": 1,
    "color": "blue",
    "size": "L",
    "status": "pending",
    "order_date": "2026-03-27T10:00:00Z"
  }
}
```

**Errors:** `400` missing item_id / invalid quantity / item inactive / invalid color or size / already ordered this season, `404` item not found

---

### `GET /store/my-orders`

Get the authenticated user's order history.

**Auth:** JWT required + Role (see above)

**Response (200):**

```json
{
  "orders": [
    {
      "id": 100,
      "item": {
        "id": 1,
        "name": "ECS Soccer Jersey",
        "image_url": "https://..."
      },
      "quantity": 1,
      "color": "blue",
      "size": "L",
      "status": "pending",
      "notes": "Please include extra socks",
      "order_date": "2026-03-27T10:00:00Z",
      "processed_date": null,
      "delivered_date": null,
      "season": { "id": 5, "name": "Spring 2026" }
    }
  ],
  "total": 1
}
```

---

### `GET /store/orders/<order_id>`

Get details for a specific order.

**Auth:** JWT required + Role (see above)

**Path Parameters:** `order_id` (int)

**Response (200):**

```json
{
  "order": {
    "id": 100,
    "item": {
      "id": 1,
      "name": "ECS Soccer Jersey",
      "description": "Official match jersey",
      "image_url": "https://...",
      "price": 45.00
    },
    "quantity": 1,
    "color": "blue",
    "size": "L",
    "status": "pending",
    "notes": "Please include extra socks",
    "order_date": "2026-03-27T10:00:00Z",
    "processed_date": null,
    "delivered_date": null,
    "ordered_by": { "id": 123, "username": "jsmith" },
    "processed_by": null,
    "season": { "id": 5, "name": "Spring 2026" }
  }
}
```

**Errors:** `403` not the order owner (unless admin), `404` order not found

---

## 6. ECS FC - Availability & RSVP

### `GET /ecs-fc-matches/<match_id>/availability`

Get RSVP/availability details for an ECS FC match. Coaches/admins see full player list; regular players see summary only.

**Auth:** JWT required

**Path Parameters:** `match_id` (int)

**Response (200):**

```json
{
  "match_id": 456,
  "match": {
    "id": 456,
    "date": "2026-04-05",
    "time": "14:00:00",
    "opponent_name": "Ballard FC",
    "location": "Memorial Stadium",
    "is_home_match": true
  },
  "team": { "id": 10, "name": "ECS FC Men's" },
  "rsvp_summary": {
    "yes": 15,
    "no": 3,
    "maybe": 2,
    "no_response": 5
  },
  "has_enough_players": true,
  "players": [
    {
      "id": 789,
      "name": "John Smith",
      "jersey_number": 10,
      "position": "Midfielder",
      "response": "yes",
      "responded_at": "2026-03-25T14:00:00Z",
      "profile_picture_url": "https://...",
      "is_guest": false
    }
  ],
  "total_players": 25,
  "my_availability": "yes"
}
```

---

### `POST /ecs-fc-matches/<match_id>/rsvp`

Update the current user's RSVP for an ECS FC match.

**Auth:** JWT required

**Path Parameters:** `match_id` (int)

**Request Body:**

```json
{
  "response": "yes"
}
```

**Valid values:** `"yes"`, `"no"`, `"maybe"`, `"no_response"`

**Response (200):**

```json
{
  "success": true,
  "message": "RSVP updated",
  "match_id": 456,
  "response": "yes",
  "responded_at": "2026-03-27T10:00:00Z"
}
```

**Errors:** `400` missing/invalid response, `404` match/player not found

---

### `POST /ecs-fc-matches/<match_id>/rsvp/bulk`

Bulk update RSVPs for multiple players (coach/admin only).

**Auth:** JWT required (coach for team or admin)

**Path Parameters:** `match_id` (int)

**Request Body:**

```json
{
  "updates": [
    { "player_id": 789, "response": "yes" },
    { "player_id": 790, "response": "no" }
  ]
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Bulk update completed",
  "results": [
    { "player_id": 789, "success": true, "response": "yes" },
    { "player_id": 790, "success": true, "response": "no" }
  ],
  "successful": 2,
  "failed": 0
}
```

**Errors:** `400` missing data, `403` not coach/admin

---

## 7. ECS FC - Match Reporting & Events

### `GET /ecs-fc-matches/<match_id>/reporting`

Get ECS FC match info for the reporting interface.

**Auth:** JWT required (admin, coach, or team member)

**Path Parameters:** `match_id` (int)

**Response (200):**

```json
{
  "match": {
    "id": 456,
    "team_id": 10,
    "team_name": "ECS FC Men's",
    "opponent_name": "Ballard FC",
    "date": "2026-04-05",
    "time": "14:00",
    "location": "Memorial Stadium",
    "is_home_match": true,
    "home_score": null,
    "away_score": null,
    "status": "scheduled"
  },
  "team_players": [
    { "id": 789, "name": "John Smith", "jersey_number": 10, "position": "Midfielder" }
  ],
  "events": [],
  "can_report": true,
  "valid_event_types": ["goal", "assist", "yellow_card", "red_card", "own_goal"]
}
```

---

### `GET /ecs-fc-matches/<match_id>/events`

Get all events for an ECS FC match.

**Auth:** JWT required

**Path Parameters:** `match_id` (int)

**Response (200):**

```json
{
  "match_id": 456,
  "events": [
    {
      "id": 1,
      "event_type": "goal",
      "player": { "id": 789, "name": "John Smith" },
      "minute": 34,
      "created_at": "2026-04-05T14:34:00Z"
    }
  ],
  "count": 1
}
```

---

### `POST /ecs-fc-matches/<match_id>/events`

Add an event to an ECS FC match.

**Auth:** JWT required (admin, coach, or team member)

**Path Parameters:** `match_id` (int)

**Request Body:**

```json
{
  "event_type": "goal",
  "player_id": 789,
  "minute": 34
}
```

**Valid event types:** `"goal"`, `"assist"`, `"yellow_card"`, `"red_card"`, `"own_goal"`

**Response (201):**

```json
{
  "success": true,
  "message": "Event added",
  "event": {
    "id": 1,
    "event_type": "goal",
    "player": { "id": 789, "name": "John Smith" },
    "minute": 34,
    "created_at": "2026-04-05T14:34:00Z"
  }
}
```

**Errors:** `400` missing/invalid event_type, `403` not authorized, `404` match/player not found

---

### `PUT /ecs-fc-matches/<match_id>/events/<event_id>`

Update an ECS FC match event.

**Auth:** JWT required (admin, coach, or team member)

**Path Parameters:** `match_id` (int), `event_id` (int)

**Request Body (all optional):**

```json
{
  "event_type": "assist",
  "player_id": 790,
  "minute": 35
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Event updated",
  "event": {
    "id": 1,
    "event_type": "assist",
    "player": { "id": 790, "name": "Jane Doe" },
    "minute": 35,
    "created_at": "2026-04-05T14:34:00Z"
  }
}
```

---

### `DELETE /ecs-fc-matches/<match_id>/events/<event_id>`

Delete an ECS FC match event.

**Auth:** JWT required (admin, coach, or team member)

**Path Parameters:** `match_id` (int), `event_id` (int)

**Response (200):**

```json
{
  "success": true,
  "message": "Event deleted"
}
```

---

### `PUT /ecs-fc-matches/<match_id>/score`

Update the score for an ECS FC match.

**Auth:** JWT required (admin, coach, or team member)

**Path Parameters:** `match_id` (int)

**Request Body:**

```json
{
  "home_score": 2,
  "away_score": 1,
  "status": "COMPLETED"
}
```

**Note:** `status` is optional (e.g., `"COMPLETED"`, `"IN_PROGRESS"`).

**Response (200):**

```json
{
  "success": true,
  "message": "Score updated",
  "match": {
    "id": 456,
    "home_score": 2,
    "away_score": 1,
    "status": "COMPLETED"
  }
}
```

---

## 8. ECS FC - Coach RSVP

### `GET /coach/ecs-fc-teams`

Get ECS FC teams the user coaches. Admins see all ECS FC teams.

**Auth:** JWT required

**Response (200):**

```json
{
  "teams": [
    {
      "id": 10,
      "name": "ECS FC Men's",
      "league_id": 8,
      "league_name": "ECS FC"
    }
  ],
  "count": 1,
  "is_admin": false
}
```

---

### `GET /coach/ecs-fc-teams/<team_id>/rsvp`

Get RSVP overview for upcoming ECS FC matches.

**Auth:** JWT required (coach for team or admin)

**Path Parameters:** `team_id` (int)

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 10 | Max matches |

**Response (200):**

```json
{
  "team": { "id": 10, "name": "ECS FC Men's" },
  "matches": [
    {
      "id": 456,
      "opponent_name": "Ballard FC",
      "date": "2026-04-05",
      "time": "14:00",
      "location": "Memorial Stadium",
      "is_home_match": true,
      "status": "scheduled",
      "rsvp_summary": {
        "yes": 15,
        "no": 3,
        "maybe": 2,
        "no_response": 5
      },
      "rsvp_deadline": "2026-04-04T12:00:00Z"
    }
  ],
  "count": 3
}
```

**Errors:** `403` not coach for team, `404` team not found

---

### `GET /coach/ecs-fc-teams/<team_id>/matches/<match_id>/rsvp`

Get detailed per-player RSVP for a specific ECS FC match.

**Auth:** JWT required (coach for team or admin)

**Path Parameters:** `team_id` (int), `match_id` (int)

**Response (200):**

```json
{
  "match": {
    "id": 456,
    "opponent_name": "Ballard FC",
    "date": "2026-04-05",
    "time": "14:00",
    "location": "Memorial Stadium",
    "is_home_match": true
  },
  "rsvp_summary": {
    "yes": 15,
    "no": 3,
    "maybe": 2,
    "no_response": 5
  },
  "players": [
    {
      "id": 789,
      "name": "John Smith",
      "jersey_number": 10,
      "position": "Midfielder",
      "response": "yes",
      "responded_at": "2026-03-25T14:00:00Z",
      "is_guest": false
    }
  ],
  "total_players": 25
}
```

---

### `POST /coach/ecs-fc-teams/<team_id>/matches/<match_id>/rsvp/reminder`

Send RSVP reminder to ECS FC team members.

**Auth:** JWT required (coach for team or admin)

**Path Parameters:** `team_id` (int), `match_id` (int)

**Request Body (all optional):**

```json
{
  "message": "Please RSVP for Saturday's match!",
  "include_responded": false,
  "channels": ["discord"]
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Reminder sent to 5 players",
  "players_notified": 5,
  "channels": ["discord"]
}
```

---

## 9. ECS FC - Substitute System

These endpoints mirror the Pub League substitute system but for ECS FC. The pool is separate.

### `GET /substitutes/ecs-fc/requests`

Get ECS FC substitute requests. Admins see all; coaches see their teams.

**Auth:** JWT required

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | - | `OPEN`, `FILLED`, `CANCELLED` |
| `team_id` | int | - | Filter by team |
| `match_id` | int | - | Filter by match |

**Response (200):**

```json
{
  "requests": [
    {
      "id": 100,
      "match_id": 456,
      "match": {
        "opponent_name": "Ballard FC",
        "date": "2026-04-05",
        "time": "14:00",
        "location": "Memorial Stadium"
      },
      "team_id": 10,
      "team_name": "ECS FC Men's",
      "positions_needed": "DEF, MID",
      "substitutes_needed": 2,
      "notes": "Need cover for injuries",
      "status": "OPEN",
      "created_at": "2026-03-27T10:00:00Z"
    }
  ],
  "count": 1
}
```

---

### `POST /substitutes/ecs-fc/requests`

Create an ECS FC substitute request.

**Auth:** JWT required (coach or admin)

**Request Body:**

```json
{
  "match_id": 456,
  "positions_needed": "DEF, MID",
  "substitutes_needed": 2,
  "notes": "Need cover for injuries"
}
```

**Response (201):**

```json
{
  "success": true,
  "message": "Substitute request created",
  "request_id": 100
}
```

---

### `GET /substitutes/ecs-fc/requests/<request_id>`

Get details of a specific ECS FC substitute request with responses.

**Auth:** JWT required

**Path Parameters:** `request_id` (int)

**Response (200):**

```json
{
  "id": 100,
  "match": {
    "id": 456,
    "opponent_name": "Ballard FC",
    "date": "2026-04-05",
    "time": "14:00",
    "location": "Memorial Stadium"
  },
  "team": { "id": 10, "name": "ECS FC Men's" },
  "positions_needed": "DEF, MID",
  "substitutes_needed": 2,
  "notes": "Need cover for injuries",
  "status": "OPEN",
  "responses": [
    {
      "id": 200,
      "player_id": 800,
      "player_name": "Sub Player",
      "is_available": true,
      "response_text": "I can play DEF",
      "responded_at": "2026-03-27T12:00:00Z"
    }
  ],
  "created_at": "2026-03-27T10:00:00Z"
}
```

---

### `PUT /substitutes/ecs-fc/requests/<request_id>`

Update an ECS FC substitute request.

**Auth:** JWT required (coach for team or admin)

**Path Parameters:** `request_id` (int)

**Request Body (all optional):**

```json
{
  "positions_needed": "MID",
  "substitutes_needed": 1,
  "notes": "Updated needs",
  "status": "FILLED"
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Request updated"
}
```

---

### `DELETE /substitutes/ecs-fc/requests/<request_id>`

Cancel an ECS FC substitute request.

**Auth:** JWT required (coach for team or admin)

**Path Parameters:** `request_id` (int)

**Response (200):**

```json
{
  "success": true,
  "message": "Request cancelled"
}
```

---

### `GET /substitutes/ecs-fc/available-requests`

Get open ECS FC substitute requests for pool members.

**Auth:** JWT required (must be in active ECS FC substitute pool)

**Response (200):**

```json
{
  "requests": [
    {
      "id": 100,
      "match": {
        "opponent_name": "Ballard FC",
        "date": "2026-04-05",
        "time": "14:00",
        "location": "Memorial Stadium",
        "is_home_match": true
      },
      "team_name": "ECS FC Men's",
      "positions_needed": "DEF, MID",
      "substitutes_needed": 2,
      "notes": "Need cover",
      "created_at": "2026-03-27T10:00:00Z"
    }
  ],
  "count": 1
}
```

---

### `POST /substitutes/ecs-fc/requests/<request_id>/respond`

Respond to an ECS FC substitute request.

**Auth:** JWT required (must be in active ECS FC substitute pool)

**Path Parameters:** `request_id` (int)

**Request Body:**

```json
{
  "is_available": true,
  "response_text": "I can play MID"
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Response recorded"
}
```

**Errors:** `400` missing is_available / request not open, `403` not in pool, `404` request/player not found

---

### `POST /substitutes/ecs-fc/requests/<request_id>/assign`

Assign a substitute to an ECS FC request.

**Auth:** JWT required (coach for team or admin)

**Path Parameters:** `request_id` (int)

**Request Body:**

```json
{
  "player_id": 800,
  "position_assigned": "DEF",
  "notes": "Confirmed"
}
```

**Response (201):**

```json
{
  "success": true,
  "message": "Substitute assigned",
  "assignment_id": 300
}
```

---

### `GET /substitutes/ecs-fc/pool/my-status`

Get the user's ECS FC substitute pool membership.

**Auth:** JWT required

**Response (200):**

```json
{
  "in_pool": true,
  "is_active": true,
  "preferred_positions": "DEF, MID",
  "max_matches_per_week": 2,
  "sms_notifications": true,
  "discord_notifications": true,
  "email_notifications": true,
  "requests_received": 3,
  "requests_accepted": 2,
  "matches_played": 1,
  "joined_at": "2026-01-15T00:00:00Z"
}
```

---

### `PUT /substitutes/ecs-fc/pool/my-status`

Update ECS FC substitute pool preferences.

**Auth:** JWT required (must be in pool)

**Request Body (all optional):**

```json
{
  "is_active": true,
  "preferred_positions": "FWD",
  "max_matches_per_week": 3,
  "sms_notifications": false,
  "discord_notifications": true,
  "email_notifications": true
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Pool preferences updated"
}
```

---

### `POST /substitutes/ecs-fc/pool/join`

Join the ECS FC substitute pool.

**Auth:** JWT required

**Request Body (all optional):**

```json
{
  "preferred_positions": "DEF, MID",
  "max_matches_per_week": 2,
  "sms_notifications": true,
  "discord_notifications": true,
  "email_notifications": true
}
```

**Response (201):**

```json
{
  "success": true,
  "message": "Joined ECS FC substitute pool"
}
```

**Response (200) - Reactivation:**

```json
{
  "success": true,
  "message": "Pool membership reactivated"
}
```

**Errors:** `400` already in pool, `404` player not found

---

### `DELETE /substitutes/ecs-fc/pool/leave`

Leave the ECS FC substitute pool.

**Auth:** JWT required

**Response (200):**

```json
{
  "success": true,
  "message": "Left ECS FC substitute pool"
}
```

**Errors:** `404` not in pool

---

## 10. Predictions URL Correction

The Predictions endpoints documented in the main doc use a **different URL prefix** than all other mobile API endpoints.

**Predictions base URL:** `/api` (NOT `/api/v1`)

The correct full URLs are:
- `GET /api/match/by_thread/<discord_thread_id>`
- `POST /api/predictions`
- `GET /api/predictions/<match_id>`
- `GET /api/predictions/<match_id>/correct`

These endpoints use no authentication (they are called by the Discord bot). They are registered on a separate `predictions_api` blueprint, not the main `mobile_api_v2` blueprint.
