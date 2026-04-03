/**
 * Logica do dashboard principal (TCC v1.0).
 */

let paginaAtual = 1;
const LIMITE = 20;

document.addEventListener("DOMContentLoaded", () => {
    carregarResumo();
    carregarContratos();

    document.getElementById("btn-filtrar").addEventListener("click", () => {
        paginaAtual = 1;
        carregarContratos();
    });

    document.querySelectorAll("#filtro-valor-min, #filtro-valor-max").forEach(el => {
        el.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                paginaAtual = 1;
                carregarContratos();
            }
        });
    });

    // Clique nos cards de risco aplica filtro automaticamente
    document.getElementById("alto-risco")?.closest(".card")?.addEventListener("click", () => {
        document.getElementById("filtro-risco").value = "alto";
        paginaAtual = 1;
        carregarContratos();
    });
    document.getElementById("medio-risco")?.closest(".card")?.addEventListener("click", () => {
        document.getElementById("filtro-risco").value = "medio";
        paginaAtual = 1;
        carregarContratos();
    });
    document.getElementById("baixo-risco")?.closest(".card")?.addEventListener("click", () => {
        document.getElementById("filtro-risco").value = "baixo";
        paginaAtual = 1;
        carregarContratos();
    });
});


function getFiltros() {
    return {
        valorMin:    document.getElementById("filtro-valor-min").value,
        valorMax:    document.getElementById("filtro-valor-max").value,
        nivelRisco:  document.getElementById("filtro-risco").value,
        ordem:       document.getElementById("filtro-ordem").value,
        pagina:      paginaAtual,
        limite:      LIMITE,
    };
}


function formatarValor(v) {
    if (!v && v !== 0) return "-";
    return v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}


function formatarData(d) {
    if (!d) return "-";
    return new Date(d).toLocaleDateString("pt-BR");
}


async function carregarResumo() {
    try {
        const data = await fetchDashboardResumo();
        document.getElementById("total-contratos").textContent = data.total_contratos.toLocaleString("pt-BR");

        // Score medio
        var scoreEl = document.getElementById("score-medio");
        if (scoreEl) {
            scoreEl.textContent = data.score_medio != null ? data.score_medio.toFixed(4) : "–";
        }

        // Distribuicao de risco
        var altoEl  = document.getElementById("alto-risco");
        var medioEl = document.getElementById("medio-risco");
        var baixoEl = document.getElementById("baixo-risco");
        if (altoEl)  altoEl.textContent  = data.alto_risco  != null ? data.alto_risco.toLocaleString("pt-BR")  : "–";
        if (medioEl) medioEl.textContent = data.medio_risco != null ? data.medio_risco.toLocaleString("pt-BR") : "–";
        if (baixoEl) baixoEl.textContent = data.baixo_risco != null ? data.baixo_risco.toLocaleString("pt-BR") : "–";
    } catch (error) {
        console.error("Erro ao carregar resumo:", error);
        document.getElementById("total-contratos").textContent = "0";
        var scoreEl = document.getElementById("score-medio");
        if (scoreEl) scoreEl.textContent = "0.00";
    }
}


