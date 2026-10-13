# Raw row schema (CSV, UTF-8 with header, one row per awarded product line; if only tender-level data exists, one row per tender)
country            El Salvador | Honduras
source_portal      e.g. World Bank Contract Awards, Global Fund PQR, UNOPS, UNGM, ISSS website, COMPRASAL (legacy), Wayback
buyer              buying institution / hospital / PR (principal recipient)
procedure_no       tender / contract / PO number as published
procedure_type     as published (e.g. Licitación Pública, RFQ, Direct contracting, PQR transaction)
tender_title       full tender / contract title as published (Spanish or English, verbatim)
item_description   the product line text, verbatim (blank if not published)
brand_model        brand / analyser / manufacturer if published
supplier           awarded supplier / distributor
manufacturer       if published separately from supplier
quantity           number only (blank if not published)
unit               e.g. pruebas, kits, cajas, units
unit_price         number only
total_awarded      number only (do NOT compute it unless qty and unit price are both published; if computed, say so in comments)
currency           USD / HNL / other ISO code as published
contract_type      comodato / pago por prueba / según demanda / contrato abierto / blank
duration           contract duration & extensions if published
publication_date   YYYY-MM-DD
award_date         YYYY-MM-DD (or signing / PO / transaction date; say which in comments)
status             Adjudicado / Contratado / Orden de compra / Open / Cancelled ...
funding            National / World Bank / IDB / Global Fund / PAHO / UN / other
source_link        direct URL to the record or document
comments           anything a reviewer needs (e.g. "date = PO date", "amount is contract total for whole lot")
