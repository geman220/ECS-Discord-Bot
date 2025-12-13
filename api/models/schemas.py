from pydantic import BaseModel, Field
from typing import List, Optional, Union


class PermissionOverwriteRequest(BaseModel):
    id: int  # Role or Member ID
    type: int  # 0 for role, 1 for member
    allow: Optional[str] = "0"
    deny: Optional[str] = "0"


class ChannelRequest(BaseModel):
    name: str
    type: int = Field(..., description="Channel type: 0 for text channel, 4 for category")
    parent_id: Optional[int] = Field(None, description="Parent category ID (only for text channels)")
    permission_overwrites: Optional[List[PermissionOverwriteRequest]] = None


class PermissionRequest(BaseModel):
    id: int
    type: int
    allow: str
    deny: str


class RoleRequest(BaseModel):
    name: str
    permissions: str = "0"  # String representation of permissions integer
    mentionable: bool = False


class UpdateChannelRequest(BaseModel):
    new_name: str


class UpdateRoleRequest(BaseModel):
    new_name: str


class AvailabilityRequest(BaseModel):
    match_id: int
    home_team_id: int
    away_team_id: int
    home_channel_id: Union[int, str]
    away_channel_id: Union[int, str]
    home_team_name: str
    away_team_name: str
    match_date: str
    match_time: str


class EmbedField(BaseModel):
    name: str
    value: str
    inline: bool = False


class EmbedData(BaseModel):
    title: str
    description: str
    color: int
    fields: List[EmbedField]
    thumbnail_url: Optional[str] = None
    footer_text: Optional[str] = None


class MessageContent(BaseModel):
    content: str
    embed_data: EmbedData


class ThreadRequest(BaseModel):
    name: str
    type: int = 11
    auto_archive_duration: int = 4320  # 72 hours in minutes
    message: MessageContent


class LeaguePollRequest(BaseModel):
    poll_id: int
    title: str
    question: str
    teams: List[dict]  # List of {team_id, channel_id, message_record_id}


class PollResponseRequest(BaseModel):
    poll_id: int
    discord_id: str
    response: str  # 'yes', 'no', 'maybe'


class PlayerChange(BaseModel):
    player_id: int
    player_name: str
    new_availability: str
    timestamp: str


class DiscordEmbedUpdateRequest(BaseModel):
    match_id: int
    channel_id: int
    message_id: int
    trigger_source: str
    player_change: Optional[PlayerChange] = None


class LeagueEventAnnouncementRequest(BaseModel):
    """Request to post a league event announcement to Discord."""
    event_id: int
    title: str
    description: Optional[str] = None
    event_type: str = "other"  # party, meeting, social, training, tournament, other
    location: Optional[str] = None
    start_datetime: str  # ISO format
    end_datetime: Optional[str] = None
    is_all_day: bool = False
    channel_id: Optional[int] = None  # If None, uses configured default channel
    channel_name: Optional[str] = None  # Alternative: lookup channel by name


class LeagueEventUpdateRequest(BaseModel):
    """Request to update an existing league event announcement."""
    event_id: int
    message_id: int
    channel_id: int
    title: str
    description: Optional[str] = None
    event_type: str = "other"
    location: Optional[str] = None
    start_datetime: str
    end_datetime: Optional[str] = None
    is_all_day: bool = False


class LeagueEventDeleteRequest(BaseModel):
    """Request to delete a league event announcement."""
    message_id: int
    channel_id: int