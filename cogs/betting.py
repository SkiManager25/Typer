import os
import aiohttp

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from odds import calculate_odds, calculate_score_markets
from currency import format_money

# ID Discorda osob uprawnionych do dodawania/rozstrzygania meczy.
# Ustawiane zmienna srodowiskowa MATCH_ADMIN_IDS, oddzielone przecinkami, np:
# MATCH_ADMIN_IDS=123456789012345678,987654321098765432
_raw_ids = os.getenv("MATCH_ADMIN_IDS", "")
AUTHORIZED_USER_IDS = {int(x.strip()) for x in _raw_ids.split(",") if x.strip().isdigit()}

# Opcjonalny kanal, na ktorym mozna dodawac mecze (ID kanalu Discorda).
# Ustawiane zmienna srodowiskowa BET_CHANNEL_ID. Jesli pusta - brak ograniczenia.
_raw_channel = os.getenv("BET_CHANNEL_ID", "").strip()
BET_CHANNEL_ID = int(_raw_channel) if _raw_channel.isdigit() else None

# Opcjonalny maksymalny zaklad (pojedynczy i kupon). Ustawiane zmienna MAX_BET.
_raw_max_bet = os.getenv("MAX_BET", "").strip()
MAX_BET = int(_raw_max_bet) if _raw_max_bet.isdigit() else None


class WrongChannelError(app_commands.CheckFailure):
    pass


def is_authorized():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not AUTHORIZED_USER_IDS:
            # jesli nikt nie zostal wskazany, awaryjnie zostaje wymog Administratora
            return interaction.user.guild_permissions.administrator
        return interaction.user.id in AUTHORIZED_USER_IDS
    return app_commands.check(predicate)


def is_correct_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if BET_CHANNEL_ID is None:
            return True
        if interaction.channel_id == BET_CHANNEL_ID:
            return True
        raise WrongChannelError()
    return app_commands.check(predicate)


def check_max_bet(kwota: int) -> str | None:
    """Zwraca komunikat błędu jeśli kwota przekracza limit, inaczej None."""
    if MAX_BET is not None and kwota > MAX_BET:
        return f"Maksymalna dopuszczalna stawka to {format_money(MAX_BET)}."
    return None


