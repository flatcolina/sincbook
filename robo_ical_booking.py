#!/usr/bin/env python3
import requests, json, os, logging
from icalendar import Calendar
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

APARTAMENTOS = {
    "cHqxxuHbV8dyusWgXYHG": {
        "ical": "https://ical.booking.com/v1/export?t=b77bf048-e971-43d4-a998-ff69a4f3a86d",
        "nome": "Eco Resort Praia dos Carneiros - Flat Colina",
        "origem": "booking"
    }
}

cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
if not cred_json:
    logging.error("FIREBASE_CREDENTIALS_JSON não definida.")
    raise SystemExit
cred_dict = json.loads(cred_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

def process_ap(ap_id, cfg):
    url = cfg["ical"]
    logging.info(f"Baixando iCal para {ap_id}")
    data = requests.get(url).text
    cal = Calendar.from_ical(data)

    def normalize_date(value):
        if hasattr(value, "date"):
            return value.date()
        return value

    for comp in cal.walk():
        if comp.name != "VEVENT":
            continue

        dtstart = comp.get("DTSTART").dt
        dtend = comp.get("DTEND").dt

        checkin = normalize_date(dtstart)
        checkout = normalize_date(dtend)
        noites = (checkout - checkin).days

        nome = comp.get("SUMMARY")
        reserva_id = f"{ap_id}_{checkin}"

        doc = {
            "apartamentoId": ap_id,
            "origem": cfg["origem"],
            "nome": nome,
            "dataCheckin": checkin.isoformat(),
            "dataCheckout": checkout.isoformat(),
            "noites": noites,
            "telefone": None,
            "valor_total": None,
            "status": "pendente",
            "criadoEm": firestore.SERVER_TIMESTAMP
        }

        logging.info(f"Gravando reserva {reserva_id}")
        db.collection("reservas_airbnb").document(reserva_id).set(doc, merge=True)

def main():
    for ap_id, cfg in APARTAMENTOS.items():
        try:
            process_ap(ap_id, cfg)
        except Exception as e:
            logging.error(f"Erro {ap_id}: {e}")

if __name__ == "__main__":
    main()
