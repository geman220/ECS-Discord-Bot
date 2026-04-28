# api/routes/ispy_routes.py

"""
I-Spy API Routes

Provides API endpoints for I-Spy mobile integration:
- Upload image to Discord and get CDN URL
- Post I-Spy submission notification to channel
"""

import logging
import os
from io import BytesIO
from typing import List, Optional

import discord
from discord.ext import commands
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from api.utils.discord_utils import get_bot
from shared_states import get_bot_instance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ispy", tags=["ispy"])

# Channel name where I-Spy posts go
ISPY_CHANNEL_NAME = "pl-miscellaneous"

# Channel that receives admin-only iSpy notifications (removal requests, etc.).
# Override via env var. Falls through to a 404 if the channel doesn't exist —
# we deliberately do NOT fall back to the public pl-miscellaneous channel because
# that would leak the requester's identity and reason to all users.
ISPY_ADMIN_CHANNEL_NAME = os.getenv("ISPY_ADMIN_CHANNEL_NAME", "ispy-mod")

# Optional: Configure a dedicated channel for image uploads (hidden from users)
# If not set, images will be uploaded to the same channel as notifications
ISPY_IMAGE_UPLOAD_CHANNEL_ID = None  # Set to a channel ID if you want a separate upload channel


class ISpySubmissionNotification(BaseModel):
    """Request model for I-Spy submission notifications."""
    shot_id: int
    author_discord_id: str
    author_name: str
    target_discord_ids: List[str]
    target_names: List[str]
    category: str
    location: str
    image_url: str
    points_awarded: int


def get_ispy_channel(bot: commands.Bot) -> Optional[discord.TextChannel]:
    """Find the I-Spy channel (#pl-miscellaneous) in any guild the bot is in."""
    for guild in bot.guilds:
        for channel in guild.channels:
            if channel.name == ISPY_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                return channel
    return None


def get_ispy_admin_channel(bot: commands.Bot) -> Optional[discord.TextChannel]:
    """Find the iSpy admin/mod channel by name (configured via ISPY_ADMIN_CHANNEL_NAME)."""
    for guild in bot.guilds:
        for channel in guild.channels:
            if channel.name == ISPY_ADMIN_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                return channel
    return None


