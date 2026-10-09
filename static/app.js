// ============================================================
// app.js — Logique frontend du microservice Sales Advisor
// Rôle : Autocomplétion des pays, soumission du formulaire,
//        affichage et animation des résultats
// ============================================================

// --- Références aux éléments du DOM ---
const countryInput  = document.getElementById('countryInput');   // Champ saisie pays
const dropdown      = document.getElementById('countryDropdown'); // Liste autocomplétion
const saleTypeInput = document.getElementById('saleTypeInput');   // Champ type de vente
const form          = document.getElementById('analysisForm');    // Formulaire principal
const submitBtn     = document.getElementById('submitBtn');       // Bouton analyser
const btnText       = document.getElementById('btnText');         // Texte du bouton
const btnLoader     = document.getElementById('btnLoader');       // Spinner du bouton
const errorBox      = document.getElementById('errorBox');        // Zone d'erreur
const resultSection = document.getElementById('resultSection');   // Section résultats

// Timer pour le debounce de l'autocomplétion
let debounceTimer = null;
// Mémorise le pays sélectionné via le dropdown (vs saisie libre)
let selectedCountry = '';


// ============================================================
// AUTOCOMPLÉTION DES PAYS
// ============================================================

// Écoute chaque frappe dans le champ pays
countryInput.addEventListener('input', () => {
  const q = countryInput.value.trim();
  selectedCountry = ''; // Réinitialiser la sélection à chaque nouvelle frappe

  clearTimeout(debounceTimer);

  // Ne pas appeler l'API si moins de 2 caractères
  if (q.length < 2) { hideDropdown(); return; }

  // Attendre 300ms après la dernière frappe avant d'appeler l'API (debounce)
  debounceTimer = setTimeout(() => fetchCountries(q), 300);
});

