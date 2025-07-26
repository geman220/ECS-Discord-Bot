import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import logging
import io
from typing import List, Optional
from common import server_id, has_admin_role

logger = logging.getLogger(__name__)
WEBUI_API_URL = os.getenv("WEBUI_API_URL", "http://localhost:5000/api")

# Channel restriction
PL_NONSENSE_CHANNEL_NAME = "pl-nonsense"

# Role requirements for I-Spy usage
ALLOWED_ROLES = [
    "ECS-FC-PL-CLASSIC",
    "ECS-FC-PL-PREMIER"
]

# Admin/moderator roles
MODERATOR_ROLES = [
    "WG: ECS FC PL Leadership",
    "WG: ECS FC Admin PUB LEAGUE"
]

def has_pl_role(interaction: discord.Interaction) -> bool:
    """Check if user has required pub league role."""
    user_roles = [role.name for role in interaction.user.roles]
    return any(role in user_roles for role in ALLOWED_ROLES)

def has_moderator_role(interaction: discord.Interaction) -> bool:
    """Check if user has moderator role."""
    user_roles = [role.name for role in interaction.user.roles]
    return any(role in user_roles for role in MODERATOR_ROLES)

def is_pl_nonsense_channel(interaction: discord.Interaction) -> bool:
    """Check if command is used in #pl-nonsense channel."""
    return interaction.channel.name == PL_NONSENSE_CHANNEL_NAME

class ISpyCategorySelect(discord.ui.Select):
    """Dropdown for selecting I-Spy venue category."""
    
    def __init__(self, categories: List[dict]):
        options = [
            discord.SelectOption(
                label=cat['display_name'],
                value=cat['key'],
                description=f"Spot someone at: {cat['display_name']}"
            )
            for cat in categories
        ]
        
        super().__init__(
            placeholder="Select venue category...",
            options=options,
            custom_id="ispy_category_select"
        )
    
    async def callback(self, interaction: discord.Interaction):
        # This will be handled by the parent view
        await interaction.response.defer()