@router.post("/upload-image")
async def upload_ispy_image(
    image: UploadFile = File(...),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Upload an image to Discord and return the CDN URL.

    This endpoint receives an image from the Flask app, uploads it to a Discord
    channel, and returns the resulting CDN URL that can be used in embeds.

    Args:
        image: The image file to upload (multipart form data)
        bot: Discord bot instance (injected)

    Returns:
        JSON with image_url (Discord CDN URL)
    """
    try:
        # Read image data
        image_data = await image.read()

        if not image_data:
            raise HTTPException(status_code=400, detail="Empty image file")

        # Validate image size (max 10MB)
        if len(image_data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image too large. Maximum size is 10MB")

        # Get filename
        filename = image.filename or "ispy_upload.jpg"

        # Find upload channel
        upload_channel = None

        if ISPY_IMAGE_UPLOAD_CHANNEL_ID:
            upload_channel = bot.get_channel(ISPY_IMAGE_UPLOAD_CHANNEL_ID)

        if not upload_channel:
            # Fall back to the I-Spy channel
            upload_channel = get_ispy_channel(bot)

        if not upload_channel:
            logger.error("Could not find I-Spy channel for image upload")
            raise HTTPException(status_code=404, detail=f"Channel '{ISPY_CHANNEL_NAME}' not found")

        # Create Discord file object
        discord_file = discord.File(
            BytesIO(image_data),
            filename=filename
        )

        # Send to channel (this uploads to Discord CDN)
        # We'll delete this message after getting the URL if using the main channel
        message = await upload_channel.send(
            content="📸 *I-Spy image upload (processing...)*",
            file=discord_file
        )

        # Extract CDN URL from attachment
        if not message.attachments:
            await message.delete()
            raise HTTPException(status_code=500, detail="Failed to upload image - no attachment returned")

        cdn_url = message.attachments[0].url

        # If we uploaded to the main channel, delete the temp message
        # (the actual submission notification will be posted separately)
        if not ISPY_IMAGE_UPLOAD_CHANNEL_ID:
            try:
                await message.delete()
            except discord.HTTPException:
                pass  # Ignore deletion errors

        logger.info(f"Image uploaded to Discord CDN: {cdn_url}")

        return {
            "success": True,
            "image_url": cdn_url,
            "filename": filename
        }

    except HTTPException:
        raise
    except discord.Forbidden as e:
        logger.error(f"Permission denied uploading image: {e}")
        raise HTTPException(status_code=403, detail="Bot lacks permission to upload to channel")
    except discord.HTTPException as e:
        logger.error(f"Discord API error uploading image: {e}")
        raise HTTPException(status_code=502, detail=f"Discord API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error uploading I-Spy image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notify-submission")
async def notify_ispy_submission(
    data: ISpySubmissionNotification,
    bot: commands.Bot = Depends(get_bot)
):
    """
    Post an I-Spy submission notification to the Discord channel.

    This creates an embed similar to what the /ispy Discord command creates,
    allowing mobile submissions to appear in Discord just like native ones.

    Args:
        data: Submission notification data
        bot: Discord bot instance (injected)

    Returns:
        JSON with success status and message_id
    """
    try:
        # Find the I-Spy channel
        channel = get_ispy_channel(bot)

        if not channel:
            logger.error(f"Could not find channel '{ISPY_CHANNEL_NAME}' for I-Spy notification")
            raise HTTPException(status_code=404, detail=f"Channel '{ISPY_CHANNEL_NAME}' not found")

        # Format targets with Discord mentions
        target_mentions = []
        for discord_id, name in zip(data.target_discord_ids, data.target_names):
            target_mentions.append(f"<@{discord_id}> ({name})")

        targets_text = "\n".join(target_mentions) if target_mentions else "Unknown"

        # Create the embed (matching the style from ispy_commands.py)
        embed = discord.Embed(
            title="📸 I-Spy Shot!",
            color=discord.Color.green(),
            description=f"**{data.author_name}** spotted some people!"
        )

        embed.add_field(
            name="📍 Location",
            value=data.location,
            inline=True
        )

        embed.add_field(
            name="🏷️ Category",
            value=data.category.title(),
            inline=True
        )

        embed.add_field(
            name="🏆 Points Earned",
            value=f"**{data.points_awarded}** points",
            inline=True
        )

        embed.add_field(
            name="🎯 Targets",
            value=targets_text,
            inline=False
        )

        # Set the image
        embed.set_image(url=data.image_url)

        # Add footer
        embed.set_footer(text=f"Shot ID: {data.shot_id} • Submitted via Mobile App")

        # Send the notification
        message = await channel.send(
            content=f"<@{data.author_discord_id}> submitted an I-Spy shot! 📸",
            embed=embed
        )

        logger.info(f"I-Spy notification posted for shot {data.shot_id} by {data.author_name}")

        return {
            "success": True,
            "message_id": str(message.id),
            "channel_id": str(channel.id)
        }

    except HTTPException:
        raise
    except discord.Forbidden as e:
        logger.error(f"Permission denied posting I-Spy notification: {e}")
        raise HTTPException(status_code=403, detail="Bot lacks permission to post in channel")
    except discord.HTTPException as e:
        logger.error(f"Discord API error posting notification: {e}")
        raise HTTPException(status_code=502, detail=f"Discord API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error posting I-Spy notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class ISpyDeleteSubmission(BaseModel):
    """Request model for deleting an iSpy submission's Discord post."""
    shot_id: int
    message_id: str
    channel_id: Optional[str] = None  # If provided, look up by id; else search by name


class ISpyRemovalRequest(BaseModel):
    """Request model for an admin-channel removal request notification."""
    shot_id: int
    requester_discord_id: str
    requester_name: str
    author_discord_id: Optional[str] = None
    reason: str
    message_id: Optional[str] = None
    channel_id: Optional[str] = None


@router.post("/delete-submission")
async def delete_ispy_submission(
    data: ISpyDeleteSubmission,
    bot: commands.Bot = Depends(get_bot)
):
    """
    Delete the Discord message for a previously-posted iSpy submission.

    Flask is the authoritative source — the DB row is already soft-deleted by
    the time this fires. This endpoint just removes the post from Discord so
    other users stop seeing it.
    """
    try:
        # Prefer channel_id when supplied; fall back to the configured name.
        channel: Optional[discord.TextChannel] = None
        if data.channel_id:
            try:
                channel_id_int = int(data.channel_id)
                got = bot.get_channel(channel_id_int)
                if isinstance(got, discord.TextChannel):
                    channel = got
            except ValueError:
                pass
        if channel is None:
            channel = get_ispy_channel(bot)
        if channel is None:
            raise HTTPException(status_code=404, detail="iSpy channel not found")

        try:
            message_id_int = int(data.message_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="message_id must be a numeric Discord snowflake")

        try:
            message = await channel.fetch_message(message_id_int)
        except discord.NotFound:
            # Already gone — treat as success so Flask doesn't keep retrying.
            logger.info(f"iSpy delete: shot {data.shot_id} message {message_id_int} already gone")
            return {"success": True, "already_deleted": True}

        await message.delete()
        logger.info(f"iSpy delete: removed Discord message {message_id_int} for shot {data.shot_id}")
        return {"success": True, "shot_id": data.shot_id}

    except HTTPException:
        raise
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="Bot lacks Manage Messages on iSpy channel")
    except discord.HTTPException as e:
        raise HTTPException(status_code=502, detail=f"Discord API error: {e}")
    except Exception as e:
        logger.error(f"Error deleting iSpy submission {data.shot_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/removal-request")
