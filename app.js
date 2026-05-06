const PAGE_SIZE = 100;
const LANGS = ["en", "fr", "de", "sv", "it"];

let allEntries = [];
let query = "";

async function loadData() {
  const resp = await fetch("data.json");
  allEntries = await resp.json();
  render();
}

function escapeHTML(str) {
  return str.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function highlight(str, q) {
  if (!q) return escapeHTML(str);
  const idx = str.toLowerCase().indexOf(q.toLowerCase());
  if (idx === -1) return escapeHTML(str);
  return escapeHTML(str.slice(0, idx)) +
    "<mark>" + escapeHTML(str.slice(idx, idx + q.length)) + "</mark>" +
    escapeHTML(str.slice(idx + q.length));
}

function matches(entry, q) {
  if (!q) return true;
  const lq = q.toLowerCase();
  if (entry.fi.toLowerCase().includes(lq)) return true;
  return LANGS.some(l => entry[l] && entry[l].toLowerCase().includes(lq));
}

function render() {
  const tbody = document.getElementById("tbody");
  const countEl = document.getElementById("count");
  const emptyEl = document.getElementById("empty");

  const filtered = allEntries.filter(e => matches(e, query));
  const shown = filtered.slice(0, PAGE_SIZE);

  if (filtered.length === 0) {
    tbody.innerHTML = "";
    emptyEl.hidden = false;
    countEl.textContent = "No results";
    return;
  }

  emptyEl.hidden = true;
  countEl.textContent = filtered.length === allEntries.length
    ? `${allEntries.length} words`
    : `${filtered.length} of ${allEntries.length} words`;

  tbody.innerHTML = shown.map(e => {
    const cells = LANGS.map(l =>
      e[l]
        ? `<td>${highlight(e[l], query)}</td>`
        : `<td class="missing">—</td>`
    ).join("");
    return `<tr><td>${highlight(e.fi, query)}</td>${cells}</tr>`;
  }).join("");
}

document.getElementById("search").addEventListener("input", e => {
  query = e.target.value.trim();
  render();
});

loadData();