class ISpySubmissionView(discord.ui.View):
    """View for I-Spy shot submission with category selection."""
    
    def __init__(self, targets: List[discord.Member], location: str, image_url: str, categories: List[dict]):
        super().__init__(timeout=300)
        self.targets = targets
        self.location = location
        self.image_url = image_url
        self.categories = categories
        self.selected_category = None
        
        # Add category select dropdown
        self.category_select = ISpyCategorySelect(categories)
        self.add_item(self.category_select)
    
    @discord.ui.button(label="Submit Shot", style=discord.ButtonStyle.success, emoji="📸")
    async def submit_shot(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_category:
            # Check if category was selected in dropdown
            for item in self.children:
                if isinstance(item, ISpyCategorySelect) and item.values:
                    self.selected_category = item.values[0]
                    break
            
            if not self.selected_category:
                await interaction.response.send_message(
                    "❌ Please select a venue category first!", 
                    ephemeral=True
                )
                return
        
        # Submit to API
        payload = {
            "targets": [str(target.id) for target in self.targets],
            "category": self.selected_category,
            "location": self.location,
            "image_url": self.image_url
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{WEBUI_API_URL}/ispy/submit",
                    json=payload,
                    headers={"X-Discord-User": str(interaction.user.id)}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # Public success message - make it engaging for the community
                        public_embed = discord.Embed(
                            title="📸 I-Spy Shot Spotted!",
                            color=discord.Color.green(),
                            description=f"**{interaction.user.mention} has Spied {', '.join([target.mention for target in self.targets])} at {self.location}!**"
                        )
                        
                        public_embed.add_field(
                            name="📍 Location & Category",
                            value=f"**{self.location}** ({self.selected_category})",
                            inline=True
                        )
                        
                        public_embed.add_field(
                            name="🏆 Points Earned",
                            value=f"**{data['points_awarded']}** points",
                            inline=True
                        )
                        
                        # Add promotional message to encourage participation
                        public_embed.add_field(
                            name="🎮 Join the Fun!",
                            value="Use `/ispy` when you spot pub leaguers in the wild! Tag them, snap a pic, and earn points!",
                            inline=False
                        )
                        
                        public_embed.set_image(url=self.image_url)
                        public_embed.set_footer(text=f"Shot #{data['shot_id']} • Use /ispy-top to see leaderboards!")
                        
                        # Send public message to channel
                        await interaction.response.edit_message(
                            content=None,
                            embed=public_embed,
                            view=None
                        )
                        
                        # Also send a private confirmation with detailed breakdown
                        try:
                            breakdown = data['breakdown']
                            private_embed = discord.Embed(
                                title="✅ Shot Submitted Successfully!",
                                color=discord.Color.blue(),
                                description="Here's your detailed scoring breakdown:"
                            )
                            
                            private_embed.add_field(
                                name="📊 Points Breakdown",
                                value=f"Base Points: {breakdown['base_points']}\nBonus Points: {breakdown['bonus_points']}\nStreak Bonus: {breakdown['streak_bonus']}\n**Total: {data['points_awarded']} points**",
                                inline=False
                            )
                            
                            await interaction.followup.send(embed=private_embed, ephemeral=True)
                        except:
                            pass  # If private message fails, that's okay
                        
                    else:
                        data = await resp.json()
                        errors = data.get('errors', ['Unknown error'])
                        
                        # Check if it's a cooldown error
                        if any('cooldown' in error.lower() for error in errors):
                            embed = discord.Embed(
                                title="⏰ Target on Cooldown",
                                color=discord.Color.orange(),
                                description="One or more targets are currently on cooldown:"
                            )
                            
                            for i, error in enumerate(errors, 1):
                                if 'cooldown' in error.lower():
                                    # Format cooldown messages more nicely
                                    if '48 hours' in error:
                                        embed.add_field(
                                            name="🌍 Global Cooldown",
                                            value=error.replace('Target', 'This target'),
                                            inline=False
                                        )
                                    elif '14 days' in error:
                                        embed.add_field(
                                            name="📍 Venue Cooldown", 
                                            value=error.replace('Target', 'This target'),
                                            inline=False
                                        )
                                    else:
                                        embed.add_field(
                                            name=f"⏱️ Cooldown {i}",
                                            value=error,
                                            inline=False
                                        )
                            
                            embed.set_footer(text="💡 Try targeting different people or wait for cooldowns to expire")
                        else:
                            # Regular error
                            error_msg = "\n".join(errors)
                            embed = discord.Embed(
                                title="❌ I-Spy Submission Failed",
                                color=discord.Color.red(),
                                description=error_msg
                            )
                        
                        await interaction.response.edit_message(
                            embed=embed,
                            view=None
                        )
                        
            except Exception as e:
                logger.error(f"Error submitting I-Spy shot: {str(e)}")
                await interaction.response.send_message(
                    f"❌ Error connecting to API: {str(e)}", 
                    ephemeral=True
                )
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_submission(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="❌ I-Spy Submission Cancelled",
            color=discord.Color.orange(),
            description="Your shot was not submitted."
        )
        
        await interaction.response.edit_message(
            embed=embed,
            view=None
        )

@app_commands.command(name="ispy", description="Submit an I-Spy shot of fellow pub leaguers")
@app_commands.describe(
    targets="1-3 Discord users you spotted (use @mentions)",
    location="Short description of location (max 40 chars)",
    image="Photo of the targets"
)
async def ispy_submit(
    interaction: discord.Interaction,
    targets: str,
    location: str,
    image: discord.Attachment
):
    """Submit an I-Spy shot with targets, location, and image."""
    
    # Defer the response immediately to avoid timeout
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Check channel restriction
        if not is_pl_nonsense_channel(interaction):
            await interaction.followup.send(
                "❌ I-Spy commands can only be used in #pl-nonsense channel!",
                ephemeral=True
            )
            return
        
        # Check role requirement
        if not has_pl_role(interaction):
            await interaction.followup.send(
                "❌ You need a pub league role (ECS-FC-PL-CLASSIC or ECS-FC-PL-PREMIER) to use I-Spy!",
                ephemeral=True
            )
            return
        
        # Validate image
        if not image.content_type or not image.content_type.startswith('image/'):
            await interaction.followup.send(
                "❌ Please attach a valid image file!",
                ephemeral=True
            )
            return
        
        # Parse targets from mentions
        target_members = []
        words = targets.split()
        
        for word in words:
            if word.startswith('<@') and word.endswith('>'):
                try:
                    user_id = int(word[2:-1].replace('!', ''))
                    member = interaction.guild.get_member(user_id)
                    if member:
                        target_members.append(member)
                except ValueError:
                    continue
        
        if not target_members:
            await interaction.followup.send(
                "❌ Please mention 1-3 valid Discord users as targets!",
                ephemeral=True
            )
            return
        
        if len(target_members) > 3:
            await interaction.followup.send(
                "❌ Maximum 3 targets allowed per shot!",
                ephemeral=True
            )
            return
        
        # Validate location length
        if len(location) > 40:
            await interaction.followup.send(
                "❌ Location description must be 40 characters or less!",
                ephemeral=True
            )
            return
        
        # Get categories from API
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{WEBUI_API_URL}/ispy/categories",
                    headers={"X-Discord-User": str(interaction.user.id)}
                ) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(
                            "❌ Error loading venue categories. Please try again later.",
                            ephemeral=True
                        )
                        return
                    
                    data = await resp.json()
                    categories = data['categories']
                    
            except Exception as e:
                logger.error(f"Error getting categories: {str(e)}")
                await interaction.followup.send(
                    "❌ Error connecting to API. Please try again later.",
                    ephemeral=True
                )
                return
        
        # Create submission view
        view = ISpySubmissionView(target_members, location, image.url, categories)
        
        embed = discord.Embed(
            title="📸 I-Spy Shot Preview",
            color=discord.Color.blue(),
            description=f"**Location:** {location}\n\n⚠️ **This will be posted publicly when submitted!**"
        )
        
        embed.add_field(
            name="🎯 Targets",
            value=", ".join([target.mention for target in target_members]),
            inline=False
        )
        
        embed.add_field(
            name="📋 Next Steps",
            value="1. Select a venue category from the dropdown\n2. Click 'Submit Shot' to post publicly and earn points",
            inline=False
        )
        
        embed.add_field(
            name="📢 Public Features",
            value="• Everyone will see the photo and tags\n• Promotes community engagement\n• Encourages others to play I-Spy",
            inline=False
        )
        
        embed.set_image(url=image.url)
        embed.set_footer(text="This shot will be shared publicly to promote the I-Spy game!")
        
        await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=True
        )
        
    except Exception as e:
        logger.error(f"Error in ispy_submit: {str(e)}")
        try:
            await interaction.followup.send(
                "❌ An unexpected error occurred. Please try again later.",
                ephemeral=True
            )
        except:
            pass  # If followup also fails, there's nothing more we can do

