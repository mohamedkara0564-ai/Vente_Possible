# ============================================================
# main.py — Point d'entrée du microservice Sales Advisor
# Framework : FastAPI
# Rôle : Exposer les routes REST, récupérer les données pays
#         via CountriesNow + World Bank API, puis appeler le service IA
# ============================================================

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx
from ai_service import analyze_sales_type

# Création de l'application FastAPI avec métadonnées
app = FastAPI(title="Sales Type Advisor", version="1.0.0")

# Montage du dossier "static" pour servir les fichiers HTML, CSS, JS
app.mount("/static", StaticFiles(directory="static"), name="static")

# URLs des APIs utilisées
COUNTRIESNOW_URL = "https://countriesnow.space/api/v0.1"
WORLDBANK_URL    = "https://api.worldbank.org/v2"


# Modèle de données attendu dans le corps de la requête POST /api/analyze
class SalesRequest(BaseModel):
    user_prompt: str = ""      # Contexte optionnel (généré automatiquement si vide)
    country_name: str          # Nom du pays saisi par l'utilisateur
    sale_type: str             # Type de vente saisi par l'utilisateur


# ---------------------------------------------------------------
# Fonction utilitaire : récupérer les données d'un pays
# Combine CountriesNow (drapeau, capitale, devise) et
# World Bank (région, niveau de revenu, population)
# ---------------------------------------------------------------
async def fetch_country_info(country_name: str) -> dict:
    """
    Récupère les informations d'un pays depuis CountriesNow et World Bank.
    Retourne un dictionnaire normalisé compatible avec ai_service.py.
    Lève une HTTPException si le pays est introuvable.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:

        # --- Étape 1 : CountriesNow — infos de base (drapeau, capitale, devise) ---
        cn_response = await client.get(
            f"{COUNTRIESNOW_URL}/countries/info",
            params={"returns": "name,capital,currency,flag,unicodeFlag,dialCode"},
            timeout=8.0
        )
        cn_response.raise_for_status()
        cn_data = cn_response.json().get("data", [])

        # Recherche insensible à la casse
        cn_country = next(
            (c for c in cn_data if c.get("name", "").lower() == country_name.lower()),
            None
        )
        if cn_country is None:
            # Essai avec correspondance partielle
            cn_country = next(
                (c for c in cn_data if country_name.lower() in c.get("name", "").lower()),
                None
            )
        if cn_country is None:
            raise HTTPException(
                status_code=404,
                detail=f"Pays '{country_name}' introuvable."
            )

        # Nom officiel normalisé depuis CountriesNow
        official_name = cn_country["name"]

        # --- Étape 2 : World Bank — région, sous-région, niveau de revenu ---
        wb_response = await client.get(
            f"{WORLDBANK_URL}/country",
            params={"format": "json", "per_page": 300},
            timeout=8.0
        )
        wb_response.raise_for_status()
        wb_raw = wb_response.json()
        wb_countries = wb_raw[1] if isinstance(wb_raw, list) and len(wb_raw) > 1 else []

        wb_country = next(
            (c for c in wb_countries if c.get("name", "").lower() == official_name.lower()),
            None
        )
        if wb_country is None:
            # Essai correspondance partielle
            wb_country = next(
                (c for c in wb_countries if official_name.lower() in c.get("name", "").lower()),
                {}
            )

        # --- Étape 3 : CountriesNow — population (dernière année disponible) ---
        population = 0
        try:
            pop_response = await client.get(
                f"{COUNTRIESNOW_URL}/countries/population",
                timeout=8.0
            )
            pop_response.raise_for_status()
            pop_data = pop_response.json().get("data", [])
            pop_entry = next(
                (c for c in pop_data if c.get("country", "").lower() == official_name.lower()),
                None
            )
            if pop_entry:
                counts = pop_entry.get("populationCounts", [])
                if counts:
                    # Prendre la valeur la plus récente
                    population = sorted(counts, key=lambda x: x["year"])[-1]["value"]
        except Exception:
            pass  # Population non critique, on continue sans

        # --- Assemblage du dictionnaire normalisé ---
        region    = wb_country.get("region", {}).get("value", "N/A") if wb_country else "N/A"
        subregion = wb_country.get("adminregion", {}).get("value", "") if wb_country else ""
        income    = wb_country.get("incomeLevel", {}).get("value", "N/A") if wb_country else "N/A"

        return {
            "name": {
                "common":   official_name,
                "official": official_name,
            },
            "region":    region,
            "subregion": subregion if subregion else region,
            "population": population,
            # ai_service attend {"code": {"name": "Nom langue"}} — on simplifie avec la devise comme proxy
            "languages":  {},
            "currencies": {
                cn_country.get("currency", "N/A"): {
                    "name":   cn_country.get("currency", "N/A"),
                    "symbol": cn_country.get("currency", "")
                }
            },
            "timezones": [],
            "capital": [cn_country.get("capital", "N/A")],
            "flags": {
                "emoji": cn_country.get("unicodeFlag", ""),
                "png":   cn_country.get("flag", ""),
            },
            # Champs supplémentaires pour enrichir l'analyse IA
            "income_level": income,
            "dial_code":    cn_country.get("dialCode", ""),
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
            response = await client.get(
                f"{COUNTRIESNOW_URL}/countries/info",
                params={"returns": "name,capital,flag,unicodeFlag"},
                timeout=5.0
            )
            if response.status_code != 200:
                return []

            countries = response.json().get("data", [])

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
@app.post("/api/analyze")
async def analyze_sales(request: SalesRequest):

    # Validation des champs obligatoires
    if not request.country_name.strip():
        raise HTTPException(status_code=400, detail="Le nom du pays est requis.")
    if not request.sale_type.strip():
        raise HTTPException(status_code=400, detail="Le type de vente est requis.")

    # --- Étape 1 : Récupérer les informations détaillées du pays ---
    try:
        country_info = await fetch_country_info(request.country_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Erreur lors de la récupération des données pays: {str(e)}"
        )

    # --- Étape 2 : Appeler le service IA pour l'analyse ---
    try:
        ai_result = await analyze_sales_type(
            user_prompt=request.user_prompt,
            country_name=country_info["name"]["common"],
            country_info=country_info,
            sale_type=request.sale_type
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erreur IA: {str(e)}")

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
        },
        "sale_type": request.sale_type,
        "analysis":  ai_result
    }


# Point d'entrée pour lancer le serveur directement avec python main.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