async function carregarContratos() {
    const loading = document.getElementById("loading");
    const tbody = document.getElementById("contratos-body");

    loading.classList.add("visible");
    tbody.innerHTML = "";

    try {
        const data = await fetchContratos(getFiltros());
        renderizarTabela(data.contratos);
        renderizarPaginacao(data.pagina, data.total_paginas, data.total);
    } catch (error) {
        console.error("Erro ao carregar contratos:", error);
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="empty-state">
                    <p>Erro ao carregar contratos. Verifique se a API esta rodando.</p>
                </td>
            </tr>`;
    } finally {
        loading.classList.remove("visible");
    }
}


function renderizarTabela(contratos) {
    const tbody = document.getElementById("contratos-body");

    if (!contratos || contratos.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="empty-state">
                    <p>Nenhum contrato encontrado</p>
                </td>
            </tr>`;
        return;
    }

    contratos.forEach((c) => {
        const tr = document.createElement("tr");

        const orgaoNome    = c.orgao     ? (c.orgao.sigla || c.orgao.nome) : "-";
        const fornecedorNome = c.fornecedor ? c.fornecedor.nome : "-";
        const objeto       = c.objeto ? (c.objeto.length > 50 ? c.objeto.substring(0, 50) + "..." : c.objeto) : "-";
        const valor        = formatarValor(c.valor);

        // Badge de risco
        const nivel = c.nivel_risco || null;
        let badgeHtml;
        if (!nivel) {
            badgeHtml = `<span class="badge-risco sem-score">–</span>`;
        } else if (nivel === "alto") {
            badgeHtml = `<span class="badge-risco alto">● Alto</span>`;
        } else if (nivel === "medio") {
            badgeHtml = `<span class="badge-risco medio">● Medio</span>`;
        } else {
            badgeHtml = `<span class="badge-risco baixo">● Baixo</span>`;
        }

        // Score
        const scoreHtml = c.score_anomalia != null
            ? `<span class="score-cell">${c.score_anomalia.toFixed(4)}</span>`
            : `<span class="score-cell" style="opacity:0.35">–</span>`;

        tr.innerHTML = `
            <td>${c.id}</td>
            <td title="${orgaoNome}">${orgaoNome}</td>
            <td title="${fornecedorNome}">${fornecedorNome.length > 30 ? fornecedorNome.substring(0, 30) + "..." : fornecedorNome}</td>
            <td title="${c.objeto || ""}">${objeto}</td>
            <td>R$ ${valor}</td>
            <td>${formatarData(c.data_inicio)}</td>
            <td>${formatarData(c.data_fim)}</td>
            <td>${badgeHtml}</td>
            <td>${scoreHtml}</td>
            <td>
                <button class="btn btn-primary btn-small" onclick="verDetalhe(${c.id})">Ver</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}


function renderizarPaginacao(paginaAtualResp, totalPaginas, total) {
    const container = document.getElementById("paginacao");
    container.innerHTML = "";

    if (totalPaginas <= 1) return;

    const btnAnterior = document.createElement("button");
    btnAnterior.textContent = "Anterior";
    btnAnterior.disabled = paginaAtualResp <= 1;
    btnAnterior.addEventListener("click", () => {
        paginaAtual = paginaAtualResp - 1;
        carregarContratos();
    });
    container.appendChild(btnAnterior);

    const inicio = Math.max(1, paginaAtualResp - 2);
    const fim = Math.min(totalPaginas, paginaAtualResp + 2);

    for (let i = inicio; i <= fim; i++) {
        const btn = document.createElement("button");
        btn.textContent = i;
        if (i === paginaAtualResp) btn.classList.add("active");
        btn.addEventListener("click", () => {
            paginaAtual = i;
            carregarContratos();
        });
        container.appendChild(btn);
    }

    if (fim < totalPaginas) {
        if (fim < totalPaginas - 1) {
            const dots = document.createElement("span");
            dots.textContent = "...";
            dots.className = "pag-dots";
            container.appendChild(dots);
        }
        const btnUltima = document.createElement("button");
        btnUltima.textContent = totalPaginas;
        btnUltima.addEventListener("click", () => {
            paginaAtual = totalPaginas;
            carregarContratos();
        });
        container.appendChild(btnUltima);
    }

    const btnProximo = document.createElement("button");
    btnProximo.textContent = "Proximo";
    btnProximo.disabled = paginaAtualResp >= totalPaginas;
    btnProximo.addEventListener("click", () => {
        paginaAtual = paginaAtualResp + 1;
        carregarContratos();
    });
    container.appendChild(btnProximo);

    const info = document.createElement("span");
    info.style.marginLeft = "0.75rem";
    info.style.color = "var(--text-muted)";
    info.style.fontSize = "0.8rem";
    info.textContent = `${total} contratos`;
    container.appendChild(info);
}


function verDetalhe(id) {
    window.location.href = `pages/contratos.html?id=${id}`;
}