@app_commands.command(name="ispy-top", description="View the I-Spy leaderboard")
@app_commands.describe(limit="Number of top players to show (default: 10, max: 25)")
async def ispy_leaderboard(interaction: discord.Interaction, limit: Optional[int] = 10):
    """Display the current I-Spy leaderboard."""
    
    # Defer the response immediately - public to encourage engagement
    await interaction.response.defer()
    
    # Check channel restriction
    if not is_pl_nonsense_channel(interaction):
        await interaction.followup.send(
            "❌ I-Spy commands can only be used in #pl-nonsense channel!",
            ephemeral=True
        )
        return
    
    # Check role requirement
    if not has_pl_role(interaction):
        await interaction.followup.send(
            "❌ You need a pub league role to view I-Spy stats!",
            ephemeral=True
        )
        return
    
    limit = min(limit, 25)  # Cap at 25
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{WEBUI_API_URL}/ispy/leaderboard?limit={limit}",
                headers={"X-Discord-User": str(interaction.user.id)}
            ) as resp:
                if resp.status != 200:
                    await interaction.followup.send(
                        "❌ Error loading leaderboard. Please try again later.",
                        ephemeral=True
                    )
                    return
                
                data = await resp.json()
                season = data['season']
                leaderboard = data['leaderboard']
                
                if not leaderboard:
                    embed = discord.Embed(
                        title="🏆 I-Spy Leaderboard",
                        color=discord.Color.blue(),
                        description="No shots recorded yet this season!"
                    )
                    await interaction.followup.send(embed=embed)
                    return
                
                embed = discord.Embed(
                    title="🏆 I-Spy Leaderboard",
                    color=discord.Color.gold(),
                    description=f"**Season:** {season['name']}\n\nWho's been spotting the most pub leaguers? 👀"
                )
                
                leaderboard_text = ""
                for entry in leaderboard:
                    rank = entry['rank']
                    discord_id = entry['discord_id']
                    points = entry['total_points']
                    shots = entry['approved_shots']
                    streak = entry['current_streak']
                    
                    # Try to get Discord user
                    try:
                        user = interaction.client.get_user(int(discord_id))
                        display_name = user.display_name if user else f"User {discord_id}"
                    except:
                        display_name = f"User {discord_id}"
                    
                    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "🏅"
                    
                    leaderboard_text += f"{medal} **#{rank}** {display_name}\n"
                    leaderboard_text += f"   📸 {shots} shots • 🏆 {points} pts • 🔥 {streak} streak\n\n"
                
                embed.description += f"\n\n{leaderboard_text}"
                
                # Add promotional footer to encourage participation
                embed.add_field(
                    name="🎮 Want to Join the Fun?",
                    value="Use `/ispy @someone location` with a photo when you spot pub leaguers out and about!\nEarn points, build streaks, and climb the leaderboard! 📈",
                    inline=False
                )
                
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error getting leaderboard: {str(e)}")
            await interaction.followup.send(
                "❌ Error connecting to API. Please try again later.",
                ephemeral=True
            )