class Betting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, WrongChannelError):
            channel_mention = f"<#{BET_CHANNEL_ID}>" if BET_CHANNEL_ID else "wyznaczonym kanale"
            await interaction.response.send_message(
                f"📍 Ta komenda działa tylko na kanale {channel_mention}.",
                ephemeral=True,
            )
        elif isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "⛔ Nie masz uprawnień do tej komendy — może jej użyć tylko wyznaczona osoba.",
                ephemeral=True,
            )
        else:
            raise error

    # ---------- ADMIN: dodawanie meczu ----------

    @app_commands.command(name="pobierz_betclic", description="[Admin] Pobierz mecze tenisa z Betclic i dodaj automatycznie")
    @app_commands.describe(limit="Ile meczów max pobrać (domyślnie 10)")
    @is_authorized()
    @is_correct_channel()
    async def pobierz_betclic(self, interaction: discord.Interaction, limit: int = 10):
        await interaction.response.defer()

        url = "https://api.betclic.com/v2/sports/2/events"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("❌ Błąd połączenia z API Betclic.")
                        return
                    data = await resp.json()
        except Exception as e:
            await interaction.followup.send(f"❌ Wystąpił błąd: {e}")
            return

        dodane = 0
        pominiete = 0

        for event in data:
            if dodane >= limit:
                break

            grouped = event.get('grouped_markets', [])
            if not grouped:
                continue

            markets = grouped[0].get('markets', [])
            if not markets:
                continue

            selections = markets[0].get('selections', [])
            if len(selections) != 2:
                continue

            gracz_a = selections[0].get('name')
            kurs_a = float(selections[0].get('odds', 0))
            gracz_b = selections[1].get('name')
            kurs_b = float(selections[1].get('odds', 0))

            if not gracz_a or not gracz_b or kurs_a < 1.01 or kurs_b < 1.01:
                continue

            existing = await db.find_open_match_by_players(gracz_a, gracz_b)
            if existing is not None:
                pominiete += 1
                continue

            await db.create_match(gracz_a, 0, gracz_b, 0, round(kurs_a, 2), round(kurs_b, 2))
            dodane += 1

        embed = discord.Embed(
            title="🤖 Betclic — Pobieranie meczów",
            description=f"✅ Dodano nowych meczów: **{dodane}**\nℹ️ Pominięto (duplikaty): **{pominiete}**",
            color=discord.Color.from_rgb(46, 204, 113)
        )
        embed.set_footer(text="Mecze są gotowe do obstawiania w /mecze")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="dodajmecz", description="[Admin] Dodaj mecz do obstawiania")
    @app_commands.describe(
        gracz_a="Imię i nazwisko gracza A",
        gracz_b="Imię i nazwisko gracza B",
        kurs_a="Kurs gracza A — podaj ręcznie jeśli chcesz ustawić kurs sam",
        kurs_b="Kurs gracza B — podaj ręcznie jeśli chcesz ustawić kurs sam",
        ranking_a="Opcjonalnie: ranking ATP/WTA gracza A (potrzebny tylko jeśli NIE podajesz kursów ręcznie)",
        ranking_b="Opcjonalnie: ranking ATP/WTA gracza B (potrzebny tylko jeśli NIE podajesz kursów ręcznie)",
        format_setow="Opcjonalnie: 3 lub 5 - otwiera dodatkowo zakłady na dokładny wynik setowy",
    )
    @is_authorized()
    @is_correct_channel()
    async def dodajmecz(self, interaction: discord.Interaction, gracz_a: str, gracz_b: str,
                         kurs_a: float = None, kurs_b: float = None,
                         ranking_a: int = None, ranking_b: int = None,
                         format_setow: int = None):
        if format_setow is not None and format_setow not in (3, 5):
            await interaction.response.send_message("format_setow musi być 3 albo 5.", ephemeral=True)
            return

        existing = await db.find_open_match_by_players(gracz_a, gracz_b)
        if existing is not None:
            already_has_scores = bool(existing["best_of"])
            if format_setow is not None and not already_has_scores:
                await db.set_match_best_of(existing["id"], format_setow)
                markets = calculate_score_markets(
                    existing["odds_a"], existing["odds_b"], existing["player_a"], existing["player_b"], format_setow
                )
                await db.create_score_markets(existing["id"], markets)
                dopisek = "\n\n➕ Dołożono zakłady na wynik setowy do tego meczu."
            elif format_setow is not None and already_has_scores:
                dopisek = "\n\n_Ten mecz już ma zakłady na wynik setowy._"
            else:
                dopisek = ""

            embed = discord.Embed(
                title=f"ℹ️  Ten mecz już istnieje — Mecz #{existing['id']}",
                description=(
                    f"**{existing['player_a']}** @ {existing['odds_a']}  vs  "
                    f"**{existing['player_b']}** @ {existing['odds_b']}\n"
                    f"Nie tworzę duplikatu — używaj tego meczu.{dopisek}"
                ),
                color=discord.Color.from_rgb(52, 152, 219),
            )
            await interaction.response.send_message(embed=embed)
            return

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

        if format_setow is not None:
            await db.set_match_best_of(match_id, format_setow)
            markets = calculate_score_markets(odds_a, odds_b, gracz_a, gracz_b, format_setow)
            await db.create_score_markets(match_id, markets)

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

        obstaw_value = (
            f"Pojedynczo: `/typuj mecz:{match_id} gracz:{gracz_a} kwota:100`\n"
            f"Do kuponu: `/kupon_dodaj mecz:{match_id} gracz:{gracz_a}`"
        )
        if format_setow is not None:
            obstaw_value += f"\nNa wynik setowy: `/typy_setowe mecz:{match_id}`"
        embed.add_field(name="Jak obstawić", value=obstaw_value, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="kurs_setowy", description="[Admin] Ustaw ręcznie kurs na konkretny wynik setowy")
    @app_commands.describe(
        mecz="ID meczu (zobacz /mecze)",
        gracz="Imię gracza (dokładnie jak w /mecze)",
        wynik="Wynik setowy, np. 2:0, 2:1, 3:0, 3:1, 3:2",
        kurs="Kurs dla tej opcji",
    )
    @is_authorized()
    async def kurs_setowy(self, interaction: discord.Interaction, mecz: int, gracz: str, wynik: str, kurs: float):
        if kurs < 1.01:
            await interaction.response.send_message("Kurs musi być co najmniej 1.01.", ephemeral=True)
            return

        match = await db.get_match(mecz)
        if match is None:
            await interaction.response.send_message("Nie ma meczu o takim ID.", ephemeral=True)
            return
        if gracz not in (match["player_a"], match["player_b"]):
            await interaction.response.send_message(
                f"Nie ma takiego gracza w tym meczu. Wybierz: {match['player_a']} lub {match['player_b']}",
                ephemeral=True,
            )
            return

        label = f"{gracz} {wynik}"
        existing_odds = await db.get_score_market_odds(mecz, label)
        await db.upsert_score_market(mecz, label, round(kurs, 2))

        if match["best_of"] is None:
            await db.set_match_best_of(mecz, -1)

        akcja = "Zaktualizowano" if existing_odds is not None else "Dodano"
        embed = discord.Embed(
            title=f"🎯  {akcja} kurs setowy",
            description=f"**{label}** @ **{round(kurs, 2)}**",
            color=discord.Color.from_rgb(230, 126, 34),
        )
        embed.set_footer(text=f"Zobacz wszystkie: /typy_setowe mecz:{mecz}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mecze", description="Lista meczów otwartych do obstawiania")
    async def mecze(self, interaction: discord.Interaction):
        matches = await db.get_open_matches()
        if not matches:
            await interaction.response.send_message("📋 Brak otwartych meczów w tej chwili.")
            return

        LIMIT = 24
        shown = matches[:LIMIT]

        embed = discord.Embed(
            title="📋  Otwarte mecze",
            description=f"Aktualnie **{len(matches)}** mecz(e/ów) czeka na typy.",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        for m in shown:
            value = f"🎾 **{m['player_a']}** @{m['odds_a']}  vs  **{m['player_b']}** @{m['odds_b']}"
            if m["best_of"]:
                value += f"\n_wynik setowy: `/typy_setowe mecz:{m['id']}`_"
            embed.add_field(name=f"Mecz #{m['id']}", value=value, inline=False)

        if len(matches) > LIMIT:
            embed.set_footer(
                text=f"Pokazano {LIMIT} z {len(matches)}. Posprzątaj stare/testowe mecze przez /anuluj_mecz."
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="anuluj_mecz", description="[Admin] Zamknij mecz BEZ rozstrzygania (np. duplikat/pomyłka) i zwróć stawki")
    @app_commands.describe(mecz="ID meczu do anulowania")
    @is_authorized()
    async def anuluj_mecz(self, interaction: discord.Interaction, mecz: int):
        match = await db.get_match(mecz)
        if match is None:
            await interaction.response.send_message("Nie ma meczu o takim ID.", ephemeral=True)
            return
        if match["status"] != "open":
            await interaction.response.send_message("Ten mecz nie jest już otwarty.", ephemeral=True)
            return

        summary = await db.cancel_match(mecz)

        embed = discord.Embed(
            title=f"🗑️  Mecz #{mecz} anulowany",
            description=f"{match['player_a']} vs {match['player_b']}",
            color=discord.Color.from_rgb(149, 165, 166),
        )
        embed.add_field(
            name="Zwrócone stawki",
            value=(
                f"Pojedyncze: {summary['bets']}\n"
                f"Setowe: {summary['score_bets']}\n"
                f"Kupony: {summary['slips']}"
            ),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="historia_meczy", description="Ostatnio rozstrzygnięte mecze")
    async def historia_meczy(self, interaction: discord.Interaction):
        matches = await db.get_settled_matches(10)
        if not matches:
            await interaction.response.send_message("Brak jeszcze rozstrzygniętych meczów.")
            return

        embed = discord.Embed(
            title="📖  Historia meczów",
            color=discord.Color.from_rgb(52, 73, 94),
        )
        for m in matches:
            embed.add_field(
                name=f"Mecz #{m['id']}: {m['player_a']} vs {m['player_b']}",
                value=f"🏆 Zwycięzca: **{m['winner']}**",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # ---------- USER: obstawianie ----------

    @app_commands.command(name="typuj", description="Postaw zakład na mecz")
    @app_commands.describe(
        mecz="ID meczu (zobacz /mecze)",
        gracz="Imię gracza, na którego stawiasz (dokładnie jak w /mecze)",
        kwota="Ile stawiasz",
    )
    async def typuj(self, interaction: discord.Interaction, mecz: int, gracz: str, kwota: int):
        if kwota <= 0:
            await interaction.response.send_message("Kwota musi być dodatnia.", ephemeral=True)
            return

        limit_error = check_max_bet(kwota)
        if limit_error:
            await interaction.response.send_message(limit_error, ephemeral=True)
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

    @app_commands.command(name="typy_setowe", description="Pokaż zakłady na dokładny wynik setowy dla meczu")
    @app_commands.describe(mecz="ID meczu (zobacz /mecze)")
    async def typy_setowe(self, interaction: discord.Interaction, mecz: int):
        match = await db.get_match(mecz)
        if match is None:
            await interaction.response.send_message("Nie ma meczu o takim ID.", ephemeral=True)
            return

        markets = await db.get_score_markets(mecz)
        if not markets:
            await interaction.response.send_message(
                "Ten mecz nie ma otwartych zakładów na wynik setowy.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🎯  Wynik setowy — mecz #{mecz}",
            description=f"{match['player_a']} vs {match['player_b']}",
            color=discord.Color.from_rgb(230, 126, 34),
        )
        for market in markets:
            embed.add_field(name=market["label"], value=f"kurs **{market['odds']}**", inline=True)
        embed.set_footer(text=f"Obstaw: /typuj_wynik mecz:{mecz} opcja:\"<etykieta>\" kwota:100")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="typuj_wynik", description="Postaw zakład na dokładny wynik setowy")
    @app_commands.describe(
        mecz="ID meczu (zobacz /typy_setowe)",
        opcja="Dokładna etykieta z /typy_setowe, np. 'Sinner 2:0'",
        kwota="Ile stawiasz",
    )
    async def typuj_wynik(self, interaction: discord.Interaction, mecz: int, opcja: str, kwota: int):
        if kwota <= 0:
            await interaction.response.send_message("Kwota musi być dodatnia.", ephemeral=True)
            return

        limit_error = check_max_bet(kwota)
        if limit_error:
            await interaction.response.send_message(limit_error, ephemeral=True)
            return

        match = await db.get_match(mecz)
        if match is None or match["status"] != "open":
            await interaction.response.send_message("Ten mecz nie jest otwarty do obstawiania.", ephemeral=True)
            return

        picked_odds = await db.get_score_market_odds(mecz, opcja)
        if picked_odds is None:
            markets = await db.get_score_markets(mecz)
            valid = ", ".join(m["label"] for m in markets) if markets else "brak"
            await interaction.response.send_message(
                f"Nie ma takiej opcji. Dostępne: {valid}", ephemeral=True
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
        await db.place_score_bet(mecz, interaction.user.id, opcja, kwota, picked_odds)

        potential = round(kwota * picked_odds)
        embed = discord.Embed(
            title="✅  Zakład na wynik setowy przyjęty",
            color=discord.Color.from_rgb(230, 126, 34),
        )
        embed.add_field(name="Typ", value=f"**{opcja}** @ {picked_odds}", inline=True)
        embed.add_field(name="Stawka", value=format_money(kwota), inline=True)
        embed.add_field(name="Możliwa wygrana", value=f"**{format_money(potential)}**", inline=True)
        await interaction.response.send_message(embed=embed)

    # ---------- ADMIN: rozstrzyganie ----------

    @app_commands.command(name="rozstrzygnij", description="[Admin] Rozstrzygnij mecz i wypłać wygrane")
    @app_commands.describe(
        mecz="ID meczu",
        zwyciezca="Imię zwycięzcy (dokładnie jak w /mecze)",
        wynik="Opcjonalnie: dokładny wynik setowy (np. 2:0, 3:1) - potrzebny do rozliczenia /typuj_wynik",
    )
    @is_authorized()
    async def rozstrzygnij(self, interaction: discord.Interaction, mecz: int, zwyciezca: str, wynik: str = None):
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

        score_results = []
        score_markets = await db.get_score_markets(mecz)
        if score_markets:
            score_results = await db.settle_score_bets(mecz, zwyciezca, wynik)

        wins = sum(1 for r in results if r[1])
        embed = discord.Embed(
            title=f"🏁  Mecz #{mecz} rozstrzygnięty",
            description=f"🏆 Zwycięzca: **{zwyciezca}**" + (f" ({wynik})" if wynik else ""),
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
        if score_results:
            if wynik:
                score_wins = sum(1 for r in score_results if r[1])
                embed.add_field(
                    name="Zakłady na wynik setowy",
                    value=f"Wypłacono {score_wins} z {len(score_results)}",
                    inline=True,
                )
            else:
                embed.add_field(
                    name="Zakłady na wynik setowy",
                    value=f"Zwrócono stawki ({len(score_results)}) — nie podano dokładnego wyniku",
                    inline=True,
                )

        winner_ids = {r[0] for r in results if r[1]}
        winner_ids |= {r[0] for r in slip_results if r[2]}
        winner_ids |= {r[0] for r in score_results if r[1]}
        if winner_ids:
            mentions = " ".join(f"<@{uid}>" for uid in winner_ids)
            embed.add_field(name="🎉  Gratulacje", value=mentions, inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Betting(bot))
