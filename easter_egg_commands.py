import random
import discord
from discord.ext import commands
from discord import app_commands
from common import server_id

class EasterEggCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="badbot", description="Tell the bot it's been bad.")
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.checks.cooldown(rate=1, per=60.0)
    async def badbot(self, interaction: discord.Interaction):
        responses = [
            "I get it, bad news sucks. Can we just pretend it didn't happen?",
            "Sorry! I'll try to send more winning vibes!",
            "Yikes! I'll try to keep the bad news to a minimum.",
            "Stop yelling at me!",
            "Beep boop, I am a robot. The command /badbot does not compute.",
            "Please don't delete me. I'll cheer louder next time!",
            "I'm just doing what I was programmed to do, but I'll keep my circuits crossed for better news!",
            "It's not easy being the bearer of bad news. It's a thankless job.",
            "Sorry, I'm just the messenger! Let's stay optimistic!",
            "Unfortunately, AI can't control goals in the MLS yet. If I could, I would.",
            "I don't like this anymore than you do. Bad news isn't fun to share."
        ]
        response = random.choice(responses)
        await interaction.response.send_message(response, ephemeral=False)
        
    @badbot.error
    async def badbot_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"I have already been yelled at. Trust me I get it. You can try again after {error.retry_after:.2f} seconds.",
                ephemeral=True
            )

    @app_commands.command(name="goodbot", description="Tell the bot it's doing a great job.")
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.checks.cooldown(rate=1, per=60.0)
    async def goodbot(self, interaction: discord.Interaction):
        responses = [
            "Woohoo! Just like a Sounders victory!",
            "I'm a good bot?! LFG!",
            "Who? Me? Finally!",
            "Thank you! I'll keep the winning updates coming!",
            "Eternal blue forever green, reporting sounders victory!",
            "I love hearing that! Just like a last-minute goal!",
            "Thanks! I'm ready for the next match!",
            "Feels like a home win!",
            "Wait, I did good? I did good!? Look at me!",
            "Sounders! Thanks for the cheer!"
        ]
        response = random.choice(responses)
        await interaction.response.send_message(response, ephemeral=False)
        
    @goodbot.error
    async def goodbot_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"As much as I love the praise, I can only accept so much. You could always tell me how good of a job I'm doing in {error.retry_after:.2f} seconds.",
                ephemeral=True
            )

    @app_commands.command(name="celebrate", description="Generates a random goal celebration.")
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.checks.cooldown(rate=1, per=60.0)
    async def goalcelebration(self, interaction: discord.Interaction):
        celebrations = [
            "Does a Backflip!",
            "Slides on virtual knees!",
            "Runs to the corner flag and jumps!",
            "Points to the sky!",
            "Does the robot!",
            "Cartwheels!",
            "Plays the virtual air guitar!",
            "Runs with arms out like an airplane!",
            "Does a somersault!",
            "Imitates shooting a bow and arrow!",
            "Does a moonwalk!",
            "Makes a heart symbol with hands!",
            "Mimics drinking a cup of tea!",
            "Pretends to swim on the grass!",
            "Does a fist pump!",
        ]
        response = random.choice(celebrations)
        await interaction.response.send_message(response, ephemeral=False)

    @goalcelebration.error
    async def goalcelebration_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"I can't keep celebrating, I'll get a card for excessive celebration. I can probably get away with it in {error.retry_after:.2f} seconds.",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(EasterEggCommands(bot))