@app_commands.command(name="ispy-me", description="View your personal I-Spy statistics")
async def ispy_personal_stats(interaction: discord.Interaction):
    """Display personal I-Spy statistics for the user."""
    
    # Defer the response immediately
    await interaction.response.defer(ephemeral=True)
    
    # Check channel restriction
    if not is_pl_nonsense_channel(interaction):
        await interaction.followup.send(
            "❌ I-Spy commands can only be used in #pl-nonsense channel!",
            ephemeral=True
        )
        return
    
    # Check role requirement
    if not has_pl_role(interaction):
        await interaction.followup.send(
            "❌ You need a pub league role to view I-Spy stats!",
            ephemeral=True
        )
        return
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{WEBUI_API_URL}/ispy/me",
                headers={"X-Discord-User": str(interaction.user.id)}
            ) as resp:
                if resp.status != 200:
                    await interaction.followup.send(
                        "❌ Error loading your stats. Please try again later.",
                        ephemeral=True
                    )
                    return
                
                data = await resp.json()
                season = data['season']
                stats = data['stats']
                
                embed = discord.Embed(
                    title=f"📊 {interaction.user.display_name}'s I-Spy Stats",
                    color=discord.Color.blue(),
                    description=f"**Season:** {season['name']}"
                )
                
                embed.add_field(
                    name="🏆 Points",
                    value=f"**{stats['total_points']}** total",
                    inline=True
                )
                
                embed.add_field(
                    name="📸 Shots",
                    value=f"**{stats['approved_shots']}** approved\n{stats['total_shots']} total",
                    inline=True
                )
                
                embed.add_field(
                    name="🔥 Streak",
                    value=f"**{stats['current_streak']}** current\n{stats['max_streak']} best",
                    inline=True
                )
                
                if stats['disallowed_shots'] > 0:
                    embed.add_field(
                        name="❌ Disallowed",
                        value=f"{stats['disallowed_shots']} shots",
                        inline=True
                    )
                
                embed.add_field(
                    name="🎯 Unique Targets",
                    value=f"{stats['unique_targets']} people",
                    inline=True
                )
                
                if stats['first_shot_at']:
                    embed.set_footer(text=f"First shot: {stats['first_shot_at'][:10]}")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error getting personal stats: {str(e)}")
            await interaction.followup.send(
                "❌ Error connecting to API. Please try again later.",
                ephemeral=True
            )

