import discord
from discord import app_commands
from discord.ext import commands

import database as db
from currency import format_money


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="saldo", description="Sprawdź swoje saldo")
    async def saldo(self, interaction: discord.Interaction):
        balance = await db.get_or_create_user(interaction.user.id, str(interaction.user))
        embed = discord.Embed(
            title="💰  Twoje saldo",
            description=f"# {format_money(balance)}",
            color=discord.Color.from_rgb(241, 196, 15),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ranking_graczy", description="Ranking najbogatszych typerów")
    async def ranking_graczy(self, interaction: discord.Interaction):
        rows = await db.get_leaderboard(10)
        if not rows:
            await interaction.response.send_message("Brak jeszcze żadnych kont.")
            return

        medale = ["🥇", "🥈", "🥉"]
        embed = discord.Embed(
            title="🏆  Ranking typerów",
            color=discord.Color.from_rgb(241, 196, 15),
        )
        lines = []
        for i, row in enumerate(rows, start=1):
            prefix = medale[i - 1] if i <= 3 else f"`{i}.`"
            lines.append(f"{prefix}  **{row['username']}** — {format_money(row['balance'])}")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="moje_zaklady", description="Historia Twoich ostatnich zakładów")
    async def moje_zaklady(self, interaction: discord.Interaction):
        bets = await db.get_user_bets(interaction.user.id)
        if not bets:
            await interaction.response.send_message("Nie masz jeszcze żadnych zakładów.")
            return

        embed = discord.Embed(
            title="📜  Historia zakładów",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        for b in bets:
            if b["status"] != "settled":
                status = "⏳ w toku"
            elif b["player_choice"] == b["winner"]:
                status = f"✅ wygrana ({format_money(int(round(b['amount'] * b['odds'])))})"
            else:
                status = "❌ przegrana"
            embed.add_field(
                name=f"#{b['match_id']} {b['player_a']} vs {b['player_b']}",
                value=f"typ: **{b['player_choice']}** @ {b['odds']} — {format_money(b['amount'])} — {status}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
