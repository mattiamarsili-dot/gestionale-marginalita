# Backup automatico — Setup (Priorità 1.1)

Obiettivo: ricevere ogni settimana, **senza fare nulla**, un backup completo dei
dati di Neon. Elimina la dipendenza dal ricordarsi di scaricarlo a mano e copre
oltre i 7 giorni di Neon PITR.

Come funziona: [backup_auto.py](backup_auto.py) genera il JSON completo (via
[backup.py](backup.py), leggendo Neon da `DATABASE_URL`) e lo invia come allegato
via email. Lo scheduler è una **GitHub Action gratuita**
([.github/workflows/backup-settimanale.yml](.github/workflows/backup-settimanale.yml))
che gira ogni domenica.

---

## Setup una-tantum (~10 minuti)

### 1. Crea una "password per le app" di Gmail
Serve perché Gmail non accetta la password normale via SMTP.
1. Vai su https://myaccount.google.com/security → attiva la **verifica in due passaggi** (se non già attiva).
2. Vai su https://myaccount.google.com/apppasswords → crea una password app (nome: "Backup Gestionale").
3. Copia la password di 16 caratteri che appare (la userai come `SMTP_PASSWORD`).

### 2. Aggiungi i Secret su GitHub
Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
Crea questi secret:

| Nome | Valore |
|---|---|
| `DATABASE_URL` | la connection string di Neon (`postgresql://...`) |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `mattia.marsili@gmail.com` |
| `SMTP_PASSWORD` | la password app di 16 caratteri del punto 1 |
| `BACKUP_EMAIL_TO` | `mattia.marsili@gmail.com` (o un altro indirizzo) |

### 3. Prova subito (senza aspettare domenica)
GitHub → tab **Actions** → **Backup settimanale** → **Run workflow**.
Dopo ~1 minuto controlla la posta: deve arrivare `backup_AAAAMMGG_HHMMSS.json` in allegato.

Fatto. Da qui in poi arriva da solo ogni domenica.

---

## Come ripristinare da uno di questi backup
```bash
cd "/Users/mattiamarsili/Desktop/Progetti Code/Gestionale Marginalità"
# salva l'allegato dalla mail, poi:
python restore.py backup_AAAAMMGG_HHMMSS.json     # in locale (SQLite)
# per ripristinare su Neon: metti DATABASE_URL nel .env e rilancia
```

---

## Note
- **Nessuna nuova dipendenza**: lo script usa solo la libreria standard Python
  (`smtplib`) più ciò che il progetto già installa.
- **Senza email configurata**: `backup_auto.py` scrive comunque una copia locale
  ruotata (`BACKUP_KEEP`, default 8) — utile lanciandolo dal Mac. In GitHub
  Actions la copia locale è effimera, quindi lì l'email è la destinazione vera.
- **Privacy**: i dati contengono informazioni sanitarie. Restano nella tua casella
  Gmail e nei Secret del tuo repository (privato). Non finiscono in chiaro nei log.
- **Alternativa allo scheduler**: al posto della GitHub Action puoi usare un
  **Render Cron Job** (a pagamento) con start command `python backup_auto.py` e le
  stesse variabili d'ambiente. La GitHub Action è preferita perché gratuita e
  indipendente da Render.

---

## Variabili d'ambiente riconosciute da `backup_auto.py`

| Variabile | Default | Uso |
|---|---|---|
| `DATABASE_URL` | — | se presente → backup di Neon; altrimenti SQLite locale |
| `SMTP_HOST` | vuoto | server SMTP; se vuoto l'email è saltata |
| `SMTP_PORT` | `587` | `587` = STARTTLS, `465` = SSL |
| `SMTP_USER` / `SMTP_PASSWORD` | vuoti | credenziali SMTP |
| `BACKUP_EMAIL_TO` | vuoto | destinatario; se vuoto l'email è saltata |
| `BACKUP_EMAIL_FROM` | = `SMTP_USER` | mittente |
| `BACKUP_DIR` | `.` | cartella della copia locale |
| `BACKUP_KEEP` | `8` | quante copie locali tenere (rotazione) |
