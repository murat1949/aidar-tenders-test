# -*- coding: utf-8 -*-
"""
Aidar Tenders / Samruk techspec extractor v1.1 / TEST10L
Usage:
    python extract_samruk_techspec.py "Lot_4521598_2026-08-26.pdf"

Result:
    Creates JSON next to the PDF:
    Lot_4521598_2026-08-26.techspec.json

Notes:
- No Supabase keys are stored here.
- v1 is designed for text-based Samruk technical specification PDFs.
"""

from pathlib import Path
import re
import json
import sys

try:
    from pypdf import PdfReader
except ImportError:
    print("ERROR: package pypdf is not installed.")
    print("Install: python -m pip install pypdf")
    sys.exit(2)


def clean(s):
    if s is None:
        return None
    s = s.replace("\u00ad", "").replace("\u200b", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def one(pattern, text, flags=re.I | re.S):
    m = re.search(pattern, text, flags)
    return clean(m.group(1)) if m else None


def extract_text(pdf_path):
    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return clean("\n".join(pages))


def russian_part(text):
    # Samruk PDFs are often bilingual: Kazakh first, Russian later.
    # TEST10L fix: find the exact Russian section heading on its own line.
    # Do NOT use rfind(), because the phrase can occur later inside body text
    # (for example, "Настоящая техническая спецификация ..."), which would
    # cut off the real header containing the lot number.
    m = re.search(
        r"(?mi)^[ \t]*ТЕХНИЧЕСКАЯ СПЕЦИФИКАЦИЯ[ \t]*$",
        text,
    )
    if m:
        return text[m.start():]
    return text


def parse(pdf_path):
    raw = extract_text(pdf_path)
    text = russian_part(raw)

    lot_id = one(r"Лот\s*№.*?\(\s*[^,\)]*,\s*(\d+)\s*\)", text)
    procurement_no = one(r"по закупке\s+(\d+)", text)
    lot_name = one(r"Лот\s*№.*?\)\s*([^\n]+)", text)
    customer = one(r"Заказчик:\s*(.+?)(?:\nОрганизатор:|\n1\.)", text)
    organizer = one(r"Организатор:\s*(.+?)(?:\n1\.|\nКраткое описание)", text)

    short_desc = one(
        r"Наименование и краткая\s*характеристика\s*(.+?)(?:\nНаименование категории|\nДополнительная характеристика)",
        text
    )
    extra_desc = one(
        r"Дополнительная характеристика\s*(.+?)(?:\nКоличество|\nСаны)",
        text
    )
    quantity = one(r"Количество\s+([0-9][0-9.,]*)", text)
    unit = one(r"Единица измерения\s+([^\n]+)", text)
    delivery_place = one(r"Место поставки\s+(.+?)(?:\nУсловия поставки)", text)
    delivery_terms = one(r"Условия поставки\s+([^\n]+)", text)
    delivery_period = one(r"Срок поставки\s+(.+?)(?:\nУсловия оплаты)", text)
    payment_terms = one(r"Условия оплаты\s+(.+?)(?:\n2\.|\nОписание и требуемые)", text)

    tech_block = one(
        r"2\.\s*Описание и требуемые.*?характеристики\s*(.+?)(?:\n3\.\s*Технические стандарты|\Z)",
        text
    )

    # Common fields found in cartridge specs.
    ink_type = one(r"Тип чернил:\s*([^;\n]+)", text)
    color = one(r"Цвет:\s*([^;\n]+)", text)
    compatibility = one(r"Совместимость.*?:\s*([^;\n]+)", text)
    yield_volume = one(r"Производительность:\s*([^;\n]+)", text)
    purpose = one(r"Назначение:\s*([^;\n]+)", text)

    signed_by = one(r"Подписал\s+([^\n]+)", text)
    signed_date = one(r"Дата подписания\s+([0-9.]+)", text)

    # Normalize quantity as numeric when possible.
    quantity_num = None
    if quantity:
        try:
            quantity_num = float(quantity.replace(" ", "").replace(",", "."))
        except Exception:
            quantity_num = None

    result = {
        "source": "samruk",
        "source_pdf": pdf_path.name,
        "procurement_no": procurement_no,
        "lot_id": lot_id,
        "lot_name": lot_name,
        "customer": customer,
        "organizer": organizer,
        "short_description": short_desc,
        "additional_description": extra_desc,
        "quantity": quantity_num if quantity_num is not None else quantity,
        "unit": unit,
        "delivery_place": delivery_place,
        "delivery_terms": delivery_terms,
        "delivery_period": delivery_period,
        "payment_terms": payment_terms,
        "technical_requirements": tech_block,
        "parsed_fields": {
            "ink_type": ink_type,
            "color": color,
            "compatibility": compatibility,
            "yield_or_volume": yield_volume,
            "purpose": purpose,
        },
        "signed_by": signed_by,
        "signed_date": signed_date,
    }
    return result


def main():
    if len(sys.argv) < 2:
        print('Usage: python extract_samruk_techspec.py "Lot_4521598_2026-08-26.pdf"')
        sys.exit(1)

    pdf_path = Path(sys.argv[1]).expanduser().resolve()
    if not pdf_path.exists():
        print("ERROR: PDF not found:", pdf_path)
        sys.exit(1)

    data = parse(pdf_path)
    out_path = pdf_path.with_suffix(".techspec.json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("OK")
    print("PDF:", pdf_path.name)
    print("LOT:", data.get("lot_id"))
    print("CUSTOMER:", data.get("customer"))
    print("QUANTITY:", data.get("quantity"), data.get("unit"))
    print("DELIVERY:", data.get("delivery_place"))
    print("TERMS:", data.get("delivery_terms"), "|", data.get("delivery_period"))
    print("PAYMENT:", data.get("payment_terms"))
    print("COMPATIBILITY:", data.get("parsed_fields", {}).get("compatibility"))
    print("JSON:", out_path)


if __name__ == "__main__":
    main()