@app_commands.command(name="ispy-stats", description="View category-specific I-Spy leaderboards")
@app_commands.describe(category="Venue category to view stats for")
async def ispy_category_stats(interaction: discord.Interaction, category: str):
    """Display leaderboard for a specific venue category."""
    
    # Defer the response immediately
    await interaction.response.defer()
    
    # Check channel restriction
    if not is_pl_nonsense_channel(interaction):
        await interaction.followup.send(
            "❌ I-Spy commands can only be used in #pl-nonsense channel!",
            ephemeral=True
        )
        return
    
    # Check role requirement
    if not has_pl_role(interaction):
        await interaction.followup.send(
            "❌ You need a pub league role to view I-Spy stats!",
            ephemeral=True
        )
        return
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{WEBUI_API_URL}/ispy/stats/category/{category}",
                headers={"X-Discord-User": str(interaction.user.id)}
            ) as resp:
                if resp.status == 404:
                    await interaction.followup.send(
                        f"❌ Category '{category}' not found or no data available.",
                        ephemeral=True
                    )
                    return
                elif resp.status != 200:
                    await interaction.followup.send(
                        "❌ Error loading category stats. Please try again later.",
                        ephemeral=True
                    )
                    return
                
                data = await resp.json()
                season = data['season']
                leaderboard = data['leaderboard']
                
                if not leaderboard:
                    embed = discord.Embed(
                        title=f"📊 {category.title()} Category Stats",
                        color=discord.Color.blue(),
                        description="No shots recorded for this category yet!"
                    )
                    await interaction.followup.send(embed=embed)
                    return
                
                category_name = leaderboard[0]['category_name']
                
                embed = discord.Embed(
                    title=f"📊 {category_name} Leaderboard",
                    color=discord.Color.purple(),
                    description=f"**Season:** {season['name']}\n\nTop spotters at {category_name.lower()} venues! 🎯"
                )
                
                leaderboard_text = ""
                for entry in leaderboard:
                    rank = entry['rank']
                    discord_id = entry['discord_id']
                    points = entry['category_points']
                    shots = entry['category_shots']
                    
                    # Try to get Discord user
                    try:
                        user = interaction.client.get_user(int(discord_id))
                        display_name = user.display_name if user else f"User {discord_id}"
                    except:
                        display_name = f"User {discord_id}"
                    
                    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "🏅"
                    
                    leaderboard_text += f"{medal} **#{rank}** {display_name}\n"
                    leaderboard_text += f"   📸 {shots} shots • 🏆 {points} pts\n\n"
                
                embed.description += f"\n\n{leaderboard_text}"
                
                # Add category-specific promotion
                embed.add_field(
                    name="🏃‍♂️ Ready to Hunt?",
                    value=f"Next time you're at a {category_name.lower()}, keep an eye out for fellow pub leaguers!\nUse `/ispy` to tag them and claim your spot on this leaderboard! 📸",
                    inline=False
                )
                
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error getting category stats: {str(e)}")
            await interaction.followup.send(
                "❌ Error connecting to API. Please try again later.",
                ephemeral=True
            )

