def format_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " zł"
