import aiosqlite

DB_PATH = "typerka.db"

START_BALANCE = 35


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
        # Kupony (AKO) - jeden zaklad obejmujacy kilka meczow, kursy sie mnoza
        await db.execute("""
            CREATE TABLE IF NOT EXISTS slips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',  -- draft / placed / settled
                stake INTEGER,
                combined_odds REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS slip_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slip_id INTEGER NOT NULL,
                match_id INTEGER NOT NULL,
                player_choice TEXT NOT NULL,
                odds_at_pick REAL NOT NULL,
                result TEXT NOT NULL DEFAULT 'pending',  -- pending / won / lost
                FOREIGN KEY(slip_id) REFERENCES slips(id),
                FOREIGN KEY(match_id) REFERENCES matches(id)
            )
        """)

        # migracja: dodaj kolumne best_of do matches jesli jeszcze jej nie ma
        try:
            await db.execute("ALTER TABLE matches ADD COLUMN best_of INTEGER")
        except Exception:
            pass  # kolumna juz istnieje

        # Zaklady na dokladny wynik setowy
        await db.execute("""
            CREATE TABLE IF NOT EXISTS score_markets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                odds REAL NOT NULL,
                FOREIGN KEY(match_id) REFERENCES matches(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS score_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                label TEXT NOT NULL,
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


async def find_open_match_by_players(player_a: str, player_b: str):
    """Szuka juz istniejacego OTWARTEGO meczu tych samych dwoch graczy
    (niezaleznie od kolejnosci), zeby unikac duplikatow przy ponownych probach."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM matches WHERE status = 'open' AND
               ((player_a = ? AND player_b = ?) OR (player_a = ? AND player_b = ?))
               ORDER BY id DESC LIMIT 1""",
            (player_a, player_b, player_b, player_a),
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
    """Oznacza mecz jako rozstrzygnięty, wypłaca wygrane z pojedynczych zakładów
    oraz aktualizuje/rozlicza kupony (AKO), które zawierają ten mecz."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE matches SET status = 'settled', winner = ? WHERE id = ?",
            (winner, match_id),
        )

        # --- pojedyncze zaklady ---
        async with db.execute(
            "SELECT * FROM bets WHERE match_id = ? AND settled = 0", (match_id,)
        ) as cur:
            bets = await cur.fetchall()

        results = []  # (discord_id, won: bool, payout: int, amount: int)
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

        # --- nogi kuponow (AKO) na ten mecz ---
        async with db.execute(
            """SELECT slip_legs.*, slips.discord_id AS slip_owner
               FROM slip_legs JOIN slips ON slip_legs.slip_id = slips.id
               WHERE slip_legs.match_id = ? AND slip_legs.result = 'pending'
                 AND slips.status = 'placed'""",
            (match_id,),
        ) as cur:
            legs = await cur.fetchall()

        affected_slip_ids = set()
        for leg in legs:
            leg_won = leg["player_choice"] == winner
            await db.execute(
                "UPDATE slip_legs SET result = ? WHERE id = ?",
                ("won" if leg_won else "lost", leg["id"]),
            )
            affected_slip_ids.add(leg["slip_id"])

        slip_results = []  # (discord_id, slip_id, won: bool, payout: int, stake: int)
        for slip_id in affected_slip_ids:
            async with db.execute(
                "SELECT * FROM slips WHERE id = ?", (slip_id,)
            ) as cur:
                slip = await cur.fetchone()
            async with db.execute(
                "SELECT * FROM slip_legs WHERE slip_id = ?", (slip_id,)
            ) as cur:
                all_legs = await cur.fetchall()

            if any(l["result"] == "lost" for l in all_legs):
                # kupon przegrany - rozliczamy od razu, reszta nog moze zostac pending
                await db.execute(
                    "UPDATE slips SET status = 'settled' WHERE id = ?", (slip_id,)
                )
                slip_results.append((slip["discord_id"], slip_id, False, 0, slip["stake"]))
            elif all(l["result"] == "won" for l in all_legs):
                payout = int(round(slip["stake"] * slip["combined_odds"]))
                await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE discord_id = ?",
                    (payout, slip["discord_id"]),
                )
                await db.execute(
                    "UPDATE slips SET status = 'settled' WHERE id = ?", (slip_id,)
                )
                slip_results.append((slip["discord_id"], slip_id, True, payout, slip["stake"]))
            # inaczej: nadal sa nogi 'pending' - czekamy na kolejne mecze

        await db.commit()
        return results, slip_results


# ---------- KUPONY (AKO) ----------

async def get_draft_slip(discord_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slips WHERE discord_id = ? AND status = 'draft'", (discord_id,)
        ) as cur:
            return await cur.fetchone()


async def get_or_create_draft_slip(discord_id: int) -> int:
    slip = await get_draft_slip(discord_id)
    if slip:
        return slip["id"]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO slips (discord_id, status) VALUES (?, 'draft')", (discord_id,)
        )
        await db.commit()
        return cur.lastrowid


async def add_leg(slip_id: int, match_id: int, player_choice: str, odds_at_pick: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO slip_legs (slip_id, match_id, player_choice, odds_at_pick)
               VALUES (?, ?, ?, ?)""",
            (slip_id, match_id, player_choice, odds_at_pick),
        )
        await db.commit()


async def get_slip_legs(slip_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT slip_legs.*, matches.player_a, matches.player_b
               FROM slip_legs JOIN matches ON slip_legs.match_id = matches.id
               WHERE slip_legs.slip_id = ?""",
            (slip_id,),
        ) as cur:
            return await cur.fetchall()


