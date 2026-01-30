# app/services/mobile/player_admin_service.py

"""
Mobile Player Admin Service

Handles administrative operations on player profiles for mobile clients including:
- Admin notes management (CRUD with attribution)
- Profile editing for any player (admin/coach only)
- Profile picture management for any player

All methods accept player_id for easier mobile app integration.
Requires appropriate permissions (admin or coach roles).
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session, joinedload

from app.services.base_service import BaseService, ServiceResult
from app.models import User, Player
from app.models.players import PlayerAdminNote

logger = logging.getLogger(__name__)


class PlayerAdminService(BaseService):
    """
    Service for administrative operations on player profiles.

    Handles admin notes, profile editing, and photo management
    for coaches and admins to manage any player's profile.
    """

    def __init__(self, session: Session):
        super().__init__(session)

    # ==================== Admin Notes Management ====================

    def get_player_admin_notes(
        self,
        player_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get admin notes for a player.

        Args:
            player_id: The player's ID
            limit: Maximum number of notes to return
            offset: Pagination offset

        Returns:
            ServiceResult with list of admin notes
        """
        player = self.session.query(Player).get(player_id)
        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        # Query notes with author info
        notes_query = self.session.query(PlayerAdminNote).filter(
            PlayerAdminNote.player_id == player_id
        ).options(
            joinedload(PlayerAdminNote.author).joinedload(User.player)
        ).order_by(PlayerAdminNote.created_at.desc())

        total_count = notes_query.count()
        notes = notes_query.offset(offset).limit(limit).all()

        notes_data = [note.to_dict(include_author=True) for note in notes]

        return ServiceResult.ok({
            "player_id": player.id,
            "player_name": player.name,
            "notes": notes_data,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(notes_data) < total_count
        })

    def create_admin_note(
        self,
        player_id: int,
        author_id: int,
        content: str
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Create a new admin note for a player.

        Args:
            player_id: The player's ID
            author_id: The user ID of the note author
            content: The note content

        Returns:
            ServiceResult with the created note
        """
        if not content or not content.strip():
            return ServiceResult.fail("Note content is required", "CONTENT_REQUIRED")

        player = self.session.query(Player).get(player_id)
        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        author = self.session.query(User).get(author_id)
        if not author:
            return ServiceResult.fail("Author not found", "AUTHOR_NOT_FOUND")

        # Create the note
        note = PlayerAdminNote(
            player_id=player_id,
            author_id=author_id,
            content=content.strip()
        )
        self.session.add(note)
        self.session.commit()

        # Refresh to get the ID and load relationships
        self.session.refresh(note)

        logger.info(f"Admin note created for player {player_id} by user {author_id}")

        return ServiceResult.ok({
            "note": note.to_dict(include_author=True),
            "player_id": player.id,
            "player_name": player.name
        })

    def update_admin_note(
        self,
        note_id: int,
        editor_id: int,
        content: str,
        allow_edit_others: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Update an existing admin note.

        Args:
            note_id: The note's ID
            editor_id: The user ID of the editor
            content: The new note content
            allow_edit_others: If True, allow editing notes by other authors (admin only)

        Returns:
            ServiceResult with the updated note
        """
        if not content or not content.strip():
            return ServiceResult.fail("Note content is required", "CONTENT_REQUIRED")

        note = self.session.query(PlayerAdminNote).options(
            joinedload(PlayerAdminNote.author).joinedload(User.player),
            joinedload(PlayerAdminNote.player)
        ).get(note_id)

        if not note:
            return ServiceResult.fail("Note not found", "NOTE_NOT_FOUND")

        # Check if user can edit this note
        if note.author_id != editor_id and not allow_edit_others:
            return ServiceResult.fail(
                "You can only edit your own notes",
                "NOT_AUTHORIZED"
            )

        # Update the note
        note.content = content.strip()
        note.updated_at = datetime.utcnow()
        self.session.commit()

        logger.info(f"Admin note {note_id} updated by user {editor_id}")

        return ServiceResult.ok({
            "note": note.to_dict(include_author=True),
            "player_id": note.player_id,
            "player_name": note.player.name if note.player else None
        })

    def delete_admin_note(
        self,
        note_id: int,
        deleter_id: int,
        allow_delete_others: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Delete an admin note.

        Args:
            note_id: The note's ID
            deleter_id: The user ID of the deleter
            allow_delete_others: If True, allow deleting notes by other authors (admin only)

        Returns:
            ServiceResult with deletion confirmation
        """
        note = self.session.query(PlayerAdminNote).options(
            joinedload(PlayerAdminNote.player)
        ).get(note_id)

        if not note:
            return ServiceResult.fail("Note not found", "NOTE_NOT_FOUND")

        # Check if user can delete this note
        if note.author_id != deleter_id and not allow_delete_others:
            return ServiceResult.fail(
                "You can only delete your own notes",
                "NOT_AUTHORIZED"
            )

        player_id = note.player_id
        player_name = note.player.name if note.player else None

        self.session.delete(note)
        self.session.commit()

        logger.info(f"Admin note {note_id} deleted by user {deleter_id}")

        return ServiceResult.ok({
            "deleted_note_id": note_id,
            "player_id": player_id,
            "player_name": player_name
        })

    # ==================== Profile Management ====================

    def update_player_profile(
        self,
        player_id: int,
        editor_id: int,
        data: Dict[str, Any]
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Update a player's profile (admin/coach operation).

        Args:
            player_id: The player's ID
            editor_id: The user ID making the edit
            data: Dictionary of fields to update

        Returns:
            ServiceResult with updated player data
        """
        player = self.session.query(Player).options(
            joinedload(Player.user),
            joinedload(Player.primary_team)
        ).get(player_id)

        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        # Fields that admins/coaches can update
        allowed_fields = [
            'name', 'phone', 'jersey_size', 'jersey_number', 'pronouns',
            'favorite_position', 'other_positions', 'positions_not_to_play',
            'frequency_play_goal', 'expected_weeks_available', 'unavailable_dates',
            'willing_to_referee', 'additional_info', 'player_notes',
            'is_coach', 'is_ref', 'is_current_player'
        ]

        updated_fields = []
        for field in allowed_fields:
            if field in data:
                old_value = getattr(player, field, None)
                new_value = data[field]

                # Handle type conversions
                if field == 'jersey_number' and new_value is not None:
                    try:
                        new_value = int(new_value) if new_value != '' else None
                    except (ValueError, TypeError):
                        continue

                if field in ['is_coach', 'is_ref', 'is_current_player']:
                    new_value = bool(new_value)

                if old_value != new_value:
                    setattr(player, field, new_value)
                    updated_fields.append(field)

        if updated_fields:
            player.profile_last_updated = datetime.utcnow()
            self.session.commit()
            logger.info(
                f"Player {player_id} profile updated by user {editor_id}. "
                f"Fields: {', '.join(updated_fields)}"
            )

        return ServiceResult.ok({
            "player_id": player.id,
            "player_name": player.name,
            "updated_fields": updated_fields,
            "player": self._build_player_response(player)
        })

    def upload_player_profile_picture(
        self,
        player_id: int,
        uploader_id: int,
        image_data: str
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Upload a profile picture for a player (admin/coach operation).

        Args:
            player_id: The player's ID
            uploader_id: The user ID uploading the picture
            image_data: Base64 encoded image data (data:image/...;base64,...)

        Returns:
            ServiceResult with new profile picture URL
        """
        player = self.session.query(Player).get(player_id)
        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        try:
            from app.players_helpers import save_cropped_profile_picture

            new_profile_picture_path = save_cropped_profile_picture(
                image_data,
                player.id
            )

            player.profile_picture_url = new_profile_picture_path
            self.session.commit()

            logger.info(
                f"Profile picture updated for player {player_id} by user {uploader_id}"
            )

            return ServiceResult.ok({
                "player_id": player.id,
                "player_name": player.name,
                "profile_picture_url": new_profile_picture_path
            })

        except ValueError as e:
            return ServiceResult.fail(str(e), "INVALID_IMAGE")
        except Exception as e:
            logger.error(f"Error uploading profile picture: {e}")
            return ServiceResult.fail(
                "Failed to upload profile picture",
                "UPLOAD_FAILED"
            )

    def delete_player_profile_picture(
        self,
        player_id: int,
        deleter_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Delete a player's profile picture (admin/coach operation).

        Args:
            player_id: The player's ID
            deleter_id: The user ID deleting the picture

        Returns:
            ServiceResult with confirmation
        """
        import os
        from flask import current_app

        player = self.session.query(Player).get(player_id)
        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        if not player.profile_picture_url:
            return ServiceResult.fail(
                "Player has no profile picture",
                "NO_PICTURE"
            )

        try:
            # Delete the file if it's local
            old_path = player.profile_picture_url
            if old_path and not old_path.startswith('http'):
                full_path = os.path.join(
                    current_app.root_path,
                    old_path.lstrip('/')
                )
                if os.path.exists(full_path):
                    os.remove(full_path)

            player.profile_picture_url = None
            self.session.commit()

            logger.info(
                f"Profile picture deleted for player {player_id} by user {deleter_id}"
            )

            return ServiceResult.ok({
                "player_id": player.id,
                "player_name": player.name,
                "profile_picture_url": None
            })

        except Exception as e:
            logger.error(f"Error deleting profile picture: {e}")
            return ServiceResult.fail(
                "Failed to delete profile picture",
                "DELETE_FAILED"
            )

    def get_player_full_profile(
        self,
        player_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get full player profile including admin-only fields.

        Args:
            player_id: The player's ID

        Returns:
            ServiceResult with complete player profile data
        """
        player = self.session.query(Player).options(
            joinedload(Player.user),
            joinedload(Player.primary_team),
            joinedload(Player.teams),
            joinedload(Player.admin_notes).joinedload(PlayerAdminNote.author)
        ).get(player_id)

        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        return ServiceResult.ok({
            "player": self._build_player_response(player, include_admin_fields=True),
            "admin_notes": [
                note.to_dict(include_author=True)
                for note in player.admin_notes[:10]  # Last 10 notes
            ],
            "admin_notes_count": len(player.admin_notes)
        })

    # ==================== Internal Helpers ====================

    def _build_player_response(
        self,
        player: Player,
        include_admin_fields: bool = False
    ) -> Dict[str, Any]:
        """Build player response dictionary."""
        from flask import request

        base_url = request.host_url.rstrip('/') if request else ''
        default_image = f"{base_url}/static/img/default_player.png"

        data = {
            "id": player.id,
            "name": player.name,
            "jersey_number": player.jersey_number,
            "jersey_size": player.jersey_size,
            "pronouns": player.pronouns,
            "phone": player.phone,
            "favorite_position": player.favorite_position,
            "other_positions": player.other_positions,
            "positions_not_to_play": player.positions_not_to_play,
            "frequency_play_goal": player.frequency_play_goal,
            "expected_weeks_available": player.expected_weeks_available,
            "unavailable_dates": player.unavailable_dates,
            "willing_to_referee": player.willing_to_referee,
            "additional_info": player.additional_info,
            "player_notes": player.player_notes,
            "profile_picture_url": (
                player.profile_picture_url
                if player.profile_picture_url and player.profile_picture_url.startswith('http')
                else f"{base_url}{player.profile_picture_url}"
                if player.profile_picture_url
                else default_image
            ),
            "is_current_player": player.is_current_player,
            "profile_last_updated": (
                player.profile_last_updated.isoformat()
                if player.profile_last_updated else None
            ),
        }

        if include_admin_fields:
            data.update({
                "is_coach": player.is_coach,
                "is_ref": player.is_ref,
                "discord_id": player.discord_id,
                "discord_username": player.discord_username,
                "discord_in_server": player.discord_in_server,
                "user_id": player.user_id,
                "primary_team_id": player.primary_team_id,
                "primary_team_name": player.primary_team.name if player.primary_team else None,
            })

            if player.user:
                data["user"] = {
                    "id": player.user.id,
                    "username": player.user.username,
                    "email": player.user.email,
                    "email_notifications": player.user.email_notifications,
                    "sms_notifications": player.user.sms_notifications,
                    "discord_notifications": player.user.discord_notifications,
                }

        return data
