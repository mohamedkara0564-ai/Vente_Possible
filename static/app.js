// ============================================================
// app.js €” Logique frontend du microservice Sales Advisor
// RÃ´le : Autocomplétion des pays, soumission du formulaire,
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
let currentAnalysisData = null;

// Timer pour le debounce de l'autocomplétion
let debounceTimer = null;
// Mémorise le pays sélectionné via le dropdown (vs saisie libre)
let selectedCountry = '';
let activeCountryIndex = -1;


// ============================================================
// AUTOCOMPLÃ‰TION DES PAYS
// ============================================================

// Ã‰coute chaque frappe dans le champ pays
countryInput.addEventListener('input', () => {
  const q = countryInput.value.trim();
  selectedCountry = ''; // Réinitialiser la sélection Ã  chaque nouvelle frappe
  countryInput.removeAttribute('aria-activedescendant');

  clearTimeout(debounceTimer);

  // Ne pas appeler l'API si moins de 2 caractères
  if (q.length < 2) { hideDropdown(); return; }

  // Attendre 300ms après la dernière frappe avant d'appeler l'API (debounce)
  debounceTimer = setTimeout(() => fetchCountries(q), 300);
});

// Appel Ã  l'API backend pour récupérer les suggestions de pays
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
  dropdown.replaceChildren();
  activeCountryIndex = -1;

  if (!countries.length) {
    hideDropdown();
    return;
  }

  countries.forEach((country, index) => {
    const li = document.createElement('li');
    li.id = `country-option-${index}`;
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', 'false');
    li.dataset.countryName = country.name || '';

    const flag = document.createElement('span');
    flag.textContent = country.flag || '';

    const name = document.createElement('span');
    name.textContent = country.name || '';

    li.append(flag, name);

    li.addEventListener('mousedown', (event) => {
      event.preventDefault();
      selectCountry(country.name);
    });

    dropdown.appendChild(li);
  });

  dropdown.classList.remove('hidden');
  countryInput.setAttribute('aria-expanded', 'true');
}

// Ferme le dropdown
function hideDropdown() {
  dropdown.classList.add('hidden');
  countryInput.setAttribute('aria-expanded', 'false');
  countryInput.removeAttribute('aria-activedescendant');
  activeCountryIndex = -1;
}

function selectCountry(name) {
  countryInput.value = name || '';
  selectedCountry = name || '';
  hideDropdown();
}

function setActiveCountry(index) {
  const options = dropdown.querySelectorAll('[role="option"]');
  if (!options.length) return;

  activeCountryIndex = (index + options.length) % options.length;
  options.forEach((option, optionIndex) => {
    const isActive = optionIndex === activeCountryIndex;
    option.classList.toggle('active', isActive);
    option.setAttribute('aria-selected', String(isActive));
  });

  const activeOption = options[activeCountryIndex];
  countryInput.setAttribute('aria-activedescendant', activeOption.id);
  activeOption.scrollIntoView({ block: 'nearest' });
}

countryInput.addEventListener('keydown', (event) => {
  if (dropdown.classList.contains('hidden')) return;

  if (event.key === 'ArrowDown') {
    event.preventDefault();
    setActiveCountry(activeCountryIndex + 1);
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    setActiveCountry(activeCountryIndex - 1);
  } else if (event.key === 'Enter' && activeCountryIndex >= 0) {
    event.preventDefault();
    const activeOption = dropdown.querySelectorAll('[role="option"]')[activeCountryIndex];
    selectCountry(activeOption.dataset.countryName);
  } else if (event.key === 'Escape') {
    hideDropdown();
  }
});

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
  e.preventDefault(); // EmpÃªcher le rechargement de la page
  hideError();

  // Récupérer les valeurs des champs
  const country  = selectedCountry || countryInput.value.trim();
  const saleType = saleTypeInput.value.trim();

  // Générer automatiquement le prompt envoyé Ã  l'IA
  const prompt = `Analyse le type de vente "${saleType}" pour le pays suivant.`;

  // Validation cÃ´té client
  if (!country || !saleType) {
    showError('Veuillez remplir tous les champs.');
    return;
  }

  // Afficher le spinner et cacher les anciens résultats
  setLoading(true);
  resultSection.classList.add('hidden');

  try {
    // Appel Ã  l'API backend
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
    currentAnalysisData = data;

  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false); // Toujours retirer le spinner
  }
});

