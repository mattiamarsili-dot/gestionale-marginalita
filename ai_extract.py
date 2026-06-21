"""
Estrazione dei dati anagrafici da un messaggio in testo libero (Claude API).

Una singola chiamata `messages` con output strutturato (JSON schema): in ingresso
il testo disordinato incollato dall'operatore, in uscita i campi del cliente già
normalizzati (date aaaa-mm-gg, CF maiuscolo, provincia sigla a 2 lettere).

La chiamata avviene solo se ANTHROPIC_API_KEY è impostata: senza chiave la
funzione "Incolla messaggio" resta disattivata (nessun costo). Import del SDK
`anthropic` fatto in modo lazy così l'app parte anche senza il pacchetto.
"""
import json

from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

# Campi estratti (sottoinsieme di CLIENTE_FIELDS + tutore). Tutti stringhe;
# vuoto = dato non presente nel messaggio.
CAMPI_ESTRAZIONE = [
    "cognome", "nome", "codice_fiscale", "data_nascita", "luogo_nascita",
    "provincia", "residenza_via", "residenza_civico", "residenza_citta",
    "residenza_cap", "telefono", "email", "asl", "centro", "medico_curante",
    "documento_tipo_numero",
]


def _schema() -> dict:
    props = {c: {"type": "string"} for c in CAMPI_ESTRAZIONE}
    return {
        "type": "object",
        "properties": props,
        "required": CAMPI_ESTRAZIONE,
        "additionalProperties": False,
    }


def _system_prompt(centri, asl_opzioni) -> str:
    centri_txt = ", ".join(centri or [])
    asl_txt = ", ".join(asl_opzioni or [])
    return (
        "Sei un assistente di un gestionale sanitario italiano. Estrai i dati "
        "anagrafici del paziente dal messaggio. Regole:\n"
        "- Date sempre nel formato aaaa-mm-gg (es. 1950-03-12).\n"
        "- Codice fiscale in MAIUSCOLO, 16 caratteri.\n"
        "- provincia = sigla a 2 lettere maiuscole (es. RM).\n"
        "- residenza_via = solo via/piazza senza il numero; residenza_civico = il numero.\n"
        "- residenza_citta = comune di residenza.\n"
        f"- centro: se nel testo compare un centro riconducibile a uno di questi, usa "
        f"esattamente quella voce: {centri_txt}. Altrimenti riporta il nome così com'è.\n"
        f"- asl: se riconducibile, usa una di queste sigle: {asl_txt}. Altrimenti riporta com'è.\n"
        "- Se un campo non è presente, lascia stringa vuota. Non inventare dati."
    )


def estrai_dati_cliente(testo: str, centri=None, asl_opzioni=None) -> dict:
    """Restituisce un dict {campo: valore} con i dati estratti dal testo.
    Solleva RuntimeError se la chiave API non è configurata."""
    testo = (testo or "").strip()
    if not testo:
        return {c: "" for c in CAMPI_ESTRAZIONE}
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY non configurata")

    import anthropic  # lazy: l'app parte anche senza il pacchetto installato

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=_system_prompt(centri, asl_opzioni),
        messages=[{"role": "user", "content": testo}],
        output_config={"format": {"type": "json_schema", "schema": _schema()}},
    )
    raw = next((b.text for b in resp.content if b.type == "text"), "{}")
    dati = json.loads(raw)
    # Normalizzazioni difensive lato server
    out = {c: (dati.get(c) or "").strip() for c in CAMPI_ESTRAZIONE}
    out["codice_fiscale"] = out["codice_fiscale"].upper()
    out["provincia"] = out["provincia"].upper()[:2]
    return out
