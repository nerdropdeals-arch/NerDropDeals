# NerDrop

Monitor automatico di offerte Amazon (Informatica/Elettronica) che pubblica
su Telegram (@nerdropdeals) le offerte sopra una certa soglia di sconto.

## Setup

1. **Crea il repository su GitHub** (pubblico) e carica questi file mantenendo
   la stessa struttura di cartelle.

2. **Aggiungi i Secrets** del repo:
   `Settings → Secrets and variables → Actions → New repository secret`

   | Nome | Valore |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | il token ottenuto da @BotFather |
   | `TELEGRAM_CHANNEL_ID` | `@nerdropdeals` |
   | `AMAZON_AFFILIATE_TAG` | il tuo tag Amazon Associates (es. `nerdrop-21`), quando lo avrai |

3. **Aggiungi il bot come amministratore** del canale @nerdropdeals, con
   permesso di pubblicare messaggi (Telegram → Canale → Amministratori →
   Aggiungi amministratore → cerca il tuo bot).

4. **Abilita le Actions** sul repo se non sono già attive di default
   (`Actions` tab → "I understand my workflows, go ahead and enable them").

5. Il workflow parte da solo ogni 5 minuti. Puoi anche lanciarlo a mano dalla
   tab **Actions → Monitor offerte NerDrop → Run workflow**, utile per i primi
   test senza aspettare il cron.

## Cosa verificare prima del primo run reale

I selettori CSS usati in `script/main.py` (dentro `scrape_categoria`) sono
indicativi: le pagine offerte di Amazon cambiano struttura piuttosto spesso.
Prima di affidarti al bot in automatico, conviene:

- lanciare lo script in locale (`python script/main.py`) puntando a una sola
  categoria, e stampare `offerte` per vedere se i dati estratti hanno senso;
- aggiustare i selettori guardando l'HTML reale della pagina (tasto destro →
  Ispeziona su un elemento offerta).

## Parametri regolabili

In cima a `script/main.py`:

- `SOGLIA_SCONTO_PERCENTUALE` — sconto minimo per notificare (default 30%)
- `PREZZO_MINIMO` — ignora prodotti sotto questa cifra (default 20€)
- `CATEGORIE` — dizionario nome → URL, aggiungine altre se vuoi ampliare

## Stato

Il file `data/notified.json` tiene traccia delle offerte già pubblicate, per
evitare di rimandare lo stesso post ogni 5 minuti. Il workflow lo ricommitta
automaticamente ad ogni run.
