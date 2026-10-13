"""HonduCompras SICC historical process search (ASP.NET WebForms postback)."""
import html
import re
import sys

import requests
import urllib3

urllib3.disable_warnings()
URL = "http://sicc.honducompras.gob.hn/HC/procesos/busquedahistorico.aspx"
P = "ctl00$cphCuerpo$wpParametros$"


def hidden(s):
    return {m.group(1): html.unescape(m.group(2)) for m in
            re.finditer(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', s)}


def search(entity="", desc="", start="", end="", stage="", fuente=""):
    ses = requests.Session()
    ses.headers["User-Agent"] = "Mozilla/5.0"
    r = ses.get(URL, timeout=60, verify=False)
    form = hidden(r.text)
    form.update({
        P + "ddlEntidades": entity, P + "ddlUC": "", P + "ddlModalidad": "", P + "ddlTipoAdquisicion": "",
        P + "ddlEtapas": stage, P + "ddlFteFinanciamiento": fuente, P + "txtObjetoCompra": desc, P + "txtExpediente": "",
        P + "wdInicio_hidden": start, P + "wdFin_hidden": end,
        "ctl00_cphCuerpo_wpParametros_wdInicio_input": start, "ctl00_cphCuerpo_wpParametros_wdFin_input": end,
        P + "btnBuscar": "Buscar",
    })
    r2 = ses.post(URL, data=form, timeout=120, verify=False)
    return ses, r2.text


if __name__ == "__main__":
    ent = sys.argv[1] if len(sys.argv) > 1 else "51"
    desc = sys.argv[2] if len(sys.argv) > 2 else ""
    ses, s = search(entity=ent, desc=desc)
    open("sicc_out.html", "w", encoding="utf-8").write(s)
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S)))
    txt = html.unescape(txt)
    i = txt.find("Expediente ONCAE")
    print(len(s), "bytes")
    print(txt[i:i + 3000])
