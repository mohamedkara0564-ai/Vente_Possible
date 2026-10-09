# ============================================================
# ai_service.py — Service d'analyse IA via Google Gemini
# Rôle : Construire le prompt, appeler l'API Gemini et
#         retourner une analyse structurée en JSON
# ============================================================

import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# Initialiser le client Gemini avec la clé API
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


async def analyze_sales_type(
    user_prompt: str,
    country_name: str,
    country_info: dict,
    sale_type: str
) -> dict:
    """
    Analyse la viabilité d'un type de vente dans un pays donné.

    Paramètres:
        user_prompt   : contexte optionnel fourni par l'utilisateur
        country_name  : nom du pays (ex: "France")
        country_info  : dictionnaire de données du pays (RestCountries)
        sale_type     : type de vente à analyser (ex: "e-commerce")

    Retourne:
        dict avec success_rate, failure_rate, favorable, analysis,
        key_factors, recommendation, risks, opportunities
    """

    # --- Construction du contexte pays à injecter dans le prompt ---
    currencies = ', '.join(
        [c.get('name', '') for c in country_info.get('currencies', {}).values()]
    ) if country_info.get('currencies') else 'N/A'

    languages = ', '.join(country_info.get('languages', {}).values()) \
        if country_info.get('languages') else 'N/A'

    country_context = f"""
Pays: {country_name}
Région: {country_info.get('region', 'N/A')}
Sous-région: {country_info.get('subregion', 'N/A')}
Population: {country_info.get('population', 0):,}
Niveau de revenu: {country_info.get('income_level', 'N/A')}
Capitale: {country_info.get('capital', ['N/A'])[0] if country_info.get('capital') else 'N/A'}
Monnaies: {currencies}
Langues: {languages}
"""

    # --- Construction du prompt envoyé à Gemini ---
    # On impose un format JSON strict pour pouvoir parser la réponse facilement
    prompt = f"""Tu es un expert en stratégie commerciale internationale et en analyse de marchés.
Analyse la viabilité du type de vente suivant dans le pays indiqué.

Contexte du pays:
{country_context}

Type de vente à analyser: {sale_type}

Question de l'utilisateur: {user_prompt}

Réponds UNIQUEMENT en JSON valide (sans markdown, sans backticks) avec cette structure exacte:
{{
  "success_rate": <nombre entier entre 0 et 100>,
  "failure_rate": <nombre entier entre 0 et 100>,
  "favorable": <true ou false>,
  "analysis": "<analyse détaillée en 3-4 phrases>",
  "key_factors": ["<facteur 1>", "<facteur 2>", "<facteur 3>"],
  "recommendation": "<recommandation concrète en 2-3 phrases>",
  "risks": ["<risque 1>", "<risque 2>"],
  "opportunities": ["<opportunité 1>", "<opportunité 2>"]
}}
Important: success_rate + failure_rate doit être égal à 100."""

    # --- Stratégie de fallback sur les modèles Gemini ---
    # Si le quota d'un modèle est épuisé (erreur 429), on passe au suivant
    models_fallback = [
        "gemini-2.0-flash-lite",  # Modèle léger, quota free tier séparé
        "gemini-2.5-flash",       # Modèle plus puissant en secours
        "gemini-flash-latest",    # Alias vers la dernière version flash disponible
    ]

    last_error = None
    response = None

    for model_name in models_fallback:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,              # Faible température = réponses plus déterministes
                    response_mime_type="application/json"  # Force Gemini à répondre en JSON pur
                )
            )
            break  # Succès : on sort de la boucle de fallback
        except Exception as e:
            last_error = e
            continue  # Quota épuisé ou erreur : on essaie le modèle suivant

    # Si tous les modèles ont échoué, on remonte la dernière erreur
    if response is None:
        raise last_error

    # Parser la réponse JSON de Gemini et la retourner comme dictionnaire Python
    result = json.loads(response.text)
    return result
