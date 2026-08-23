"""
Liczenie kursów bukmacherskich na podstawie miejsca w rankingu ATP/WTA.

Logika:
1. Niższy numer rankingowy = lepszy zawodnik, więc "siłę" gracza liczymy jako 1/rank.
2. Prawdopodobieństwo wygranej = udział siły gracza w sumie sił obu graczy.
3. Kurs uczciwy (fair odds) = 1 / prawdopodobieństwo.
4. Odejmujemy marżę bukmacherską (np. 6%), żeby suma "implikowanych prawdopodobieństw"
   przekraczała 100% - tak działają prawdziwe zakłady.
"""

MARGIN = 0.06       # 6% marży "domu"
MIN_ODDS = 1.01      # bezpieczny dolny limit kursu
RANK_STRENGTH_EXPONENT = 1.0  # >1 = różnice w rankingu mają większe znaczenie


def _strength(rank: int) -> float:
    # zabezpieczenie przed rank = 0
    rank = max(rank, 1)
    return 1 / (rank ** RANK_STRENGTH_EXPONENT)


def calculate_odds(rank_a: int, rank_b: int) -> tuple[float, float]:
    """Zwraca (odds_a, odds_b) jako kursy dziesiętne, np. (1.85, 1.95)."""
    strength_a = _strength(rank_a)
    strength_b = _strength(rank_b)

    prob_a = strength_a / (strength_a + strength_b)
    prob_b = 1 - prob_a

    # kurs uczciwy, potem obniżony o marżę
    fair_odds_a = 1 / prob_a
    fair_odds_b = 1 / prob_b

    odds_a = max(fair_odds_a * (1 - MARGIN), MIN_ODDS)
    odds_b = max(fair_odds_b * (1 - MARGIN), MIN_ODDS)

    return round(odds_a, 2), round(odds_b, 2)


if __name__ == "__main__":
    # szybki test - faworyt (rank 3) vs outsider (rank 87)
    print(calculate_odds(3, 87))   # oczekiwane: niski kurs / wysoki kurs
    print(calculate_odds(1, 2))    # wyrównany mecz top graczy