async def post_ispy_removal_request(
    data: ISpyRemovalRequest,
    bot: commands.Bot = Depends(get_bot)
):
    """
    Forward a tagged-player removal request to the iSpy admin channel.

    Configurable via env var ISPY_ADMIN_CHANNEL_NAME (default: ispy-mod).
    Deliberately does not fall back to the public iSpy channel — leaking a
    private removal request to everyone would defeat the point.
    """
    try:
        channel = get_ispy_admin_channel(bot)
        if channel is None:
            logger.error(
                f"iSpy removal-request: admin channel '{ISPY_ADMIN_CHANNEL_NAME}' not found in any guild. "
                f"Set ISPY_ADMIN_CHANNEL_NAME env var or create the channel."
            )
            raise HTTPException(
                status_code=404,
                detail=f"iSpy admin channel '{ISPY_ADMIN_CHANNEL_NAME}' not found"
            )

        embed = discord.Embed(
            title="⚠️ iSpy removal request",
            color=discord.Color.orange(),
            description="A tagged player has requested admin review of an iSpy submission."
        )
        embed.add_field(
            name="Requester",
            value=f"<@{data.requester_discord_id}> ({data.requester_name})",
            inline=False
        )
        if data.author_discord_id:
            embed.add_field(
                name="Original submitter",
                value=f"<@{data.author_discord_id}>",
                inline=True
            )
        embed.add_field(
            name="Shot ID",
            value=str(data.shot_id),
            inline=True
        )
        # Reason is user-supplied free text — Discord renders this raw, but
        # it's contained inside an embed field so injected formatting only
        # affects this one block. Trim to embed limits.
        reason = data.reason or '(no reason provided)'
        if len(reason) > 1000:
            reason = reason[:1000] + '…'
        embed.add_field(name="Reason", value=reason, inline=False)

        # Build a jump-to-message link if we have message + channel coordinates.
        content_parts = []
        if data.channel_id and data.message_id:
            try:
                guild_id = channel.guild.id
                jump_url = f"https://discord.com/channels/{guild_id}/{int(data.channel_id)}/{int(data.message_id)}"
                content_parts.append(f"Original post: {jump_url}")
            except (ValueError, AttributeError):
                pass

        await channel.send(
            content="\n".join(content_parts) if content_parts else None,
            embed=embed,
        )
        logger.info(f"iSpy removal-request posted to admin channel for shot {data.shot_id}")
        return {"success": True, "shot_id": data.shot_id}

    except HTTPException:
        raise
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail=f"Bot lacks send permission on '{ISPY_ADMIN_CHANNEL_NAME}'")
    except discord.HTTPException as e:
        raise HTTPException(status_code=502, detail=f"Discord API error: {e}")
    except Exception as e:
        logger.error(f"Error posting iSpy removal-request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def ispy_health():
    """Health check for I-Spy endpoints."""
    try:
        bot = get_bot_instance()
        channel = get_ispy_channel(bot) if bot and bot.is_ready() else None
        admin_channel = get_ispy_admin_channel(bot) if bot and bot.is_ready() else None

        return {
            "status": "healthy",
            "bot_ready": bot.is_ready() if bot else False,
            "ispy_channel_found": channel is not None,
            "ispy_channel_name": ISPY_CHANNEL_NAME,
            "ispy_admin_channel_found": admin_channel is not None,
            "ispy_admin_channel_name": ISPY_ADMIN_CHANNEL_NAME,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
