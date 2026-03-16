/* Seeder API — config, generation, polling */

let seederPolling = null;

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const data = await res.json();
    if (data.base_url) document.getElementById('seederUrl').value = data.base_url;
    if (data.key) document.getElementById('seederKey').value = data.key;
  } catch (e) { /* server not running or static mode */ }
}

async function saveConfig() {
  const btn = document.getElementById('btnSaveConfig');
  const base_url = document.getElementById('seederUrl').value;
  const key = document.getElementById('seederKey').value;
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url, key })
    });
    const data = await res.json();
    if (data.ok) {
      btn.textContent = '\u2713 Enregistr\u00e9';
      setTimeout(() => btn.textContent = 'Enregistrer la configuration', 2000);
    }
  } catch (e) {
    btn.textContent = '\u2717 Erreur';
    setTimeout(() => btn.textContent = 'Enregistrer la configuration', 2000);
  }
}

async function generateSessions() {
  const startDate = document.getElementById('seederDateStart').value;
  const endDate = document.getElementById('seederDateEnd').value;
  if (!startDate || !endDate) { setStatus('Veuillez renseigner les deux dates', 'error'); return; }
  if (startDate >= endDate) { setStatus('La date de fin doit \u00eatre post\u00e9rieure', 'error'); return; }
  try {
    const res = await fetch('/api/sessions/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start_date: startDate, end_date: endDate })
    });
    const data = await res.json();
    if (data.ok) startPolling();
    else if (data.error) setStatus(data.error, 'error');
  } catch (e) { setStatus('Impossible de contacter le serveur', 'error'); }
}

async function stopGeneration() {
  try { await fetch('/api/sessions/stop', { method: 'POST' }); } catch (e) {}
}

function startPolling() {
  if (seederPolling) clearInterval(seederPolling);
  seederPolling = setInterval(pollStatus, 800);
  pollStatus();
}

async function pollStatus() {
  try {
    const res = await fetch('/api/sessions/status');
    const data = await res.json();
    updateUI(data);
    if (!data.running && seederPolling) {
      clearInterval(seederPolling);
      seederPolling = null;
    }
  } catch (e) {}
}

function updateUI(data) {
  const btnGen = document.getElementById('btnGenerate');
  const btnStop = document.getElementById('btnStop');
  const progressFill = document.getElementById('seederProgressFill');
  const consoleEl = document.getElementById('seederConsole');

  btnGen.disabled = data.running;
  btnStop.disabled = !data.running;

  if (data.running) {
    setStatus(data.status_text || 'G\u00e9n\u00e9ration en cours\u2026', 'running');
  } else if (data.done) {
    setStatus(data.status_text || 'G\u00e9n\u00e9ration termin\u00e9e', 'done');
    document.getElementById('seederChecklist').style.opacity = '1';
  } else if (data.error) {
    setStatus(data.status_text || 'Erreur', 'error');
  } else {
    setStatus('En attente', '');
  }

  progressFill.style.width = (data.progress_pct || 0) + '%';
  progressFill.classList.toggle('running', data.running);

  if (data.output) {
    consoleEl.classList.add('visible');
    consoleEl.textContent = data.output
      .replace(/\x1b\[[0-9;]*m/g, '')
      .replace(/^PROGRESS:\d+$/gm, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
}

function setStatus(text, state) {
  const dot = document.getElementById('seederStatusDot');
  const txt = document.getElementById('seederStatusText');
  dot.className = 'seeder-status-dot' + (state ? ' ' + state : '');
  txt.textContent = text;
}
