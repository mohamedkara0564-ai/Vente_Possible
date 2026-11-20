# ============================================================
# main.py — Point d'entrée du microservice Sales Advisor
# Framework : FastAPI
# Rôle : Exposer les routes REST, récupérer les données pays
#         via CountriesNow + World Bank API, puis appeler le service IA
# ============================================================

import asyncio
import logging
import time

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
import httpx
from ai_service import analyze_sales_type
from pdf_service import generate_sales_pdf

# Création de l'application FastAPI avec métadonnées
app = FastAPI(title="Sales Type Advisor", version="1.0.0")
logger = logging.getLogger(__name__)

# Montage du dossier "static" pour servir les fichiers HTML, CSS, JS
app.mount("/static", StaticFiles(directory="static"), name="static")

# URLs des APIs utilisées
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
    """Récupère une réponse JSON et la garde en mémoire pendant une heure."""
    cached = _country_data_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    async with _country_data_cache_lock:
        # Une autre requête a peut-être rempli le cache pendant l'attente.
        cached = _country_data_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        response = await client.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        _country_data_cache[cache_key] = (time.monotonic(), data)
        return data


# Modèle de données attendu dans le corps de la requête POST /api/analyze
class SalesRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_prompt: str = Field(default="", max_length=1000)
    country_name: str = Field(min_length=1, max_length=100)
    sale_type: str = Field(min_length=1, max_length=200)


# ---------------------------------------------------------------
# Fonction utilitaire : récupérer les données d'un pays
# Combine CountriesNow (drapeau, capitale, devise) et
# World Bank (région, niveau de revenu, population)
# ---------------------------------------------------------------
async def fetch_country_info(country_id: str) -> dict:
    """
    Récupère les informations d'un pays depuis CountriesNow et World Bank.
    Supporte le nom du pays ou le code ISO2.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:

        # --- Étape 1 : CountriesNow — infos de base ---
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

        # --- Étape 2 : World Bank — données macro-économiques ---
        # On utilise le code ISO2 pour la Banque Mondiale (plus fiable)
        wb_id = iso2 if iso2 else official_name

        # Données de base pays
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

        # Indicateurs : PIB par habitant et Pénétration Internet
        gdp_pc = "N/A"
        internet_users = "N/A"

        if iso2:
            try:
                # PIB par habitant (dernier point de données)
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

                # Pénétration Internet
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

        # --- Étape 3 : Population ---
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
# Route GET / — Sert la page principale de l'interface utilisateur
# ---------------------------------------------------------------
@app.get("/")
async def root():
    return FileResponse("static/index.html")


# ---------------------------------------------------------------
# Route GET /api/countries/search — Autocomplétion des pays
# Appelée en temps réel pendant la saisie (dès 2 caractères)
# Interroge CountriesNow et retourne jusqu'à 10 suggestions
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

            # Filtrer les pays dont le nom contient la saisie (insensible à la casse)
            query = q.lower()
            matches = [
                c for c in countries
                if query in c.get("name", "").lower()
            ]

            # Formater et retourner les 10 premiers résultats
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
# Route POST /api/analyze — Analyse principale
# Reçoit le pays et le type de vente, récupère les données du pays,
# appelle l'IA et retourne l'analyse complète
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

    # --- Étape 1 : Récupérer les informations détaillées du pays ---
    try:
        # On essaie d'utiliser l'ISO2 si fourni pour plus de précision
        lookup_name = request.country_iso2 if request.country_iso2 else request.country_name
        country_info = await fetch_country_info(lookup_name)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Échec de récupération des données pays")
        raise HTTPException(
            status_code=503,
            detail="Le service de données pays est temporairement indisponible."
        )

    # --- Étape 2 : Appeler le service IA pour l'analyse ---
    try:
        ai_result = await analyze_sales_type(
            user_prompt=request.user_prompt,
            country_name=country_info["name"]["common"],
            country_info=country_info,
            sale_type=request.sale_type
        )
    except Exception:
        logger.exception("Échec du service d'analyse IA")
        raise HTTPException(
            status_code=503,
            detail="Le service d'analyse est temporairement indisponible."
        )

    # --- Étape 3 : Construire et retourner la réponse finale ---
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
# Route POST /api/download-pdf — Génération de PDF
# Reçoit les données d'analyse et retourne le fichier PDF
# ---------------------------------------------------------------
@app.post("/api/download-pdf")
async def download_pdf(data: dict):
    try:
        pdf_content = generate_sales_pdf(data)
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=analyse_{data['country']['name']}.pdf"
            }
        )
    except Exception as e:
        logger.exception("Échec de génération du PDF")
        raise HTTPException(status_code=500, detail="Erreur lors de la génération du PDF.")


# Point d'entrée pour lancer le serveur directement avec python main.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
