import requests

def pobierz_mecze_tenis():
    url = "https://api.betclic.com/v2/sports/2/events"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        
        mecze = []
        for event in data:
            # Pobieramy tylko mecze z dwoma opcjami (wygrana 1 / wygrana 2)
            if 'grouped_markets' in event and event['grouped_markets']:
                markets = event['grouped_markets'][0].get('markets', [])
                if markets:
                    selections = markets[0].get('selections', [])
                    if len(selections) == 2:
                        p1 = selections[0]['name']
                        k1 = selections[0]['odds']
                        p2 = selections[1]['name']
                        k2 = selections[1]['odds']
                        
                        mecze.append({
                            "gracz1": p1,
                            "kurs1": k1,
                            "gracz2": p2,
                            "kurs2": k2,
                            "nazwa_wydarzenia": event.get('name')
                        })
        return mecze
    except Exception as e:
        print(f"Błąd pobierania danych z Betclic: {e}")
        return []