// Appel à l'API backend pour récupérer les suggestions de pays
async function fetchCountries(q) {
  try {
    const res = await fetch(`/api/countries/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    renderDropdown(data);
  } catch {
    hideDropdown(); // En cas d'erreur réseau, fermer le dropdown silencieusement
  }
}

// Affiche les suggestions dans la liste déroulante
function renderDropdown(countries) {
  dropdown.innerHTML = '';

  if (!countries.length) { hideDropdown(); return; }

  countries.forEach(c => {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.innerHTML = `<span>${c.flag}</span><span>${c.name}</span>`;

    // Au clic sur une suggestion : remplir le champ et fermer le dropdown
    li.addEventListener('mousedown', (e) => {
      e.preventDefault(); // Empêche le blur du champ avant la sélection
      countryInput.value = c.name;
      selectedCountry = c.name;
      hideDropdown();
    });

    dropdown.appendChild(li);
  });

  dropdown.classList.remove('hidden');
}

// Ferme le dropdown
function hideDropdown() { dropdown.classList.add('hidden'); }

// Ferme le dropdown si on clique en dehors du champ pays
document.addEventListener('click', (e) => {
  if (!e.target.closest('.form-group')) hideDropdown();
});

// Quand le champ perd le focus : fermer le dropdown et mémoriser la valeur saisie
countryInput.addEventListener('blur', () => {
  setTimeout(hideDropdown, 150); // Délai pour laisser le mousedown se déclencher
  if (!selectedCountry) selectedCountry = countryInput.value.trim();
});


// ============================================================
// SOUMISSION DU FORMULAIRE
// ============================================================

form.addEventListener('submit', async (e) => {
  e.preventDefault(); // Empêcher le rechargement de la page
  hideError();

  // Récupérer les valeurs des champs
  const country  = selectedCountry || countryInput.value.trim();
  const saleType = saleTypeInput.value.trim();

  // Générer automatiquement le prompt envoyé à l'IA
  const prompt = `Analyse le type de vente "${saleType}" pour le pays suivant.`;

  // Validation côté client
  if (!country || !saleType) {
    showError('Veuillez remplir tous les champs.');
    return;
  }

  // Afficher le spinner et cacher les anciens résultats
  setLoading(true);
  resultSection.classList.add('hidden');

  try {
    // Appel à l'API backend
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_prompt: prompt,
        country_name: country,
        sale_type: saleType
      })
    });

    const data = await res.json();

    // Si le serveur retourne une erreur HTTP, afficher le message
    if (!res.ok) throw new Error(data.detail || 'Erreur serveur');

    // Afficher les résultats
    renderResult(data);

  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false); // Toujours retirer le spinner
  }
});


// ============================================================
// AFFICHAGE DES RÉSULTATS
// ============================================================

function renderResult(data) {
  const { country, sale_type, analysis } = data;

  // --- Informations sur le pays ---
  document.getElementById('countryFlag').textContent     = country.flag || '🌐';
  document.getElementById('countryName').textContent     = country.name;
  document.getElementById('countryOfficial').textContent = country.official;
  document.getElementById('metaRegion').textContent      = `${country.region} — ${country.subregion}`;
  document.getElementById('metaCapital').textContent     = country.capital;
  // Formatage de la population avec séparateur de milliers français
  document.getElementById('metaPopulation').textContent  = country.population.toLocaleString('fr-FR');
  document.getElementById('metaLanguages').textContent   = country.languages.join(', ') || 'N/A';
  document.getElementById('metaCurrencies').textContent  = country.currencies.join(', ') || 'N/A';
  document.getElementById('saleTypeLabel').textContent   = sale_type;

  // --- Animation des cercles SVG de pourcentage ---
  animateCircle('successArc', analysis.success_rate);
  animateCircle('failureArc', analysis.failure_rate);
  document.getElementById('successValue').textContent = `${analysis.success_rate}%`;
  document.getElementById('failureValue').textContent = `${analysis.failure_rate}%`;

  // --- Badge favorable / défavorable ---
  const badge = document.getElementById('favorableBadge');
  if (analysis.favorable) {
    badge.textContent = '✅ Ce type de vente est favorable dans ce pays';
    badge.className = 'favorable-badge yes'; // Style vert
  } else {
    badge.textContent = '❌ Ce type de vente est peu favorable dans ce pays';
    badge.className = 'favorable-badge no';  // Style rouge
  }

  // --- Textes de l'analyse et de la recommandation ---
  document.getElementById('analysisText').textContent       = analysis.analysis;
  document.getElementById('recommendationText').textContent = analysis.recommendation;

  // --- Listes dynamiques ---
  renderList('opportunitiesList', analysis.opportunities || []);
  renderList('risksList', analysis.risks || []);
  renderList('factorsList', analysis.key_factors || []);

  // Afficher la section et scroller jusqu'à elle
  resultSection.classList.remove('hidden');
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Génère les éléments <li> d'une liste à partir d'un tableau de chaînes
function renderList(id, items) {
  const ul = document.getElementById(id);
  ul.innerHTML = items.map(i => `<li>${i}</li>`).join('');
}

// ============================================================
// ANIMATION DES CERCLES SVG
// Principe : on manipule strokeDashoffset pour "dessiner"
// progressivement l'arc en fonction du pourcentage
// Circonférence = 2 × π × rayon = 2 × π × 50 ≈ 314.16
// ============================================================
function animateCircle(arcId, percent) {
  const circ = 2 * Math.PI * 50; // Circonférence totale du cercle (r=50)
  const arc = document.getElementById(arcId);

  arc.style.strokeDasharray  = circ;  // Longueur totale du trait
  arc.style.strokeDashoffset = circ;  // Départ à 0% (arc invisible)

  // Double requestAnimationFrame pour forcer le navigateur à appliquer
  // l'état initial avant de lancer la transition CSS
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      // Réduire l'offset pour "remplir" l'arc jusqu'au pourcentage voulu
      arc.style.strokeDashoffset = circ - (circ * percent / 100);
    });
  });
}


// ============================================================
// FONCTIONS UTILITAIRES
// ============================================================

// Active ou désactive l'état de chargement du bouton
function setLoading(state) {
  submitBtn.disabled = state;
  btnText.textContent = state ? 'Analyse en cours...' : 'Analyser';
  btnLoader.classList.toggle('hidden', !state); // Affiche/cache le spinner
}

// Affiche un message d'erreur dans la zone dédiée
function showError(msg) {
  errorBox.textContent = `⚠️ ${msg}`;
  errorBox.classList.remove('hidden');
}

// Cache la zone d'erreur
function hideError() { errorBox.classList.add('hidden'); }
