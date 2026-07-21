# Piano di Recovery — Gestionale Marginalità

**URL produzione:** https://gestionale-marginalita.onrender.com  
**Repository:** https://github.com/mattiamarsili-dot/gestionale-marginalita  
**Database:** Neon PostgreSQL (neon.tech)  
**Hosting:** Render.com  

---

## Checklist rapida — sito non risponde

1. Apri https://gestionale-marginalita.onrender.com — attendi 60 secondi (Render free si "addormenta")
2. Se non si sveglia → vai su **Render → tuo servizio → Logs** per vedere l'errore
3. Se i log mostrano un crash → segui lo scenario corrispondente sotto

---

## Scenario A — Sito lento al primo accesso (normale)

**Causa:** Render free sospende il servizio dopo 15 minuti di inattività.  
**Soluzione:** Attendere 30-60 secondi al primo accesso della giornata. Nessuna azione richiesta.

**Soluzione permanente:** Configurare UptimeRobot (gratuito) per un ping ogni 5 minuti.

### Configurare UptimeRobot

1. Vai su https://uptimerobot.com → crea account gratuito
2. Clicca **Add New Monitor**
3. Imposta:
   - Monitor Type: **HTTP(s)**
   - Friendly Name: `Gestionale Marginalità`
   - URL: `https://gestionale-marginalita.onrender.com`
   - Monitoring Interval: **5 minutes**
4. Aggiungi la tua email per le notifiche
5. Clicca **Create Monitor**

Da questo momento il sito non si addormenterà più e riceverai email se va offline.

---

## Scenario B — App crashata / Internal Server Error

**Sintomi:** pagina bianca, errore 500, "Internal Server Error"

### Passo 1 — Leggi i log

Su Render → tuo servizio → **Logs**. Cerca righe rosse con `ERROR` o `Traceback`.

### Passo 2 — Rollback al commit precedente

Se il crash è avvenuto dopo un aggiornamento del codice:

1. Vai su Render → tuo servizio → **Events**
2. Trova il deploy precedente (quello che funzionava)
3. Clicca i tre puntini accanto a quel deploy → **Rollback to this deploy**

Oppure da terminale:

```bash
cd "/Users/mattiamarsili/Desktop/Progetti Code/Gestionale Marginalità"
git log --oneline   # trova il commit che funzionava
git revert HEAD     # annulla l'ultimo commit
git push
```

### Passo 3 — Verifica variabili d'ambiente

Su Render → **Environment** → controlla che siano presenti:

| Variabile | Deve essere impostata |
|---|---|
| `DATABASE_URL` | connection string Neon (postgresql://...) |
| `ACCESS_CODE` | codice di accesso |
| `SECRET_KEY` | chiave segreta |
| `DRIVE_FOLDER_ID` | ID cartella Google Drive |
| `GOOGLE_CREDENTIALS_JSON` | JSON service account su una riga |

Se manca `DATABASE_URL` l'app usa SQLite e perde tutti i dati cloud.

---

## Scenario C — Dati persi o corrotti

### Opzione 1 — Restore da backup Neon (automatico, 7 giorni)

1. Vai su https://neon.tech → tuo progetto `gestionale`
2. Clicca **Branches** → seleziona il branch principale
3. Clicca **Restore** → scegli il punto temporale desiderato
4. Conferma — Neon ripristina il database a quel momento

### Opzione 2 — Restore da backup locale (file JSON)

Se hai un file di backup (scaricato dall'app o generato con `backup.py`):

```bash
cd "/Users/mattiamarsili/Desktop/Progetti Code/Gestionale Marginalità"

# Restore in LOCALE (SQLite): basta lanciarlo
python3 restore.py backup_YYYYMMDD_HHMMSS.json

# Restore in PRODUZIONE (Neon): prima imposta DATABASE_URL nel file .env
```

Lo script ripristina **tutte le tabelle** del backup (clienti, pratiche,
preventivi, righe ausili, preset, motivazioni) e chiede conferma prima di
sovrascrivere. Riconosce anche i vecchi backup (formato pre-2026-06).

---

## Scenario D — Aggiornamento codice che rompe tutto

### Rollback immediato

```bash
cd "/Users/mattiamarsili/Desktop/Progetti Code/Gestionale Marginalità"
git log --oneline -10     # vedi gli ultimi 10 commit
git revert <hash-commit>  # es: git revert abc1234
git push
```

Render esegue automaticamente un nuovo deploy con il codice precedente.

---

## Come eseguire un backup

Il backup è un singolo file JSON con **tutte le tabelle** (clienti, pratiche,
preventivi, righe ausili, preset, motivazioni) e tutte le loro colonne.

### Modo 1 — Dall'app (consigliato, anche da telefono)

Clicca l'icona **☁︎ (scarica)** in alto a destra nella barra: scarica subito
`backup_AAAAMMGG_HHMMSS.json` con i dati **di produzione** (Neon). Salvalo dove
preferisci (Google Drive, email a te stesso, chiavetta).

**Consigliato:** un download a settimana e sempre prima di toccare il codice.

### Modo 2 — Da terminale (Mac)

```bash
cd "/Users/mattiamarsili/Desktop/Progetti Code/Gestionale Marginalità"
python3 backup.py          # backup del DB locale (SQLite)
# con DATABASE_URL nel .env → backup di produzione (Neon)
```

> **Reti di sicurezza attive, in ordine:**
> 1. **Neon PITR** — ripristino a qualsiasi istante degli ultimi 7 giorni (automatico).
> 2. **Backup JSON automatico** — ogni domenica via email, senza intervento
>    (GitHub Action + `backup_auto.py`). Setup in `BACKUP_AUTOMATICO.md`.
> 3. **Backup JSON manuale** — il download 1-click qui sopra, per snapshot al volo.
> 4. **Git** — il codice è su GitHub; i dati NO (i `backup_*.json` sono git-ignored apposta).

---

## Scenario E — Render sospende il servizio (piano gratuito)

Render può sospendere i servizi gratuiti in caso di inattività prolungata o superamento dei limiti.

**Soluzione rapida:**
1. Vai su Render → tuo servizio → clicca **Resume** se disponibile
2. Oppure clicca **Manual Deploy → Deploy latest commit**

**Soluzione permanente:** Upgrade a Render Starter ($7/mese) per un servizio sempre attivo.

---

## Contatti e risorse

| Servizio | URL | Uso |
|---|---|---|
| Render Dashboard | https://dashboard.render.com | deploy, log, variabili |
| Neon Dashboard | https://console.neon.tech | database, backup, restore |
| GitHub Repository | https://github.com/mattiamarsili-dot/gestionale-marginalita | codice sorgente |
| UptimeRobot | https://uptimerobot.com | monitoraggio disponibilità |

---

## Procedura aggiornamento codice (sicura)

Prima di ogni modifica al codice:

```bash
# 1. Backup dati
python3 backup.py

# 2. Fai le modifiche al codice

# 3. Testa in locale
python3 app.py

# 4. Pubblica
git add .
git commit -m "descrizione modifica"
git push
```

Render rileva il push e rideploya automaticamente in 1-2 minuti.
