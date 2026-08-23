# Tenis Typerka Bot

Bot Discord do obstawiania prawdziwych meczów ATP/WTA za wirtualne punkty.
Kursy liczone automatycznie na podstawie rankingu obu graczy.

## Instalacja

1. Zainstaluj Pythona 3.10+ i zależności:
   ```
   pip install -r requirements.txt
   ```

2. Utwórz bota na https://discord.com/developers/applications
   - Zakładka "Bot" -> "Reset Token" -> skopiuj token
   - W "OAuth2 -> URL Generator" zaznacz scope `bot` i `applications.commands`,
     uprawnienia: Send Messages, Use Slash Commands, Embed Links
   - Wejdź w wygenerowany link i dodaj bota na swój serwer

3. Ustaw token jako zmienną środowiskową (nie wklejaj go do kodu!):
   ```
   export DISCORD_TOKEN=twoj_token_tutaj
   ```

4. Uruchom bota:
   ```
   python bot.py
   ```

## Komendy

**Admin (osoba z uprawnieniem Administrator na serwerze):**
- `/dodajmecz gracz_a ranking_a gracz_b ranking_b` — otwiera nowy mecz do obstawiania,
  kursy liczą się same z rankingu
- `/rozstrzygnij mecz zwyciezca` — zamyka mecz i automatycznie wypłaca wygrane

**Wszyscy:**
- `/saldo` — sprawdź swoje punkty (nowe konto startuje z 1000 pkt)
- `/mecze` — lista otwartych meczów z kursami
- `/typuj mecz gracz kwota` — postaw zakład
- `/moje_zaklady` — historia Twoich zakładów
- `/ranking_graczy` — top 10 najbogatszych typerów

## Jak liczone są kursy

Siła gracza = 1 / jego miejsce w rankingu (im niższy numer, tym silniejszy gracz).
Prawdopodobieństwo wygranej = udział siły gracza w sumie sił obu zawodników.
Kurs = 1 / prawdopodobieństwo, pomniejszony o 6% marży "domu" (jak u prawdziwych bukmacherów,
suma prawdopodobieństw > 100%, żeby ekonomia się spinała).

Parametry do dostrojenia w `odds.py`:
- `MARGIN` — marża bukmacherska (domyślnie 6%)
- `RANK_STRENGTH_EXPONENT` — jak mocno różnica w rankingu wpływa na kurs (domyślnie 1.0,
  wyższa wartość = większe różnice w kursach między faworytem a outsiderem)

## Pomysły na rozwój

- Automatyczne pobieranie aktualnego rankingu ATP/WTA (np. scraping lub płatne API typu
  Sportradar / api-tennis.com) zamiast ręcznego wpisywania przy `/dodajmecz`
- Dzienny bonus / odnawianie punktów, żeby nikt nie "zbankrutował" na stałe
- Limit maksymalnego zakładu, żeby jedna osoba nie zdominowała ekonomii
- Automatyczne zamykanie zakładów o godzinie startu meczu (`/zamknij mecz`)
- Kanał z historią wszystkich rozstrzygniętych zakładów (log embed)
