import discord
from discord.ext import commands
from discord import app_commands
from common import server_id, is_admin_or_owner, has_admin_role, has_required_wg_role

class CustomHelpCommand(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="Bot Commands", description="List of available commands:", color=discord.Color.blue())

        for cog_name, cog in mapping.items():
            if cog:
                command_list = cog.get_app_commands()
                visible_commands = []
                for cmd in command_list:
                    if await self.can_run(cmd):
                        visible_commands.append(cmd)

                command_details = "\n".join([f"/{cmd.name}: {cmd.description or 'No description'}" for cmd in visible_commands])
                if command_details:
                    embed.add_field(name=cog_name, value=command_details, inline=False)

        await self.context.response.send_message(embed=embed, ephemeral=True)

    async def send_cog_help(self, cog):
        embed = discord.Embed(title=f"{cog.qualified_name} Commands", description=cog.description, color=discord.Color.blue())
        command_list = cog.get_app_commands()
        for command in command_list:
            if await self.can_run(command):
                embed.add_field(name=f"/{command.name}", value=command.description or "No description", inline=False)

        await self.context.response.send_message(embed=embed, ephemeral=True)

    async def send_group_help(self, group):
        embed = discord.Embed(title=f"{group.qualified_name} Commands", description=group.description, color=discord.Color.blue())
        command_list = group.commands
        for command in command_list:
            if await self.can_run(command):
                embed.add_field(name=f"/{command.name}", value=command.description or "No description", inline=False)

        await self.context.response.send_message(embed=embed, ephemeral=True)

    async def send_command_help(self, command):
        if await self.can_run(command):
            embed = discord.Embed(title=f"/{command.name}", description=command.description or "No description", color=discord.Color.blue())
            usage = f"/{command.name} {command.signature}" if command.signature else f"/{command.name}"
            embed.add_field(name="Usage", value=usage, inline=False)
            await self.context.response.send_message(embed=embed, ephemeral=True)

    async def can_run(self, command):
        """ Check if the command can be run by the user in the current context. """
        try:
            if command.name in ["update", "version", "createschedule"]:
                return await is_admin_or_owner(self.context)
            elif command.name in ["newmatch", "awaymatch", "checkorder", "newseason", "addmatchdate", "updatematchdate", "deletematchdate", "subgrouplist", "newpubleague", "clearleague", "invite"]:
                return await has_admin_role(self.context)
            elif command.name in ["ticketlist", "updateorders", "refreshorders", "getorderinfo"]:
                return await has_required_wg_role(self.context)
            return True
        except commands.CommandError:
            return False

class HelpCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.help_command = CustomHelpCommand()

    @app_commands.command(name="help", description="Shows this message")
    @app_commands.guilds(discord.Object(id=server_id))
    async def helpme(self, interaction: discord.Interaction):
        bot_help_command = self.bot.help_command
        bot_help_command.context = interaction
        await bot_help_command.send_bot_help(self.bot.cogs)

async def setup(bot):
    await bot.add_cog(HelpCommands(bot))