// Front da POC: popula a dropdown de lotes e exibe os veículos do lote selecionado.
// Front e API ficam sob o mesmo domínio (CloudFront), então usamos caminhos relativos.

const API_BASE = "/api";

const els = {
  select: document.getElementById("lote-select"),
  refresh: document.getElementById("refresh"),
  status: document.getElementById("status"),
  table: document.getElementById("tabela"),
  tbody: document.querySelector("#tabela tbody"),
};

function setStatus(msg) {
  els.status.textContent = msg || "";
}

async function fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

async function carregarLotes() {
  setStatus("Carregando lotes...");
  els.select.innerHTML = "";
  try {
    const { lotes } = await fetchJson(`${API_BASE}/lotes`);
    if (!lotes || lotes.length === 0) {
      els.select.innerHTML = '<option value="">Nenhum lote disponível</option>';
      setStatus("Nenhum lote concluído ainda.");
      renderVeiculos([]);
      return;
    }
    els.select.innerHTML =
      '<option value="">Selecione um lote</option>' +
      lotes.map((l) => `<option value="${l}">${l}</option>`).join("");
    setStatus("");
  } catch (err) {
    setStatus(`Erro ao carregar lotes: ${err.message}`);
  }
}

async function carregarVeiculos(lote) {
  if (!lote) {
    renderVeiculos([]);
    return;
  }
  setStatus(`Carregando veículos do lote ${lote}...`);
  try {
    const { veiculos } = await fetchJson(`${API_BASE}/lotes/${encodeURIComponent(lote)}`);
    renderVeiculos(veiculos || []);
    setStatus(
      veiculos && veiculos.length
        ? `${veiculos.length} veículo(s).`
        : "Lote sem veículos."
    );
  } catch (err) {
    setStatus(`Erro ao carregar veículos: ${err.message}`);
    renderVeiculos([]);
  }
}

function renderVeiculos(veiculos) {
  els.tbody.innerHTML = veiculos
    .map(
      (v) =>
        `<tr><td>${v.lote}</td><td>${v.placa}</td><td>${v.ano_fabricacao}</td>` +
        `<td>${v.modelo}</td><td>${v.fabricante}</td></tr>`
    )
    .join("");
  els.table.hidden = veiculos.length === 0;
}

els.select.addEventListener("change", (e) => carregarVeiculos(e.target.value));
els.refresh.addEventListener("click", () => carregarVeiculos(els.select.value));

carregarLotes();