# Admin commands
@app_commands.command(name="ispy-disallow", description="[ADMIN] Disallow an I-Spy shot")
@app_commands.describe(
    shot_id="ID of the shot to disallow",
    reason="Reason for disallowing the shot",
    penalty="Point penalty to apply (default: 5)"
)
async def ispy_admin_disallow(
    interaction: discord.Interaction,
    shot_id: int,
    reason: str,
    penalty: Optional[int] = 5
):
    """Admin command to disallow a shot."""
    
    # Defer the response immediately
    await interaction.response.defer(ephemeral=True)
    
    # Check moderator role
    if not has_moderator_role(interaction):
        await interaction.followup.send(
            "❌ You don't have permission to use admin I-Spy commands!",
            ephemeral=True
        )
        return
    
    payload = {
        "reason": reason,
        "penalty": penalty
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{WEBUI_API_URL}/ispy/admin/disallow/{shot_id}",
                json=payload,
                headers={"X-Discord-User": str(interaction.user.id)}
            ) as resp:
                if resp.status == 200:
                    embed = discord.Embed(
                        title="✅ Shot Disallowed",
                        color=discord.Color.green(),
                        description=f"Shot ID {shot_id} has been disallowed.\n\n**Reason:** {reason}\n**Penalty:** -{penalty} points"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                elif resp.status == 404:
                    await interaction.followup.send(
                        "❌ Shot not found or already disallowed.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ Error disallowing shot. Please try again later.",
                        ephemeral=True
                    )
                    
        except Exception as e:
            logger.error(f"Error disallowing shot: {str(e)}")
            await interaction.followup.send(
                "❌ Error connecting to API. Please try again later.",
                ephemeral=True
            )

@app_commands.command(name="ispy-recategorize", description="[ADMIN] Move a shot to a different category")
@app_commands.describe(
    shot_id="ID of the shot to recategorize",
    new_category="New category key for the shot"
)
async def ispy_admin_recategorize(
    interaction: discord.Interaction,
    shot_id: int,
    new_category: str
):
    """Admin command to recategorize a shot."""
    
    # Defer the response immediately
    await interaction.response.defer(ephemeral=True)
    
    # Check moderator role
    if not has_moderator_role(interaction):
        await interaction.followup.send(
            "❌ You don't have permission to use admin I-Spy commands!",
            ephemeral=True
        )
        return
    
    payload = {"new_category": new_category}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{WEBUI_API_URL}/ispy/admin/recategorize/{shot_id}",
                json=payload,
                headers={"X-Discord-User": str(interaction.user.id)}
            ) as resp:
                if resp.status == 200:
                    embed = discord.Embed(
                        title="✅ Shot Recategorized",
                        color=discord.Color.green(),
                        description=f"Shot ID {shot_id} moved to category: {new_category}"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                elif resp.status == 404:
                    await interaction.followup.send(
                        "❌ Shot not found.",
                        ephemeral=True
                    )
                elif resp.status == 400:
                    await interaction.followup.send(
                        f"❌ Invalid category: {new_category}",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ Error recategorizing shot. Please try again later.",
                        ephemeral=True
                    )
                    
        except Exception as e:
            logger.error(f"Error recategorizing shot: {str(e)}")
            await interaction.followup.send(
                "❌ Error connecting to API. Please try again later.",
                ephemeral=True
            )

@app_commands.command(name="ispy-jail", description="[ADMIN] Temporarily block a user from I-Spy")
@app_commands.describe(
    user="Discord user to jail",
    hours="Number of hours to block (default: 24)",
    reason="Reason for jailing the user"
)
async def ispy_admin_jail(
    interaction: discord.Interaction,
    user: discord.Member,
    hours: Optional[int] = 24,
    reason: Optional[str] = "No reason provided"
):
    """Admin command to jail a user."""
    
    # Defer the response immediately
    await interaction.response.defer(ephemeral=True)
    
    # Check moderator role
    if not has_moderator_role(interaction):
        await interaction.followup.send(
            "❌ You don't have permission to use admin I-Spy commands!",
            ephemeral=True
        )
        return
    
    payload = {
        "discord_id": str(user.id),
        "hours": hours,
        "reason": reason
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{WEBUI_API_URL}/ispy/admin/jail",
                json=payload,
                headers={"X-Discord-User": str(interaction.user.id)}
            ) as resp:
                if resp.status == 200:
                    embed = discord.Embed(
                        title="🔒 User Jailed",
                        color=discord.Color.orange(),
                        description=f"{user.mention} has been blocked from I-Spy for {hours} hours.\n\n**Reason:** {reason}"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(
                        "❌ Error jailing user. Please try again later.",
                        ephemeral=True
                    )
                    
        except Exception as e:
            logger.error(f"Error jailing user: {str(e)}")
            await interaction.followup.send(
                "❌ Error connecting to API. Please try again later.",
                ephemeral=True
            )

@app_commands.command(name="ispy-cooldowns", description="View active cooldowns for a user")
@app_commands.describe(user="Discord user to check cooldowns for")
async def ispy_check_cooldowns(interaction: discord.Interaction, user: discord.Member):
    """Check active cooldowns for a user."""
    
    # Defer the response immediately
    await interaction.response.defer(ephemeral=True)
    
    # Check channel restriction
    if not is_pl_nonsense_channel(interaction):
        await interaction.followup.send(
            "❌ I-Spy commands can only be used in #pl-nonsense channel!",
            ephemeral=True
        )
        return
    
    # Check role requirement (allow both regular users and moderators)
    if not (has_pl_role(interaction) or has_moderator_role(interaction)):
        await interaction.followup.send(
            "❌ You need a pub league role to check I-Spy cooldowns!",
            ephemeral=True
        )
        return
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{WEBUI_API_URL}/ispy/cooldowns/{user.id}",
                headers={"X-Discord-User": str(interaction.user.id)}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    cooldowns = data.get('cooldowns', [])
                    
                    if not cooldowns:
                        embed = discord.Embed(
                            title="✅ No Active Cooldowns",
                            color=discord.Color.green(),
                            description=f"{user.mention} has no active cooldowns and can be targeted!"
                        )
                    else:
                        embed = discord.Embed(
                            title="⏰ Active Cooldowns",
                            color=discord.Color.orange(),
                            description=f"Current cooldowns for {user.mention}:"
                        )
                        
                        for cooldown in cooldowns:
                            cooldown_type = "🌍 Global" if cooldown['type'] == 'global' else f"📍 {cooldown['category_name']}"
                            embed.add_field(
                                name=cooldown_type,
                                value=f"Expires: {cooldown['expires_at'][:19].replace('T', ' ')}",
                                inline=False
                            )
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
                elif resp.status == 404:
                    await interaction.followup.send(
                        f"❌ No cooldown data found for {user.mention}.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ Error loading cooldown data. Please try again later.",
                        ephemeral=True
                    )
                    
        except Exception as e:
            logger.error(f"Error checking cooldowns: {str(e)}")
            await interaction.followup.send(
                "❌ Error connecting to API. Please try again later.",
                ephemeral=True
            )


@app_commands.command(name="ispy-reset-cooldowns", description="[ADMIN] Reset all cooldowns for a user")
@app_commands.describe(
    user="Discord user to reset cooldowns for",
    reason="Reason for resetting cooldowns"
)
async def ispy_admin_reset_cooldowns(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: Optional[str] = "No reason provided"
):
    """Admin command to reset cooldowns for a user."""
    
    # Defer the response immediately
    await interaction.response.defer(ephemeral=True)
    
    # Check moderator role
    if not has_moderator_role(interaction):
        await interaction.followup.send(
            "❌ You don't have permission to use admin I-Spy commands!",
            ephemeral=True
        )
        return
    
    payload = {
        "target_discord_id": str(user.id),
        "reason": reason
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{WEBUI_API_URL}/ispy/admin/reset-cooldowns",
                json=payload,
                headers={"X-Discord-User": str(interaction.user.id)}
            ) as resp:
                if resp.status == 200:
                    embed = discord.Embed(
                        title="✅ Cooldowns Reset",
                        color=discord.Color.green(),
                        description=f"All cooldowns for {user.mention} have been reset.\n\n**Reason:** {reason}"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(
                        "❌ Error resetting cooldowns. Please try again later.",
                        ephemeral=True
                    )
                    
        except Exception as e:
            logger.error(f"Error resetting cooldowns: {str(e)}")
            await interaction.followup.send(
                "❌ Error connecting to API. Please try again later.",
                ephemeral=True
            )


async def setup(bot):
    """Setup function for the cog."""
    bot.tree.add_command(ispy_submit, guild=discord.Object(id=server_id))
    bot.tree.add_command(ispy_leaderboard, guild=discord.Object(id=server_id))
    bot.tree.add_command(ispy_personal_stats, guild=discord.Object(id=server_id))
    bot.tree.add_command(ispy_category_stats, guild=discord.Object(id=server_id))
    bot.tree.add_command(ispy_check_cooldowns, guild=discord.Object(id=server_id))
    bot.tree.add_command(ispy_admin_disallow, guild=discord.Object(id=server_id))
    bot.tree.add_command(ispy_admin_recategorize, guild=discord.Object(id=server_id))
    bot.tree.add_command(ispy_admin_jail, guild=discord.Object(id=server_id))
    bot.tree.add_command(ispy_admin_reset_cooldowns, guild=discord.Object(id=server_id))