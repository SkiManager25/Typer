import discord
from discord import app_commands
from discord.ext import commands

import database as db


class Kupony(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="kupon_dodaj", description="Dodaj mecz do swojego kuponu (AKO)")
    @app_commands.describe(
        mecz="ID meczu (zobacz /mecze)",
        gracz="Imię gracza, na którego stawiasz w tym meczu",
    )
    async def kupon_dodaj(self, interaction: discord.Interaction, mecz: int, gracz: str):
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

        slip_id = await db.get_or_create_draft_slip(interaction.user.id)

        existing_legs = await db.get_slip_legs(slip_id)
        if any(leg["match_id"] == mecz for leg in existing_legs):
            await interaction.response.send_message(
                "Ten mecz jest już na Twoim kuponie. Usuń go najpierw przez /kupon_usun, jeśli chcesz zmienić typ.",
                ephemeral=True,
            )
            return

        await db.add_leg(slip_id, mecz, gracz, picked_odds)
        legs = await db.get_slip_legs(slip_id)
        combined = 1.0
        for leg in legs:
            combined *= leg["odds_at_pick"]

        await interaction.response.send_message(
            f"✅ Dodano do kuponu: **{gracz}** @ {picked_odds} (mecz #{mecz}).\n"
            f"Kupon zawiera teraz **{len(legs)}** mecz(e/ów) — łączny kurs: **{round(combined, 2)}**.\n"
            f"Zobacz kupon: `/kupon_pokaz` | Obstaw: `/kupon_obstaw kwota:100`"
        )

    @app_commands.command(name="kupon_usun", description="Usuń mecz ze swojego kuponu")
    @app_commands.describe(mecz="ID meczu do usunięcia z kuponu")
    async def kupon_usun(self, interaction: discord.Interaction, mecz: int):
        slip = await db.get_draft_slip(interaction.user.id)
        if not slip:
            await interaction.response.send_message("Nie masz otwartego kuponu.", ephemeral=True)
            return
        removed = await db.remove_leg(slip["id"], mecz)
        if removed:
            await interaction.response.send_message(f"Usunięto mecz #{mecz} z kuponu.")
        else:
            await interaction.response.send_message("Tego meczu nie było na kuponie.", ephemeral=True)

    @app_commands.command(name="kupon_pokaz", description="Pokaż swój aktualny kupon (przed obstawieniem)")
    async def kupon_pokaz(self, interaction: discord.Interaction):
        slip = await db.get_draft_slip(interaction.user.id)
        if not slip:
            await interaction.response.send_message(
                "Nie masz otwartego kuponu. Dodaj mecz przez `/kupon_dodaj`.", ephemeral=True
            )
            return

        legs = await db.get_slip_legs(slip["id"])
        if not legs:
            await interaction.response.send_message(
                "Twój kupon jest pusty. Dodaj mecz przez `/kupon_dodaj`.", ephemeral=True
            )
            return

        combined = 1.0
        lines = []
        for leg in legs:
            combined *= leg["odds_at_pick"]
            lines.append(
                f"#{leg['match_id']}: {leg['player_a']} vs {leg['player_b']} — "
                f"typ: {leg['player_choice']} @ {leg['odds_at_pick']}"
            )
        combined = round(combined, 2)

        text = "```\n" + "\n".join(lines) + f"\n\nŁączny kurs: {combined}\n" + "```"
        await interaction.response.send_message(
            f"🎟️ **Twój kupon ({len(legs)} mecz(e/ów))**\n{text}\n"
            f"Obstaw: `/kupon_obstaw kwota:100`"
        )

    @app_commands.command(name="kupon_obstaw", description="Zatwierdź i obstaw swój kupon")
    @app_commands.describe(kwota="Ile stawiasz na cały kupon")
    async def kupon_obstaw(self, interaction: discord.Interaction, kwota: int):
        if kwota <= 0:
            await interaction.response.send_message("Kwota musi być dodatnia.", ephemeral=True)
            return

        await db.get_or_create_user(interaction.user.id, str(interaction.user))
        success, error = await db.place_slip(interaction.user.id, kwota)
        if not success:
            await interaction.response.send_message(error, ephemeral=True)
            return

        slip = (await db.get_user_slips(interaction.user.id, limit=1))[0]
        potential = int(round(slip["stake"] * slip["combined_odds"]))
        await interaction.response.send_message(
            f"✅ Kupon obstawiony! Stawka: **${kwota:,}**, łączny kurs: **{slip['combined_odds']}**.\n"
            f"Możliwa wygrana: **${potential:,}**."
        )

    @app_commands.command(name="kupon_anuluj", description="Anuluj (wyczyść) swój niezatwierdzony kupon")
    async def kupon_anuluj(self, interaction: discord.Interaction):
        slip = await db.get_draft_slip(interaction.user.id)
        if not slip:
            await interaction.response.send_message("Nie masz otwartego kuponu do anulowania.", ephemeral=True)
            return
        await db.clear_draft_slip(interaction.user.id)
        await interaction.response.send_message("Kupon wyczyszczony.")

    @app_commands.command(name="moje_kupony", description="Historia Twoich kuponów (AKO)")
    async def moje_kupony(self, interaction: discord.Interaction):
        slips = await db.get_user_slips(interaction.user.id)
        if not slips:
            await interaction.response.send_message("Nie masz jeszcze żadnych obstawionych kuponów.")
            return

        lines = []
        for slip in slips:
            legs = await db.get_slip_legs(slip["id"])
            leg_desc = ", ".join(f"{l['player_choice']}" for l in legs)
            if slip["status"] == "placed":
                status = "⏳ w toku"
            else:
                any_lost = any(l["result"] == "lost" for l in legs)
                status = "❌ przegrany" if any_lost else "✅ wygrany"
            lines.append(
                f"Kupon #{slip['id']} ({len(legs)} mecz(e/ów): {leg_desc}) — "
                f"stawka ${slip['stake']:,} @ {slip['combined_odds']} — {status}"
            )

        text = "```\n" + "\n".join(lines) + "\n```"
        await interaction.response.send_message(text)


async def setup(bot: commands.Bot):
    await bot.add_cog(Kupony(bot))
