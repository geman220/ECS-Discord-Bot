"""
FastAPI router for posting native Discord polls.

Used by Flask to post availability polls (e.g. to #pl-subs) on behalf of an
admin in the mobile app. Posts the poll plus a role-mention prefix so members
of the targeted roles get a notification.
"""

from datetime import timedelta, timezone
from typing import List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import discord
from discord.ext import commands

from api.utils.discord_utils import get_bot

logger = logging.getLogger(__name__)
router = APIRouter()


class PollAnswer(BaseModel):
    text: str = Field(..., min_length=1, max_length=55)
    emoji: Optional[str] = None


class PostPollRequest(BaseModel):
    channel_id: str
    tag_role_ids: List[str] = Field(default_factory=list)
    question: str = Field(..., min_length=1, max_length=300)
    answers: List[PollAnswer] = Field(..., min_items=2, max_items=10)
    duration_hours: int = Field(..., ge=1, le=168)
    allow_multiselect: bool = False


@router.post("/api/discord/post-poll")
async def post_poll(
    payload: PostPollRequest,
    bot: commands.Bot = Depends(get_bot),
):
    try:
        channel = bot.get_channel(int(payload.channel_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Invalid channel_id")
    if channel is None:
        raise HTTPException(
            status_code=502,
            detail=f"Channel {payload.channel_id} not found",
        )

    poll = discord.Poll(
        question=payload.question,
        duration=timedelta(hours=payload.duration_hours),
        multiple=payload.allow_multiselect,
    )
    # Discord assigns answer IDs in insertion order starting at 1.
    answers_with_ids = []
    for idx, ans in enumerate(payload.answers, start=1):
        if ans.emoji:
            poll.add_answer(text=ans.text, emoji=ans.emoji)
        else:
            poll.add_answer(text=ans.text)
        answers_with_ids.append({
            "answer_id": idx,
            "text": ans.text,
            "emoji": ans.emoji,
        })

    mentions = " ".join(f"<@&{rid}>" for rid in payload.tag_role_ids)

    try:
        sent = await channel.send(
            content=mentions if mentions else None,
            poll=poll,
            allowed_mentions=discord.AllowedMentions(
                roles=True, everyone=False, users=False
            ),
        )
    except discord.Forbidden as e:
        logger.warning(
            "Forbidden posting poll to channel %s: %s", payload.channel_id, e
        )
        raise HTTPException(
            status_code=502,
            detail=f"Bot lacks permission to post poll: {e}",
        )
    except discord.HTTPException as e:
        logger.error("Discord API error posting poll: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Discord API error: {e.status} {e.text}",
        )
    except Exception as e:
        logger.exception("Unexpected error posting poll")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to post poll: {e}",
        )

    expires_at = (
        sent.created_at.astimezone(timezone.utc)
        + timedelta(hours=payload.duration_hours)
    ).isoformat()
    guild_id = channel.guild.id if getattr(channel, "guild", None) else 0
    message_url = (
        f"https://discord.com/channels/{guild_id}/{channel.id}/{sent.id}"
    )

    return {
        "success": True,
        "message_id": str(sent.id),
        "channel_id": str(channel.id),
        "channel_name": channel.name,
        "guild_id": str(guild_id),
        "expires_at": expires_at,
        "message_url": message_url,
        "answers": answers_with_ids,
    }


class PostSurveyEmbedRequest(BaseModel):
    channel_id: str
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field("", max_length=2000)
    url: str = Field(..., min_length=1)
    button_label: str = Field("Take Survey", min_length=1, max_length=80)
    tag_role_ids: List[str] = Field(default_factory=list)


@router.post("/api/discord/post-survey-embed")
async def post_survey_embed(
    payload: PostSurveyEmbedRequest,
    bot: commands.Bot = Depends(get_bot),
):
    """Post an embed with a link button that opens the hosted survey form.

    Used by Flask to publish a multi-question survey to a channel (e.g.
    #pl-announcements). Mirrors post_poll's role-mention + error handling.
    """
    try:
        channel = bot.get_channel(int(payload.channel_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Invalid channel_id")
    if channel is None:
        raise HTTPException(
            status_code=502, detail=f"Channel {payload.channel_id} not found"
        )

    embed = discord.Embed(
        title=payload.title,
        description=payload.description or None,
        color=discord.Color.from_str("#1a472a"),
    )
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=payload.button_label, url=payload.url))

    mentions = " ".join(f"<@&{rid}>" for rid in payload.tag_role_ids)

    try:
        sent = await channel.send(
            content=mentions if mentions else None,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(
                roles=True, everyone=False, users=False
            ),
        )
    except discord.Forbidden as e:
        logger.warning(
            "Forbidden posting survey embed to channel %s: %s", payload.channel_id, e
        )
        raise HTTPException(
            status_code=502, detail=f"Bot lacks permission to post embed: {e}"
        )
    except discord.HTTPException as e:
        logger.error("Discord API error posting survey embed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"Discord API error: {e.status} {e.text}"
        )
    except Exception as e:
        logger.exception("Unexpected error posting survey embed")
        raise HTTPException(status_code=500, detail=f"Failed to post embed: {e}")

    guild_id = channel.guild.id if getattr(channel, "guild", None) else 0
    message_url = (
        f"https://discord.com/channels/{guild_id}/{channel.id}/{sent.id}"
    )
    return {
        "success": True,
        "message_id": str(sent.id),
        "channel_id": str(channel.id),
        "channel_name": channel.name,
        "guild_id": str(guild_id),
        "message_url": message_url,
    }
