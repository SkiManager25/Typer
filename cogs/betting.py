import os

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from odds import calculate_odds
from currency import format_money

_raw_ids = os.getenv("MATCH_ADMIN_IDS", "")
AUTHORIZED_USER_IDS = {int(x.strip()) for x in _raw_ids.split(",") if x.strip().isdigit()}


def is_authorized():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not AUTHORIZED_USER_IDS:
            return interaction.user.guild_permissions.administrator
        return interaction.user.id in AUTHORIZED_USER_IDS
    return app_commands.check(predicate)


class Betting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "⛔ Nie masz uprawnień do tej komendy — może jej użyć tylko wyznaczona osoba.",
                ephemeral=True,
            )
        else:
            raise error

    @app_commands.command(name="dodajmecz", description="[Admin] Dodaj mecz do obstawiania")
    @app_commands.describe(
        gracz_a="Imię i nazwisko gracza A",
        gracz_b="Imię i nazwisko gracza B",
        kurs_a="Kurs gracza A — podaj ręcznie jeśli chcesz ustawić kurs sam",
        kurs_b="Kurs gracza B — podaj ręcznie jeśli chcesz ustawić kurs sam",
        ranking_a="Opcjonalnie: ranking ATP/WTA gracza A (potrzebny tylko jeśli NIE podajesz kursów ręcznie)",
        ranking_b="Opcjonalnie: ranking ATP/WTA gracza B (potrzebny tylko jeśli NIE podajesz kursów ręcznie)",
    )
    @is_authorized()
    async def dodajmecz(self, interaction: discord.Interaction, gracz_a: str, gracz_b: str,
                         kurs_a: float = None, kurs_b: float = None,
                         ranking_a: int = None, ranking_b: int = None):
        if kurs_a is not None and kurs_b is not None:
            if kurs_a < 1.01 or kurs_b < 1.01:
                await interaction.response.send_message("Kursy muszą być co najmniej 1.01.", ephemeral=True)
                return
            odds_a, odds_b = round(kurs_a, 2), round(kurs_b, 2)
            recznie = True
        elif kurs_a is not None or kurs_b is not None:
            await interaction.response.send_message(
                "Jeśli podajesz kurs ręcznie, musisz podać OBA kursy (kurs_a i kurs_b) naraz.",
                ephemeral=True,
            )
            return
        elif ranking_a is not None and ranking_b is not None:
            odds_a, odds_b = calculate_odds(ranking_a, ranking_b)
            recznie = False
        else:
            await interaction.response.send_message(
                "Podaj albo oba kursy (kurs_a + kurs_b), albo oba rankingi (ranking_a + ranking_b), "
                "żeby kurs policzył się automatycznie.",
                ephemeral=True,
            )
            return

        match_id = await db.create_match(
            gracz_a, ranking_a or 0, gracz_b, ranking_b or 0, odds_a, odds_b
        )

        rank_line_a = f" (ranking {ranking_a})" if ranking_a else ""
        rank_line_b = f" (ranking {ranking_b})" if ranking_b else ""
        source_note = "🎯 kursy ustawione ręcznie" if recznie else "📊 kursy liczone automatycznie z rankingu"

        embed = discord.Embed(
            title=f"🎾  Mecz #{match_id}",
            description="Nowy mecz otwarty do obstawiania!",
            color=discord.Color.from_rgb(46, 204, 113),
        )
        embed.add_field(name=f"🅰️  {gracz_a}{rank_line_a}", value=f"kurs **{odds_a}**", inline=True)
        embed.add_field(name=f"🅱️  {gracz_b}{rank_line_b}", value=f"kurs **{odds_b}**", inline=True)
        embed.add_field(name="\u200b", value=f"_{source_note}_", inline=False)
        embed.add_field(
            name="Jak obstawić",
            value=(
                f"Pojedynczo: `/typuj mecz:{match_id} gracz:{gracz_a} kwota:100`\n"
                f"Do kuponu: `/kupon_dodaj mecz:{match_id} gracz:{gracz_a}`"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mecze", description="Lista meczów otwartych do obstawiania")
    async def mecze(self, interaction: discord.Interaction):
        matches = await db.get_open_matches()
        if not matches:
            await interaction.response.send_message("📋 Brak otwartych meczów w tej chwili.")
            return

        embed = discord.Embed(
            title="📋  Otwarte mecze",
            description=f"Aktualnie **{len(matches)}** mecz(e/ów) czeka na typy.",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        for m in matches:
            embed.add_field(
                name=f"Mecz #{m['id']}",
                value=f"🎾 **{m['player_a']}** @{m['odds_a']}  vs  **{m['player_b']}** @{m['odds_b']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

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
                f"Za mało kasy. Masz {format_money(balance)}, chcesz postawić {format_money(kwota)}.",
                ephemeral=True,
            )
            return

        await db.change_balance(interaction.user.id, -kwota)
        await db.place_bet(mecz, interaction.user.id, gracz, kwota, picked_odds)

        potential = round(kwota * picked_odds)
        embed = discord.Embed(
            title="✅  Zakład przyjęty",
            color=discord.Color.from_rgb(46, 204, 113),
        )
        embed.add_field(name="Typ", value=f"**{gracz}** @ {picked_odds}", inline=True)
        embed.add_field(name="Stawka", value=format_money(kwota), inline=True)
        embed.add_field(name="Możliwa wygrana", value=f"**{format_money(potential)}**", inline=True)
        await interaction.response.send_message(embed=embed)

    # ---------- ADMIN: rozstrzyganie ----------

    @app_commands.command(name="rozstrzygnij", description="[Admin] Rozstrzygnij mecz i wypłać wygrane")
    @app_commands.describe(mecz="ID meczu", zwyciezca="Imię zwycięzcy (dokładnie jak w /mecze)")
    @is_authorized()
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
        results, slip_results = await db.settle_match(mecz, zwyciezca)

        wins = sum(1 for r in results if r[1])
        embed = discord.Embed(
            title=f"🏁  Mecz #{mecz} rozstrzygnięty",
            description=f"🏆 Zwycięzca: **{zwyciezca}**",
            color=discord.Color.from_rgb(241, 196, 15),
        )
        embed.add_field(
            name="Pojedyncze zakłady",
            value=f"Wypłacono {wins} z {len(results)}",
            inline=True,
        )
        if slip_results:
            slip_wins = sum(1 for r in slip_results if r[2])
            embed.add_field(
                name="Kupony (AKO)",
                value=f"Rozliczono {slip_wins} wygranych z {len(slip_results)} w tym kroku",
                inline=True,
            )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Betting(bot))
