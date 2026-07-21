# Piano d'azione — Miglioramento criticità

> Ordinato per priorità (rapporto rischio-ridotto / sforzo). Ogni intervento ha
> obiettivo, passi concreti, sforzo stimato e criterio di "fatto".
> Stato: creato il 2026-07-21.

---

## 🔴 Priorità 1 — Sicurezza dei dati (chiude l'unico buco reale)

### 1.1 Automatizzare il backup JSON — ✅ CODICE PRONTO (manca setup Secret)
**Perché prima di tutto:** oggi oltre i 7 giorni di Neon PITR il recupero dipende
dal ricordarti di cliccare. Questo elimina la dipendenza umana.
- **Implementato:**
  - [backup_auto.py](backup_auto.py) — genera il JSON completo di Neon, lo invia via
    email (SMTP) e tiene una copia locale ruotata (`BACKUP_KEEP`, default 8).
  - [.github/workflows/backup-settimanale.yml](.github/workflows/backup-settimanale.yml)
    — scheduler gratuito: gira ogni domenica + lancio manuale.
  - Testato in locale: generazione, rotazione e gestione errori SMTP.
- **Resta da fare (utente, ~10 min):** creare i Secret GitHub e la password app Gmail —
  guida in [BACKUP_AUTOMATICO.md](BACKUP_AUTOMATICO.md).
- **Fatto quando:** arriva un backup via email senza intervento, 2 settimane di fila.

### 1.2 Ruotare la password Neon esposta — ⛔ AZIONE UTENTE
- **Passi:** Neon Console → reset password → aggiornare `DATABASE_URL` su Render → verificare riconnessione.
- **Sforzo:** ~15 min · **Fatto quando:** vecchia stringa non più valida e sito online.

---

## 🔴 Priorità 2 — Test sulla logica dei margini (protegge il denaro)

### 2.1 Suite minima su `calcola_margine` e scaglioni provvigione
- **Passi:**
  1. Aggiungere `pytest`.
  2. `tests/test_margine.py`: `calcola_margine` (solo ASL, ASL+privato, ricavi=0), soglie provvigione (16/17/18% attorno a 250k/350k), struttura 10%.
  3. `tests/test_range_date.py`: `_calcola_range`, `_calcola_range_intervallo`, `_parse_ym` (mesi a cavallo d'anno, intervallo invertito).
- **Sforzo:** ~3-4 ore · **Fatto quando:** `pytest` verde con i casi limite sulle soglie.

---

## 🟡 Priorità 3 — Robustezza sicurezza web (basso costo, buon ritorno)

### 3.1 Irrobustire il cookie di sessione
- **Passi:** in `app.py` dopo `app.secret_key`: `SESSION_COOKIE_SECURE=True`,
  `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"`, `PERMANENT_SESSION_LIFETIME`.
- **Sforzo:** ~15 min · **Fatto quando:** in prod il cookie è Secure/HttpOnly.

### 3.2 Protezione CSRF sui POST
- **Opzione A (completa):** `flask-wtf` `CSRFProtect` + token nei form.
- **Opzione B (leggera):** affidarsi a `SameSite=Lax` + token custom sulle azioni distruttive.
- **Raccomandazione:** B ora (mono-utente), A se entrano più operatori.
- **Sforzo:** A ~3 ore / B ~1 ora · **Fatto quando:** i POST distruttivi rifiutano richieste cross-site.

---

## 🟡 Priorità 4 — Correttezza monetaria

### 4.1 Migrare importi da `REAL`/float a `NUMERIC`/Decimal
> ⚠️ Cambio schema su DB in produzione: farlo DOPO la Priorità 1.
- **Passi:**
  1. Backup completo prima di toccare nulla.
  2. `ALTER COLUMN ... TYPE NUMERIC(10,2)` idempotente in `migrate_db()`; su SQLite gestire in Python con `Decimal`.
  3. Verificare `calcola_margine` e i template.
- **Sforzo:** ~4-5 ore (distruttivo) · **Fatto quando:** i totali coincidono al centesimo pre/post.

---

## 🟢 Priorità 5 — Manutenibilità a lungo termine

### 5.1 Spezzare `app.py` (2285 righe) in Blueprint
- **Passi:** `blueprints/` con `pratiche.py`, `clienti.py`, `moduli.py`, `drive.py`, `api.py`;
  `app.py` diventa bootstrap + `register_blueprint`. Migrazione incrementale, una area alla volta.
- **Sforzo:** ~1-2 giorni distribuiti · **Fatto quando:** `app.py` < ~300 righe.

### 5.2 Pulizia repository
- **Passi:** spostare `import_fatturati_giugno.py` e `sync_clienti_to_neon.py` in `scripts/`;
  rimuovere `.db` di backup e `server.log` dalla working dir (già git-ignored).
- **Sforzo:** ~30 min · **Fatto quando:** root pulita.

---

## Sequenza consigliata
1. **Settimana 1:** 1.1 + 1.2 → poi 2.1.
2. **Settimana 2:** 3.1 + 3.2B + 5.2.
3. **Quando c'è tempo:** 4.1 (con backup pronti) e 5.1 (refactor incrementale).

> Regola d'oro: **backup automatico (1.1) prima di 4.1 e 5.1** — sono gli unici
> interventi che toccano schema/struttura in modo potenzialmente distruttivo.
