"""
NerDrop - Monitor offerte Amazon (Informatica/Elettronica)
Scarica le pagine offerte Amazon, confronta con lo storico locale,
e pubblica su Telegram le offerte che superano una soglia di sconto.
"""

import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

# Categorie da monitorare: nome interno -> URL pagina offerte Amazon.it
CATEGORIE = {
    "informatica": "https://www.amazon.it/deals?bubble-id=deals-collection-computers",
    "elettronica": "https://www.amazon.it/deals?bubble-id=deals-collection-electronics",
}

SOGLIA_SCONTO_PERCENTUALE = 30  # notifica solo sconti sopra questa soglia
PREZZO_MINIMO = 20.0            # ignora prodotti troppo economici (rumore)

STATE_FILE = Path(__file__).parent.parent / "data" / "notified.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@nerdropdeals")
AFFILIATE_TAG = os.environ.get("AMAZON_AFFILIATE_TAG", "")  # es. nerdrop-21

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
}

REQUEST_DELAY_SECONDS = 3  # pausa tra una richiesta e l'altra, per essere "gentili"


# ---------------------------------------------------------------------------
# Stato: quali offerte abbiamo già notificato
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def estrai_asin(url: str) -> str | None:
    match = re.search(r"/dp/([A-Z0-9]{10})", url)
    return match.group(1) if match else None


def parse_prezzo(testo: str) -> float | None:
    """Converte '299,99 €' o '299.99' in float."""
    if not testo:
        return None
    pulito = testo.replace("€", "").replace(".", "").replace(",", ".").strip()
    match = re.search(r"[\d.]+", pulito)
    return float(match.group()) if match else None


def scrape_categoria(nome: str, url: str) -> list[dict]:
    """
    Ritorna una lista di offerte trovate nella pagina.
    NOTA: i selettori CSS di Amazon cambiano spesso — questa è una base
    di partenza da verificare/aggiustare guardando l'HTML reale.
    """
    offerte = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[{nome}] Errore nel download della pagina: {exc}")
        return offerte

    soup = BeautifulSoup(resp.text, "html.parser")

    # Selettore indicativo: le card offerta Amazon usano vari data-testid
    # a seconda del layout. Da verificare/adattare ispezionando la pagina.
    cards = soup.select("[data-testid='deal-card']") or soup.select("div.DealCard")

    for card in cards:
        link_el = card.select_one("a[href*='/dp/']")
        if not link_el:
            continue
        href = link_el.get("href", "")
        asin = estrai_asin(href)
        if not asin:
            continue

        titolo_el = card.select_one("[data-testid='deal-title']") or card.select_one("span.a-truncate-full")
        titolo = titolo_el.get_text(strip=True) if titolo_el else "Prodotto senza titolo"

        prezzo_el = card.select_one(".a-price .a-offscreen")
        prezzo_attuale = parse_prezzo(prezzo_el.get_text(strip=True)) if prezzo_el else None

        sconto_el = card.select_one("[data-testid='deal-badge']")
        sconto_testo = sconto_el.get_text(strip=True) if sconto_el else ""
        sconto_match = re.search(r"(\d+)\s*%", sconto_testo)
        sconto_percentuale = int(sconto_match.group(1)) if sconto_match else None

        if prezzo_attuale is None or sconto_percentuale is None:
            continue

        offerte.append({
            "asin": asin,
            "categoria": nome,
            "titolo": titolo,
            "prezzo_attuale": prezzo_attuale,
            "sconto_percentuale": sconto_percentuale,
            "url": f"https://www.amazon.it/dp/{asin}",
        })

    return offerte


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def costruisci_link_affiliato(url: str) -> str:
    if not AFFILIATE_TAG:
        return url
    separatore = "&" if "?" in url else "?"
    return f"{url}{separatore}tag={AFFILIATE_TAG}"


def formatta_messaggio(offerta: dict) -> str:
    link = costruisci_link_affiliato(offerta["url"])
    return (
        f"🔥 <b>-{offerta['sconto_percentuale']}%</b>\n\n"
        f"{offerta['titolo']}\n\n"
        f"💶 <b>{offerta['prezzo_attuale']:.2f} €</b>\n\n"
        f"👉 <a href=\"{link}\">Vai all'offerta</a>\n\n"
        f"#{offerta['categoria']}"
    )


def pubblica_su_telegram(testo: str) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN non impostato, salto la pubblicazione.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": testo,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=15)
    if not resp.ok:
        print(f"Errore pubblicazione Telegram: {resp.status_code} {resp.text}")
        return False
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    state = load_state()
    nuove_pubblicazioni = 0

    for nome_categoria, url in CATEGORIE.items():
        print(f"Controllo categoria: {nome_categoria}")
        offerte = scrape_categoria(nome_categoria, url)
        print(f"  -> trovate {len(offerte)} offerte grezze")

        for offerta in offerte:
            asin = offerta["asin"]

            if offerta["sconto_percentuale"] < SOGLIA_SCONTO_PERCENTUALE:
                continue
            if offerta["prezzo_attuale"] < PREZZO_MINIMO:
                continue

            gia_notificata = state.get(asin)
            # Rinotifica solo se il prezzo è sceso ulteriormente rispetto all'ultima volta
            if gia_notificata and offerta["prezzo_attuale"] >= gia_notificata.get("prezzo_attuale", 0):
                continue

            messaggio = formatta_messaggio(offerta)
            if pubblica_su_telegram(messaggio):
                nuove_pubblicazioni += 1
                state[asin] = {
                    "prezzo_attuale": offerta["prezzo_attuale"],
                    "sconto_percentuale": offerta["sconto_percentuale"],
                    "titolo": offerta["titolo"],
                }
                time.sleep(1)  # piccola pausa tra un post e l'altro

        time.sleep(REQUEST_DELAY_SECONDS)

    save_state(state)
    print(f"Fatto. Pubblicazioni nuove in questo run: {nuove_pubblicazioni}")


if __name__ == "__main__":
    main()
