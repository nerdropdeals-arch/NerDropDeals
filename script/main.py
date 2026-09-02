"""
NerDrop - Bot semi-automatico
L'utente manda al bot (in chat privata) il link di un prodotto Amazon che ha
trovato lui stesso. Lo script legge i messaggi nuovi, scarica QUELLA SINGOLA
pagina prodotto (consentito da robots.txt, a differenza delle pagine di
ricerca/offerte), estrae titolo/prezzo/immagine, aggiunge il link affiliato
e pubblica sul canale Telegram.
"""

import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

STATE_FILE = Path(__file__).parent.parent / "data" / "telegram_offset.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@nerdropdeals")
AFFILIATE_TAG = os.environ.get("AMAZON_AFFILIATE_TAG", "")  # es. nerdrop-21

# Solo i messaggi che arrivano da questo ID Telegram vengono processati.
# Protegge il bot da chiunque altro scopra lo username e provi a scrivergli.
OWNER_CHAT_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
}

AMAZON_URL_PATTERN = re.compile(r"https?://(?:www\.)?amazon\.[a-z.]+/[^\s]*")


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
# Lettura pagina prodotto (singola, quella che l'utente ha mandato)
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


def leggi_prodotto(url: str) -> dict | None:
    """
    Scarica la singola pagina prodotto (consentito da robots.txt) ed estrae
    titolo, prezzo e immagine. I selettori sono quelli standard delle pagine
    prodotto Amazon, ma vanno verificati/aggiustati se Amazon cambia layout.
    """
    asin = estrai_asin(url)
    if not asin:
        print(f"Link non riconosciuto come pagina prodotto Amazon: {url}")
        return None

    url_pulito = f"https://www.amazon.it/dp/{asin}"

    try:
        resp = requests.get(url_pulito, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Errore nel download della pagina prodotto: {exc}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    titolo_el = soup.select_one("#productTitle")
    titolo = titolo_el.get_text(strip=True) if titolo_el else "Prodotto Amazon"

    prezzo_el = (
        soup.select_one("#corePrice_feature_div .a-price .a-offscreen")
        or soup.select_one(".priceToPay .a-offscreen")
        or soup.select_one("#priceblock_ourprice")
        or soup.select_one(".a-price .a-offscreen")
    )
    prezzo = parse_prezzo(prezzo_el.get_text(strip=True)) if prezzo_el else None

    immagine_el = soup.select_one("#landingImage")
    immagine_url = immagine_el.get("src") if immagine_el else None

    return {
        "asin": asin,
        "titolo": titolo,
        "prezzo_attuale": prezzo,
        "immagine_url": immagine_url,
        "url": url_pulito,
    }


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def costruisci_link_affiliato(url: str) -> str:
    if not AFFILIATE_TAG:
        return url
    separatore = "&" if "?" in url else "?"
    return f"{url}{separatore}tag={AFFILIATE_TAG}"


def formatta_messaggio(prodotto: dict) -> str:
    link = costruisci_link_affiliato(prodotto["url"])
    prezzo_testo = (
        f"💶 <b>{prodotto['prezzo_attuale']:.2f} €</b>\n\n"
        if prodotto["prezzo_attuale"] is not None
        else ""
    )
    return (
        f"🔥 <b>{prodotto['titolo']}</b>\n\n"
        f"{prezzo_testo}"
        f"👉 <a href=\"{link}\">Vai all'offerta</a>"
    )


def pubblica_su_telegram(prodotto: dict, testo: str) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN non impostato, salto la pubblicazione.")
        return False

    # Se abbiamo trovato un'immagine, pubblichiamo foto+didascalia,
    # altrimenti solo testo.
    if prodotto.get("immagine_url"):
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "photo": prodotto["immagine_url"],
            "caption": testo,
            "parse_mode": "HTML",
        }
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": testo,
            "parse_mode": "HTML",
        }

    resp = requests.post(url, json=payload, timeout=15)
    if not resp.ok:
        print(f"Errore pubblicazione Telegram: {resp.status_code} {resp.text}")
        return False
    return True


def rispondi_al_proprietario(testo: str) -> None:
    """Manda una conferma in chat privata, per sapere che è andato tutto bene."""
    if not TELEGRAM_BOT_TOKEN or not OWNER_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": OWNER_CHAT_ID, "text": testo, "parse_mode": "HTML"}
    requests.post(url, json=payload, timeout=15)


def leggi_nuovi_messaggi(offset: int) -> tuple[list[dict], int]:
    """
    Legge i messaggi nuovi arrivati al bot (getUpdates), a partire dall'ultimo
    offset salvato. Ritorna (lista messaggi, nuovo offset da salvare).
    """
    if not TELEGRAM_BOT_TOKEN:
        return [], offset

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 0}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    messaggi = []
    nuovo_offset = offset

    for update in data.get("result", []):
        nuovo_offset = update["update_id"] + 1
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            continue
        chat_id = msg.get("chat", {}).get("id")
        testo = msg.get("text", "")
        messaggi.append({"chat_id": chat_id, "testo": testo})

    return messaggi, nuovo_offset


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not OWNER_CHAT_ID:
        print("OWNER_CHAT_ID non impostato: nessun messaggio verrà processato.")

    state = load_state()
    offset = state.get("offset", 0)

    messaggi, nuovo_offset = leggi_nuovi_messaggi(offset)
    print(f"Messaggi nuovi trovati: {len(messaggi)}")

    pubblicazioni = 0

    for msg in messaggi:
        if msg["chat_id"] != OWNER_CHAT_ID:
            print(f"Messaggio ignorato, chat_id non autorizzato: {msg['chat_id']}")
            continue

        match = AMAZON_URL_PATTERN.search(msg["testo"])
        if not match:
            continue  # non era un link Amazon, ignoriamo

        link = match.group(0)
        print(f"Link ricevuto: {link}")

        prodotto = leggi_prodotto(link)
        if prodotto is None:
            rispondi_al_proprietario("⚠️ Non sono riuscito a leggere quella pagina prodotto.")
            continue

        testo_post = formatta_messaggio(prodotto)
        if pubblica_su_telegram(prodotto, testo_post):
            pubblicazioni += 1
            rispondi_al_proprietario(f"✅ Pubblicato: {prodotto['titolo'][:60]}")
        else:
            rispondi_al_proprietario("⚠️ Errore nella pubblicazione sul canale.")

    state["offset"] = nuovo_offset
    save_state(state)
    print(f"Fatto. Pubblicazioni in questo run: {pubblicazioni}")


if __name__ == "__main__":
    main()
