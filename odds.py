MARGIN = 0.06      
MIN_ODDS = 1.01     
RANK_STRENGTH_EXPONENT = 1.0  


def _strength(rank: int) -> float:
    rank = max(rank, 1)
    return 1 / (rank ** RANK_STRENGTH_EXPONENT)


def calculate_odds(rank_a: int, rank_b: int) -> tuple[float, float]:
    """Zwraca (odds_a, odds_b) jako kursy dziesiętne, np. (1.85, 1.95)."""
    strength_a = _strength(rank_a)
    strength_b = _strength(rank_b)

    prob_a = strength_a / (strength_a + strength_b)
    prob_b = 1 - prob_a

    fair_odds_a = 1 / prob_a
    fair_odds_b = 1 / prob_b

    odds_a = max(fair_odds_a * (1 - MARGIN), MIN_ODDS)
    odds_b = max(fair_odds_b * (1 - MARGIN), MIN_ODDS)

    return round(odds_a, 2), round(odds_b, 2)


if __name__ == "__main__":
    print(calculate_odds(3, 87))   # oczekiwane: niski kurs / wysoki kurs
    print(calculate_odds(1, 2))    # wyrównany mecz top graczy


def calculate_score_markets(odds_a: float, odds_b: float, player_a: str, player_b: str,
                             best_of: int) -> list[tuple[str, float]]:
    """Rozbija kurs meczowy na kursy na dokładny wynik setowy.

    best_of=3 -> mecz do 2 wygranych setów (mozliwe wyniki 2:0, 2:1)
    best_of=5 -> mecz do 3 wygranych setow (mozliwe wyniki 3:0, 3:1, 3:2)

    Prawdopodobienstwa wygranej graczy licza sie z kursow meczowych (implikowane,
    znormalizowane), a nastepnie dziela na poszczegolne wyniki setowe wg prostej
    heurystyki: im bardziej wyrownany mecz, tym wiekszy udzial wyniku "do decydujacego seta".
    Zwraca liste (etykieta, kurs), np. ("Sinner 2:0", 1.8).
    """
    raw_a = 1 / odds_a
    raw_b = 1 / odds_b
    prob_a = raw_a / (raw_a + raw_b)
    prob_b = 1 - prob_a

    closeness = 1 - abs(prob_a - 0.5) * 2  # 1 = wyrownany mecz, 0 = duzy faworyt

    if best_of == 3:
        w_straight = 0.65 - 0.25 * closeness
        w_decider = 1 - w_straight
        weights = {"2:0": w_straight, "2:1": w_decider}
    elif best_of == 5:
        w_3_0 = 0.45 - 0.25 * closeness
        w_3_1 = 0.35
        w_3_2 = max(1 - w_3_0 - w_3_1, 0.05)
        weights = {"3:0": w_3_0, "3:1": w_3_1, "3:2": w_3_2}
    else:
        raise ValueError("best_of musi być 3 lub 5")

    results = []
    for label, prob_win in [("A", prob_a), ("B", prob_b)]:
        player = player_a if label == "A" else player_b
        for score, weight in weights.items():
            prob = prob_win * weight
            fair_odds = 1 / prob
            score_odds = max(fair_odds * (1 - MARGIN), MIN_ODDS)
            results.append((f"{player} {score}", round(score_odds, 2)))

    return results
