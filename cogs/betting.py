import discord
from discord import app_commands
from discord.ext import commands

import database as db
from odds import calculate_odds


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)


class Betting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- ADMIN: dodawanie meczu ----------

    @app_commands.command(name="dodajmecz", description="[Admin] Dodaj mecz do obstawiania")
    @app_commands.describe(
        gracz_a="Imię i nazwisko gracza A",
        ranking_a="Aktualny ranking ATP/WTA gracza A (liczba)",
        gracz_b="Imię i nazwisko gracza B",
        ranking_b="Aktualny ranking ATP/WTA gracza B (liczba)",
    )
    @is_admin()
    async def dodajmecz(self, interaction: discord.Interaction, gracz_a: str, ranking_a: int,
                         gracz_b: str, ranking_b: int):
        odds_a, odds_b = calculate_odds(ranking_a, ranking_b)
        match_id = await db.create_match(gracz_a, ranking_a, gracz_b, ranking_b, odds_a, odds_b)

        embed = discord.Embed(
            title=f"🎾 Mecz #{match_id} otwarty do obstawiania",
            description=(
                f"**{gracz_a}** (ranking {ranking_a}) — kurs **{odds_a}**\n"
                f"**{gracz_b}** (ranking {ranking_b}) — kurs **{odds_b}**\n\n"
                f"Obstaw: `/typuj mecz:{match_id} gracz:{gracz_a} kwota:100`"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mecze", description="Lista meczów otwartych do obstawiania")
    async def mecze(self, interaction: discord.Interaction):
        matches = await db.get_open_matches()
        if not matches:
            await interaction.response.send_message("Brak otwartych meczów.")
            return

        lines = []
        for m in matches:
            lines.append(
                f"#{m['id']}: {m['player_a']} (@{m['odds_a']}) vs "
                f"{m['player_b']} (@{m['odds_b']})"
            )
        text = "```\n" + "\n".join(lines) + "\n```"
        await interaction.response.send_message(f"📋 **Otwarte mecze**\n{text}")

    # ---------- USER: obstawianie ----------

    @app_commands.command(name="typuj", description="Postaw zakład na mecz")
    @app_commands.describe(
        mecz="ID meczu (zobacz /mecze)",
        gracz="Imię gracza, na którego stawiasz (dokładnie jak w /mecze)",
        kwota="Ile punktów stawiasz",
    )
    async def typuj(self, interaction: discord.Interaction, mecz: int, gracz: str, kwota: int):
        if kwota <= 0:
            await interaction.response.send_message("Kwota musi być dodatnia.", ephemeral=True)
            return

        match = await db.get_match(mecz)
        if match is None or match["status"] != "open":
            await interaction.response.send_message("Ten mecz nie jest otwarty do obstawiania.", ephemeral=True)
            return

        if gracz == match["player_a"]:
            picked_odds = match["odds_a"]
        elif gracz == match["player_b"]:
            picked_odds = match["odds_b"]
        else:
            await interaction.response.send_message(
                f"Nie ma takiego gracza w tym meczu. Wybierz: {match['player_a']} lub {match['player_b']}",
                ephemeral=True,
            )
            return

        balance = await db.get_or_create_user(interaction.user.id, str(interaction.user))
        if balance < kwota:
            await interaction.response.send_message(
                f"Za mało punktów. Masz {balance}, chcesz postawić {kwota}.", ephemeral=True
            )
            return

        await db.change_balance(interaction.user.id, -kwota)
        await db.place_bet(mecz, interaction.user.id, gracz, kwota, picked_odds)

        potential = round(kwota * picked_odds)
        await interaction.response.send_message(
            f"✅ Postawiłeś **{kwota}** pkt na **{gracz}** @ {picked_odds}. "
            f"Możliwa wygrana: **{potential}** pkt."
        )

    # ---------- ADMIN: rozstrzyganie ----------

    @app_commands.command(name="rozstrzygnij", description="[Admin] Rozstrzygnij mecz i wypłać wygrane")
    @app_commands.describe(mecz="ID meczu", zwyciezca="Imię zwycięzcy (dokładnie jak w /mecze)")
    @is_admin()
    async def rozstrzygnij(self, interaction: discord.Interaction, mecz: int, zwyciezca: str):
        match = await db.get_match(mecz)
        if match is None:
            await interaction.response.send_message("Nie ma meczu o takim ID.", ephemeral=True)
            return
        if zwyciezca not in (match["player_a"], match["player_b"]):
            await interaction.response.send_message(
                f"Zwycięzca musi być: {match['player_a']} lub {match['player_b']}", ephemeral=True
            )
            return

        await db.close_match(mecz)
        results = await db.settle_match(mecz, zwyciezca)

        wins = sum(1 for r in results if r[1])
        await interaction.response.send_message(
            f"🏁 Mecz #{mecz} rozstrzygnięty — zwycięzca: **{zwyciezca}**\n"
            f"Wypłacono wygrane {wins} z {len(results)} zakładów."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Betting(bot))
