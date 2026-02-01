/**
 * Willow API helpers
 */

const BASE = '';

export async function fetchStatus() {
  const res = await fetch(`${BASE}/api/status`);
  return res.json();
}

export async function fetchPersonas() {
  const res = await fetch(`${BASE}/api/personas`);
  return res.json();
}

export async function searchKnowledge(query, limit = 5) {
  const res = await fetch(`${BASE}/api/knowledge/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  return res.json();
}

export async function fetchGaps(limit = 10) {
  const res = await fetch(`${BASE}/api/knowledge/gaps?limit=${limit}`);
  return res.json();
}

export async function fetchStats() {
  const res = await fetch(`${BASE}/api/knowledge/stats`);
  return res.json();
}

export async function fetchCoherence() {
  const res = await fetch(`${BASE}/api/coherence`);
  return res.json();
}

export async function ingestFile(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/api/ingest`, { method: 'POST', body: form });
  return res.json();
}
