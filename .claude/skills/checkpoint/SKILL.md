---
name: checkpoint
description: >
  Wrap-up della sessione da lanciare PRIMA di pulire la chat (/clear o /compact),
  per non perdere contesto e ripartire efficienti. Usalo quando l'utente dice
  "pulisci la chat", "facciamo checkpoint", "sto per fare /clear", o quando la
  conversazione è lunga e serve consolidare lo stato nella memoria.
---

# Checkpoint prima di pulire la chat

Obiettivo: la sessione nuova deve ripartire **senza ri-derivare nulla**. Tutto lo
stato utile va nella memoria del progetto (già caricata a ogni avvio), non in chat.

## Passi

1. **Cosa è cambiato in questa sessione** — elenca in 3-8 righe: commit fatti
   (hash + una riga), cosa è già deployato su Render, cosa è ancora locale/non
   applicato, decisioni prese con l'utente, gotcha scoperti.

2. **Aggiorna la memoria** (`.../memory/`):
   - Per ogni filone di lavoro tocca **un** file memoria (`type: project` o
     `feedback`), non crearne di nuovi se ne esiste già uno sul tema.
   - Aggiorna la riga corrispondente in `MEMORY.md` (una riga, con hook).
   - Converti le date relative in assolute. Niente contenuto in `MEMORY.md`.
   - Cancella o correggi le voci diventate false.

3. **Lavori aperti** — scrivi nel file memoria del filone la sezione
   "Aperto / prossimi passi" con: cosa manca, comandi esatti da lanciare
   (es. `DATABASE_URL=… python import_fatturati_agosto.py --apply`), file/riga
   di riferimento.

4. **Verifica rapida**: `git status` pulito o solo file attesi? Push fatto se
   l'utente lo voleva? Test/deploy citati con esito reale (no "dovrebbe
   funzionare").

5. **Riepiloga all'utente in ≤10 righe** cosa è stato salvato in memoria e
   conferma che può fare `/clear` senza perdere niente. Se qualcosa NON è
   sicuro riprenderlo dopo il clear, dillo esplicitamente.

## Regole

- Non riscrivere in chat spiegazioni lunghe: se serve ricordarle, vanno in memoria.
- Non committare né deployare in questo passo se non richiesto: è solo consolidamento.
- Skill breve per definizione: niente analisi nuove, solo salvataggio stato.
