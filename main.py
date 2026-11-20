# ============================================================
# main.py â€” Point d'entrÃ©e du microservice Sales Advisor
# Framework : FastAPI
# RÃ´le : Exposer les routes REST, rÃ©cupÃ©rer les donnÃ©es pays
#         via CountriesNow + World Bank API, puis appeler le service IA
# ============================================================

import asyncio
import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
import httpx
from ai_service import analyze_sales_type

# CrÃ©ation de l'application FastAPI avec mÃ©tadonnÃ©es
app = FastAPI(title="Sales Type Advisor", version="1.0.0")
logger = logging.getLogger(__name__)

# Montage du dossier "static" pour servir les fichiers HTML, CSS, JS
app.mount("/static", StaticFiles(directory="static"), name="static")

# URLs des APIs utilisÃ©es
COUNTRIESNOW_URL = "https://countriesnow.space/api/v0.1"
WORLDBANK_URL    = "https://api.worldbank.org/v2"
CACHE_TTL_SECONDS = 60 * 60
_country_data_cache: dict[str, tuple[float, dict]] = {}
_country_data_cache_lock = asyncio.Lock()


async def fetch_json_cached(
    client: httpx.AsyncClient,
    cache_key: str,
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 8.0,
) -> dict | list:
    """RÃ©cupÃ¨re une rÃ©ponse JSON et la garde en mÃ©moire pendant une heure."""
    cached = _country_data_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    async with _country_data_cache_lock:
        # Une autre requÃªte a peut-Ãªtre rempli le cache pendant l'attente.
        cached = _country_data_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        response = await client.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        _country_data_cache[cache_key] = (time.monotonic(), data)
        return data


# ModÃ¨le de donnÃ©es attendu dans le corps de la requÃªte POST /api/analyze
class SalesRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_prompt: str = Field(default="", max_length=1000)
    country_name: str = Field(min_length=1, max_length=100)
    sale_type: str = Field(min_length=1, max_length=200)


