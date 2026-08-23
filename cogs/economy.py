import discord
from discord import app_commands
from discord.ext import commands

import database as db


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="saldo", description="Sprawdź swoje saldo")
    async def saldo(self, interaction: discord.Interaction):
        balance = await db.get_or_create_user(interaction.user.id, str(interaction.user))
        await interaction.response.send_message(
            f"💰 Twoje saldo: **${balance:,}**"
        )

    @app_commands.command(name="ranking_graczy", description="Ranking najbogatszych typerów")
    async def ranking_graczy(self, interaction: discord.Interaction):
        rows = await db.get_leaderboard(10)
        if not rows:
            await interaction.response.send_message("Brak jeszcze żadnych kont.")
            return

        lines = []
        for i, row in enumerate(rows, start=1):
            lines.append(f"{i}. {row['username']} — ${row['balance']:,}")

        text = "```\n" + "\n".join(lines) + "\n```"
        await interaction.response.send_message(f"🏆 **Ranking typerów**\n{text}")

    @app_commands.command(name="moje_zaklady", description="Historia Twoich ostatnich zakładów")
    async def moje_zaklady(self, interaction: discord.Interaction):
        bets = await db.get_user_bets(interaction.user.id)
        if not bets:
            await interaction.response.send_message("Nie masz jeszcze żadnych zakładów.")
            return

        lines = []
        for b in bets:
            if b["status"] != "settled":
                status = "⏳ w toku"
            elif b["player_choice"] == b["winner"]:
                status = f"✅ wygrana (${int(round(b['amount'] * b['odds'])):,})"
            else:
                status = "❌ przegrana"
            lines.append(
                f"#{b['match_id']} {b['player_a']} vs {b['player_b']} — "
                f"typ: {b['player_choice']} @ {b['odds']} — ${b['amount']:,} — {status}"
            )

        text = "```\n" + "\n".join(lines) + "\n```"
        await interaction.response.send_message(text)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