// Télécharge le rapport correspondant Ã  la dernière analyse affichée.
pdfDownloadBtn?.addEventListener('click', async () => {
  if (!currentAnalysisData) return;

  pdfDownloadBtn.disabled = true;
  pdfDownloadBtn.setAttribute('aria-busy', 'true');
  pdfButtonLabel.textContent = 'Préparation du PDF€¦';
  pdfStatus.textContent = 'Génération du rapport en cours€¦';
  pdfStatus.classList.remove('error', 'success');

  try {
    const res = await fetch('/api/download-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentAnalysisData)
    });

    if (!res.ok) {
      let message = 'Erreur lors de la génération du PDF.';
      try {
        const errData = await res.json();
        message = errData.detail || message;
      } catch {
        // Conserver le message générique si le serveur n'a pas répondu en JSON.
      }
      throw new Error(message);
    }

    if (!res.headers.get('content-type')?.includes('application/pdf')) {
      throw new Error('Le serveur n€™a pas renvoyé un fichier PDF valide.');
    }

    const blob = await res.blob();
    if (!blob.size) throw new Error('Le fichier PDF reçu est vide.');

    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    const countryName = currentAnalysisData.country.name;
    link.href = url;
    link.download = `analyse_${countryName.replace(/[^\w-]/g, '_')}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
    pdfStatus.textContent = 'Le téléchargement du rapport a démarré.';
    pdfStatus.classList.add('success');
  } catch (err) {
    pdfStatus.textContent = `Ã‰chec du téléchargement : ${err.message}`;
    pdfStatus.classList.add('error');
  } finally {
    pdfDownloadBtn.disabled = false;
    pdfDownloadBtn.removeAttribute('aria-busy');
    pdfButtonLabel.textContent = 'Télécharger le rapport';
  }
});


// ============================================================
// AFFICHAGE DES RÃ‰SULTATS
// ============================================================

function renderResult(data) {
  const { country, sale_type, analysis } = data;

  // --- Informations sur le pays ---
  document.getElementById('countryFlag').textContent     = country.flag || 'ðŸŒ';
  document.getElementById('countryName').textContent     = country.name;
  document.getElementById('countryOfficial').textContent = country.official;
  document.getElementById('metaRegion').textContent      = `${country.region} €” ${country.subregion}`;
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

  // Afficher la section et scroller jusqu'Ã  elle
  resultSection.classList.remove('hidden');
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Génère les éléments <li> d'une liste Ã  partir d'un tableau de chaÃ®nes
function renderList(id, items) {
  const ul = document.getElementById(id);
  ul.replaceChildren();

  items.forEach((item) => {
    const li = document.createElement('li');
    li.textContent = String(item);
    ul.appendChild(li);
  });
}

// ============================================================
// ANIMATION DES CERCLES SVG
// Principe : on manipule strokeDashoffset pour "dessiner"
// progressivement l'arc en fonction du pourcentage
// Circonférence = 2 Ã— Ï€ Ã— rayon = 2 Ã— Ï€ Ã— 50 ‰ˆ 314.16
// ============================================================
function animateCircle(arcId, percent) {
  const circ = 2 * Math.PI * 50; // Circonférence totale du cercle (r=50)
  const arc = document.getElementById(arcId);

  arc.style.strokeDasharray  = circ;  // Longueur totale du trait
  arc.style.strokeDashoffset = circ;  // Départ Ã  0% (arc invisible)

  // Double requestAnimationFrame pour forcer le navigateur Ã  appliquer
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
  errorBox.textContent = `š ï¸ ${msg}`;
  errorBox.classList.remove('hidden');
}

// Cache la zone d'erreur
function hideError() { errorBox.classList.add('hidden'); }