# ---------------------------------------------------------------
# Fonction utilitaire : rÃ©cupÃ©rer les donnÃ©es d'un pays
# Combine CountriesNow (drapeau, capitale, devise) et
# World Bank (rÃ©gion, niveau de revenu, population)
# ---------------------------------------------------------------
async def fetch_country_info(country_id: str) -> dict:
    """
    RÃ©cupÃ¨re les informations d'un pays depuis CountriesNow et World Bank.
    Supporte le nom du pays ou le code ISO2.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:

        # --- Ã‰tape 1 : CountriesNow â€” infos de base ---
        cn_data_raw = await fetch_json_cached(
            client,
            "countriesnow_info_detail",
            f"{COUNTRIESNOW_URL}/countries/info",
            params={"returns": "name,capital,currency,flag,unicodeFlag,dialCode,iso2"},
            timeout=8.0,
        )
        cn_data = cn_data_raw.get("data", [])

        # Recherche par code ISO2 ou nom
        cn_country = next(
            (c for c in cn_data if (c.get("iso2", "").lower() == country_id.lower() or
                                   c.get("name", "").lower() == country_id.lower())),
            None
        )

        if cn_country is None:
            # Essai avec correspondance partielle si c'est un nom
            cn_country = next(
                (c for c in cn_data if country_id.lower() in c.get("name", "").lower()),
                None
            )

        if cn_country is None:
            raise HTTPException(status_code=404, detail=f"Pays '{country_id}' introuvable.")

        official_name = cn_country["name"]
        iso2 = cn_country.get("iso2", "")

        # --- Ã‰tape 2 : World Bank â€” donnÃ©es macro-Ã©conomiques ---
        # On utilise le code ISO2 pour la Banque Mondiale (plus fiable)
        wb_id = iso2 if iso2 else official_name

        # DonnÃ©es de base pays
        wb_countries_raw = await fetch_json_cached(
            client,
            "worldbank_countries",
            f"{WORLDBANK_URL}/country",
            params={"format": "json", "per_page": 300},
            timeout=8.0,
        )
        wb_countries = wb_countries_raw[1] if isinstance(wb_countries_raw, list) and len(wb_countries_raw) > 1 else []

        wb_country = next(
            (c for c in wb_countries if (c.get("id", "").lower() == wb_id.lower() or
                                        c.get("name", "").lower() == official_name.lower())),
            {}
        )

        # Indicateurs : PIB par habitant et PÃ©nÃ©tration Internet
        gdp_pc = "N/A"
        internet_users = "N/A"

        if iso2:
            try:
                # PIB par habitant (dernier point de donnÃ©es)
                gdp_raw = await fetch_json_cached(
                    client,
                    f"wb_gdp_{iso2}",
                    f"{WORLDBANK_URL}/country/{iso2}/indicator/NY.GDP.PCAP.CD",
                    params={"format": "json", "per_page": 5},
                    timeout=5.0
                )
                if isinstance(gdp_raw, list) and len(gdp_raw) > 1 and gdp_raw[1]:
                    for val in gdp_raw[1]:
                        if val.get("value") is not None:
                            gdp_pc = val["value"]
                            break

                # PÃ©nÃ©tration Internet
                net_raw = await fetch_json_cached(
                    client,
                    f"wb_net_{iso2}",
                    f"{WORLDBANK_URL}/country/{iso2}/indicator/IT.NET.USER.ZS",
                    params={"format": "json", "per_page": 5},
                    timeout=5.0
                )
                if isinstance(net_raw, list) and len(net_raw) > 1 and net_raw[1]:
                    for val in net_raw[1]:
                        if val.get("value") is not None:
                            internet_users = val["value"]
                            break
            except Exception:
                pass

        # --- Ã‰tape 3 : Population ---
        population = 0
        try:
            pop_raw = await fetch_json_cached(
                client,
                "countriesnow_population",
                f"{COUNTRIESNOW_URL}/countries/population",
                timeout=8.0,
            )
            pop_data = pop_raw.get("data", [])
            pop_entry = next(
                (c for c in pop_data if c.get("country", "").lower() == official_name.lower() or
                                       c.get("iso3", "").lower() == wb_country.get("id", "").lower()),
                None
            )
            if pop_entry:
                counts = pop_entry.get("populationCounts", [])
                if counts:
                    population = sorted(counts, key=lambda x: x["year"])[-1]["value"]
        except Exception:
            pass

        return {
            "name": {"common": official_name, "official": official_name},
            "region": wb_country.get("region", {}).get("value", "N/A") if wb_country else "N/A",
            "subregion": wb_country.get("adminregion", {}).get("value", "") if wb_country else "",
            "population": population,
            "languages": {},
            "currencies": {
                cn_country.get("currency", "N/A"): {
                    "name": cn_country.get("currency", "N/A"),
                    "symbol": cn_country.get("currency", "")
                }
            },
            "capital": [cn_country.get("capital", "N/A")],
            "flags": {
                "emoji": cn_country.get("unicodeFlag", ""),
                "png": cn_country.get("flag", ""),
            },
            "income_level": wb_country.get("incomeLevel", {}).get("value", "N/A") if wb_country else "N/A",
            "gdp_pc": gdp_pc,
            "internet_users": internet_users,
            "dial_code": cn_country.get("dialCode", ""),
            "iso2": iso2
        }


# ---------------------------------------------------------------
# Route GET / â€” Sert la page principale de l'interface utilisateur
# ---------------------------------------------------------------
@app.get("/")
async def root():
    return FileResponse("static/index.html")


# ---------------------------------------------------------------
# Route GET /api/countries/search â€” AutocomplÃ©tion des pays
# AppelÃ©e en temps rÃ©el pendant la saisie (dÃ¨s 2 caractÃ¨res)
# Interroge CountriesNow et retourne jusqu'Ã  10 suggestions
# ---------------------------------------------------------------
@app.get("/api/countries/search")
async def search_countries(q: str):
    # Ne pas interroger l'API si la saisie est trop courte
    if len(q) < 2:
        return []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            payload = await fetch_json_cached(
                client,
                "countriesnow_info_search",
                f"{COUNTRIESNOW_URL}/countries/info",
                params={"returns": "name,capital,flag,unicodeFlag"},
                timeout=5.0,
            )
            countries = payload.get("data", [])

            # Filtrer les pays dont le nom contient la saisie (insensible Ã  la casse)
            query = q.lower()
            matches = [
                c for c in countries
                if query in c.get("name", "").lower()
            ]

            # Formater et retourner les 10 premiers rÃ©sultats
            return [
                {
                    "name":     m["name"],
                    "official": m["name"],
                    "flag":     m.get("unicodeFlag", ""),
                    "iso2":     m.get("iso2", ""),
                    "code":     ""
                }
                for m in matches[:10]
            ]
        except Exception:
            return []


# ---------------------------------------------------------------
# Route POST /api/analyze â€” Analyse principale
# ReÃ§oit le pays et le type de vente, rÃ©cupÃ¨re les donnÃ©es du pays,
# appelle l'IA et retourne l'analyse complÃ¨te
# ---------------------------------------------------------------
class SalesRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_prompt: str = Field(default="", max_length=1000)
    country_name: str = Field(min_length=1, max_length=100)
    country_iso2: str | None = Field(default=None, min_length=2, max_length=2)
    sale_type: str = Field(min_length=1, max_length=200)


@app.post("/api/analyze")
async def analyze_sales(request: SalesRequest):

    # Validation des champs obligatoires
    if not request.country_name.strip():
        raise HTTPException(status_code=400, detail="Le nom du pays est requis.")
    if not request.sale_type.strip():
        raise HTTPException(status_code=400, detail="Le type de vente est requis.")

    # --- Ã‰tape 1 : RÃ©cupÃ©rer les informations dÃ©taillÃ©es du pays ---
    try:
        # On essaie d'utiliser l'ISO2 si fourni pour plus de prÃ©cision
        lookup_name = request.country_iso2 if request.country_iso2 else request.country_name
        country_info = await fetch_country_info(lookup_name)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Ã‰chec de rÃ©cupÃ©ration des donnÃ©es pays")
        raise HTTPException(
            status_code=503,
            detail="Le service de donnÃ©es pays est temporairement indisponible."
        )

    # --- Ã‰tape 2 : Appeler le service IA pour l'analyse ---
    try:
        ai_result = await analyze_sales_type(
            user_prompt=request.user_prompt,
            country_name=country_info["name"]["common"],
            country_info=country_info,
            sale_type=request.sale_type
        )
    except Exception:
        logger.exception("Ã‰chec du service d'analyse IA")
        raise HTTPException(
            status_code=503,
            detail="Le service d'analyse est temporairement indisponible."
        )

    # --- Ã‰tape 3 : Construire et retourner la rÃ©ponse finale ---
    return {
        "country": {
            "name":       country_info["name"]["common"],
            "official":   country_info["name"]["official"],
            "region":     country_info.get("region", "N/A"),
            "subregion":  country_info.get("subregion", "N/A"),
            "population": country_info.get("population", 0),
            "capital":    country_info.get("capital", ["N/A"])[0],
            "flag":       country_info.get("flags", {}).get("emoji", ""),
            "languages":  list(country_info.get("languages", {}).values()),
            "currencies": [
                c.get("name", "")
                for c in country_info.get("currencies", {}).values()
            ],
            "income_level": country_info.get("income_level", "N/A"),
            "gdp_pc": country_info.get("gdp_pc", "N/A"),
            "internet_users": country_info.get("internet_users", "N/A")
        },
        "sale_type": request.sale_type,
        "analysis":  ai_result
    }


# ---------------------------------------------------------------
# Route POST /api/download-pdf â€” GÃ©nÃ©ration de PDF
# ReÃ§oit les donnÃ©es d'analyse et retourne le fichier PDF
# ---------------------------------------------------------------
@app.post("/api/download-pdf")
async def download_pdf(request: Request):
    try:
        data = await request.json()
        pdf_content = generate_sales_pdf(data)
        country_name = data.get("country", {}).get("name", "rapport")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in country_name)
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=analyse_{safe_name}.pdf"
            }
        )
    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        logger.error("Ã‰chec de gÃ©nÃ©ration du PDF:\n%s", err_detail)
        raise HTTPException(status_code=500, detail=f"Erreur PDF : {str(e)}")


# Point d'entrÃ©e pour lancer le serveur directement avec python main.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)



