"""
Moduł bazy danych dla bota typerskiego.
Używa SQLite (aiosqlite) - jeden plik bazy, zero konfiguracji.
"""
import aiosqlite

DB_PATH = "typerka.db"

START_BALANCE = 1000  # startowe saldo dla nowego usera


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER NOT NULL DEFAULT 1000
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_a TEXT NOT NULL,
                player_b TEXT NOT NULL,
                rank_a INTEGER NOT NULL,
                rank_b INTEGER NOT NULL,
                odds_a REAL NOT NULL,
                odds_b REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',  -- open / closed / settled
                winner TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                player_choice TEXT NOT NULL,
                amount INTEGER NOT NULL,
                odds REAL NOT NULL,
                settled INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(match_id) REFERENCES matches(id)
            )
        """)
        await db.commit()


async def get_or_create_user(discord_id: int, username: str) -> int:
    """Zwraca saldo użytkownika, tworząc konto jeśli nie istnieje."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT balance FROM users WHERE discord_id = ?", (discord_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO users (discord_id, username, balance) VALUES (?, ?, ?)",
                (discord_id, username, START_BALANCE),
            )
            await db.commit()
            return START_BALANCE
        else:
            # aktualizuj username na wypadek zmiany nicku
            await db.execute(
                "UPDATE users SET username = ? WHERE discord_id = ?",
                (username, discord_id),
            )
            await db.commit()
            return row[0]


async def get_balance(discord_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT balance FROM users WHERE discord_id = ?", (discord_id,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def change_balance(discord_id: int, delta: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE discord_id = ?",
            (delta, discord_id),
        )
        await db.commit()


async def create_match(player_a: str, rank_a: int, player_b: str, rank_b: int,
                        odds_a: float, odds_b: float) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO matches (player_a, rank_a, player_b, rank_b, odds_a, odds_b)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (player_a, rank_a, player_b, rank_b, odds_a, odds_b),
        )
        await db.commit()
        return cur.lastrowid


async def get_match(match_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM matches WHERE id = ?", (match_id,)
        ) as cur:
            return await cur.fetchone()


async def get_open_matches():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM matches WHERE status = 'open' ORDER BY id"
        ) as cur:
            return await cur.fetchall()


async def close_match(match_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE matches SET status = 'closed' WHERE id = ?", (match_id,)
        )
        await db.commit()


async def place_bet(match_id: int, discord_id: int, player_choice: str,
                     amount: int, odds: float) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO bets (match_id, discord_id, player_choice, amount, odds)
               VALUES (?, ?, ?, ?, ?)""",
            (match_id, discord_id, player_choice, amount, odds),
        )
        await db.commit()
        return cur.lastrowid


async def get_bets_for_match(match_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM bets WHERE match_id = ? AND settled = 0", (match_id,)
        ) as cur:
            return await cur.fetchall()


async def get_user_bets(discord_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT bets.*, matches.player_a, matches.player_b, matches.status, matches.winner
               FROM bets JOIN matches ON bets.match_id = matches.id
               WHERE bets.discord_id = ? ORDER BY bets.id DESC LIMIT 20""",
            (discord_id,),
        ) as cur:
            return await cur.fetchall()


async def settle_match(match_id: int, winner: str):
    """Oznacza mecz jako rozstrzygnięty i wypłaca wygrane."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE matches SET status = 'settled', winner = ? WHERE id = ?",
            (winner, match_id),
        )
        async with db.execute(
            "SELECT * FROM bets WHERE match_id = ? AND settled = 0", (match_id,)
        ) as cur:
            bets = await cur.fetchall()

        results = []  # (discord_id, won: bool, payout: int)
        for bet in bets:
            won = bet["player_choice"] == winner
            payout = int(round(bet["amount"] * bet["odds"])) if won else 0
            if won:
                await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE discord_id = ?",
                    (payout, bet["discord_id"]),
                )
            await db.execute("UPDATE bets SET settled = 1 WHERE id = ?", (bet["id"],))
            results.append((bet["discord_id"], won, payout, bet["amount"]))

        await db.commit()
        return results


async def get_leaderboard(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY balance DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()
