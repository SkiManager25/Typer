import os
import asyncio
import discord
from discord.ext import commands

from database import init_db

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Zsynchronizowano {len(synced)} komend slash.")
    except Exception as e:
        print(f"Błąd synchronizacji komend: {e}")


async def main():
    await init_db()
    async with bot:
        await bot.load_extension("cogs.economy")
        await bot.load_extension("cogs.betting")
        await bot.load_extension("cogs.kupony")
        await bot.start(TOKEN)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "Brak DISCORD_TOKEN. Ustaw zmienną środowiskową, np.:\n"
            "  export DISCORD_TOKEN=twoj_token_tutaj   (Linux/Mac)\n"
            "  set DISCORD_TOKEN=twoj_token_tutaj      (Windows cmd)"
        )
    asyncio.run(main())