async def remove_leg(slip_id: int, match_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM slip_legs WHERE slip_id = ? AND match_id = ?", (slip_id, match_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def clear_draft_slip(discord_id: int):
    slip = await get_draft_slip(discord_id)
    if not slip:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM slip_legs WHERE slip_id = ?", (slip["id"],))
        await db.execute("DELETE FROM slips WHERE id = ?", (slip["id"],))
        await db.commit()


async def place_slip(discord_id: int, stake: int) -> tuple[bool, str]:
    """Zatwierdza kupon (draft -> placed), pobiera stawke z konta.
    Zwraca (sukces, komunikat_bledu_lub_pusty)."""
    slip = await get_draft_slip(discord_id)
    if not slip:
        return False, "Nie masz otwartego kuponu. Dodaj mecze przez /kupon_dodaj."

    legs = await get_slip_legs(slip["id"])
    if len(legs) < 2:
        return False, "Kupon musi mieć co najmniej 2 mecze (dla 1 meczu użyj /typuj)."

    # sprawdz czy wszystkie mecze wciaz otwarte
    for leg in legs:
        match = await get_match(leg["match_id"])
        if match is None or match["status"] != "open":
            return False, f"Mecz #{leg['match_id']} nie jest już otwarty do obstawiania."

    balance = await get_balance(discord_id)
    if balance is None or balance < stake:
        from currency import format_money
        return False, f"Za mało kasy. Masz {format_money(balance or 0)}, chcesz postawić {format_money(stake)}."

    combined_odds = 1.0
    for leg in legs:
        combined_odds *= leg["odds_at_pick"]
    combined_odds = round(combined_odds, 2)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance = balance - ? WHERE discord_id = ?", (stake, discord_id)
        )
        await db.execute(
            "UPDATE slips SET status = 'placed', stake = ?, combined_odds = ? WHERE id = ?",
            (stake, combined_odds, slip["id"]),
        )
        await db.commit()

    return True, ""


async def get_user_slips(discord_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM slips WHERE discord_id = ? AND status != 'draft'
               ORDER BY id DESC LIMIT ?""",
            (discord_id, limit),
        ) as cur:
            return await cur.fetchall()


async def get_leaderboard(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY balance DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()


async def get_settled_matches(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM matches WHERE status = 'settled' ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()


# ---------- ZAKLADY NA WYNIK SETOWY ----------

async def set_match_best_of(match_id: int, best_of: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE matches SET best_of = ? WHERE id = ?", (best_of, match_id))
        await db.commit()


async def create_score_markets(match_id: int, markets: list[tuple[str, float]]):
    async with aiosqlite.connect(DB_PATH) as db:
        for label, odds in markets:
            await db.execute(
                "INSERT INTO score_markets (match_id, label, odds) VALUES (?, ?, ?)",
                (match_id, label, odds),
            )
        await db.commit()


async def upsert_score_market(match_id: int, label: str, odds: float):
    """Dodaje nowy wynik setowy albo nadpisuje kurs, jesli taka etykieta juz istnieje."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM score_markets WHERE match_id = ? AND label = ?", (match_id, label)
        ) as cur:
            row = await cur.fetchone()
        if row:
            await db.execute("UPDATE score_markets SET odds = ? WHERE id = ?", (odds, row[0]))
        else:
            await db.execute(
                "INSERT INTO score_markets (match_id, label, odds) VALUES (?, ?, ?)",
                (match_id, label, odds),
            )
        await db.commit()


async def get_score_markets(match_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM score_markets WHERE match_id = ? ORDER BY id", (match_id,)
        ) as cur:
            return await cur.fetchall()


async def get_score_market_odds(match_id: int, label: str) -> float | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT odds FROM score_markets WHERE match_id = ? AND label = ?", (match_id, label)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def place_score_bet(match_id: int, discord_id: int, label: str, amount: int, odds: float) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO score_bets (match_id, discord_id, label, amount, odds)
               VALUES (?, ?, ?, ?, ?)""",
            (match_id, discord_id, label, amount, odds),
        )
        await db.commit()
        return cur.lastrowid


async def settle_score_bets(match_id: int, winner: str, actual_score: str | None):
    """Rozlicza zaklady na wynik setowy dla meczu.
    Jesli actual_score is None (nie podano dokladnego wyniku), wszystkie zaklady
    setowe na ten mecz sa zwracane (stawka wraca na konto, bez wygranej)."""
    correct_label = f"{winner} {actual_score}" if actual_score else None

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM score_bets WHERE match_id = ? AND settled = 0", (match_id,)
        ) as cur:
            bets = await cur.fetchall()

        results = []  # (discord_id, won: bool, payout: int, amount: int, refunded: bool)
        for bet in bets:
            if correct_label is None:
                # brak dokladnego wyniku - zwrot stawki
                await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE discord_id = ?",
                    (bet["amount"], bet["discord_id"]),
                )
                await db.execute("UPDATE score_bets SET settled = 1 WHERE id = ?", (bet["id"],))
                results.append((bet["discord_id"], False, bet["amount"], bet["amount"], True))
            else:
                won = bet["label"] == correct_label
                payout = int(round(bet["amount"] * bet["odds"])) if won else 0
                if won:
                    await db.execute(
                        "UPDATE users SET balance = balance + ? WHERE discord_id = ?",
                        (payout, bet["discord_id"]),
                    )
                await db.execute("UPDATE score_bets SET settled = 1 WHERE id = ?", (bet["id"],))
                results.append((bet["discord_id"], won, payout, bet["amount"], False))

        await db.commit()
        return results
