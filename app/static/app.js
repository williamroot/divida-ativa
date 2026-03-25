/* ===== Máscara de CNPJ ===== */

function mascaraCnpj(input) {
    let valor = input.value.replace(/\D/g, "");
    if (valor.length > 14) {
        valor = valor.slice(0, 14);
    }
    if (valor.length > 12) {
        valor = valor.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{1,2})/, "$1.$2.$3/$4-$5");
    } else if (valor.length > 8) {
        valor = valor.replace(/^(\d{2})(\d{3})(\d{3})(\d{1,4})/, "$1.$2.$3/$4");
    } else if (valor.length > 5) {
        valor = valor.replace(/^(\d{2})(\d{3})(\d{1,3})/, "$1.$2.$3");
    } else if (valor.length > 2) {
        valor = valor.replace(/^(\d{2})(\d{1,3})/, "$1.$2");
    }
    input.value = valor;
}

/* ===== Navegação por tabs ===== */

function trocarTab(nomeTab) {
    document.querySelectorAll(".tab").forEach(function (tab) {
        tab.classList.toggle("active", tab.dataset.tab === nomeTab);
    });
    document.querySelectorAll(".tab-content").forEach(function (conteudo) {
        conteudo.classList.toggle("active", conteudo.id === "tab-" + nomeTab);
    });
}

/* ===== Consulta individual ===== */

function consultarCnpj() {
    var cnpjInput = document.getElementById("cnpj");
    var cnpj = cnpjInput.value.trim();
    if (!cnpj) {
        mostrarErro("resultado", "Informe o CNPJ para consultar.");
        return;
    }

    var divResultado = document.getElementById("resultado");
    limparConteudo(divResultado);
    var carregando = document.createElement("div");
    carregando.className = "carregando";
    var spinner = document.createElement("span");
    spinner.className = "spinner";
    carregando.appendChild(spinner);
    carregando.appendChild(document.createTextNode(" Consultando..."));
    divResultado.appendChild(carregando);

    fetch("/api/consulta", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cnpj: cnpj, forcar: document.getElementById("forcar-busca").checked }),
    })
        .then(function (resposta) {
            if (!resposta.ok) {
                return resposta.json().then(function (dados) {
                    throw new Error(dados.detail || "Erro ao consultar o CNPJ.");
                });
            }
            return resposta.text();
        })
        .then(function (html) {
            /* Server-rendered Jinja2 partial from trusted endpoint */
            divResultado.innerHTML = html;
            carregarHistorico();
        })
        .catch(function (erro) {
            mostrarErro("resultado", erro.message);
        });
}

/* ===== Consulta em lote ===== */

var pollingIntervalId = null;

function consultarLote() {
    var textarea = document.getElementById("cnpjs-texto");
    var cnpjsTexto = textarea.value.trim();
    if (!cnpjsTexto) {
        mostrarErro("lote-tabela-container", "Informe ao menos um CNPJ.");
        return;
    }

    var cnpjs = cnpjsTexto
        .split("\n")
        .map(function (linha) {
            return linha.trim();
        })
        .filter(function (linha) {
            return linha.length > 0;
        });

    if (cnpjs.length === 0) {
        mostrarErro("lote-tabela-container", "Nenhum CNPJ válido encontrado.");
        return;
    }

    var progressoContainer = document.getElementById("progresso-container");
    var progressoTexto = document.getElementById("progresso-texto");
    var progressoBarra = document.getElementById("progresso-barra");
    var tabelaContainer = document.getElementById("lote-tabela-container");

    progressoContainer.style.display = "block";
    progressoTexto.textContent = "Enviando consulta em lote...";
    progressoBarra.style.width = "0%";
    limparConteudo(tabelaContainer);

    fetch("/api/consulta/lote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cnpjs: cnpjs }),
    })
        .then(function (resposta) {
            if (!resposta.ok) {
                return resposta.json().then(function (dados) {
                    throw new Error(dados.detail || "Erro ao enviar consulta em lote.");
                });
            }
            return resposta.json();
        })
        .then(function (dados) {
            var loteId = dados.id;
            progressoTexto.textContent = "Processando... 0%";
            iniciarPolling(loteId);
        })
        .catch(function (erro) {
            progressoContainer.style.display = "none";
            mostrarErro("lote-tabela-container", erro.message);
        });
}

function iniciarPolling(loteId) {
    if (pollingIntervalId) {
        clearInterval(pollingIntervalId);
    }

    pollingIntervalId = setInterval(function () {
        fetch("/api/consulta/lote/" + loteId + "/status")
            .then(function (resposta) {
                if (!resposta.ok) {
                    throw new Error("Erro ao verificar status do lote.");
                }
                return resposta.json();
            })
            .then(function (dados) {
                atualizarProgresso(dados);
                if (dados.status === "concluido" || dados.status === "erro") {
                    clearInterval(pollingIntervalId);
                    pollingIntervalId = null;
                    exibirResultadosLote(dados);
                    carregarHistorico();
                }
            })
            .catch(function (erro) {
                clearInterval(pollingIntervalId);
                pollingIntervalId = null;
                mostrarErro("lote-tabela-container", erro.message);
            });
    }, 2000);
}

function atualizarProgresso(dados) {
    var progressoTexto = document.getElementById("progresso-texto");
    var progressoBarra = document.getElementById("progresso-barra");
    var total = dados.total || 1;
    var processados = dados.processados || 0;
    var percentual = Math.round((processados / total) * 100);

    progressoBarra.style.width = percentual + "%";
    progressoTexto.textContent = "Processando... " + percentual + "% (" + processados + "/" + total + ")";

    if (dados.status === "concluido") {
        progressoTexto.textContent = "Concluído! " + processados + "/" + total + " processados.";
    } else if (dados.status === "erro") {
        progressoTexto.textContent = "Finalizado com erros. " + processados + "/" + total + " processados.";
    }
}

function exibirResultadosLote(dados) {
    var container = document.getElementById("lote-tabela-container");
    limparConteudo(container);

    if (!dados.resultados || dados.resultados.length === 0) {
        var p = document.createElement("p");
        p.className = "texto-centro";
        p.textContent = "Nenhum resultado encontrado.";
        container.appendChild(p);
        return;
    }

    var wrapper = document.createElement("div");
    wrapper.className = "tabela-responsiva";
    var tabela = document.createElement("table");
    tabela.className = "tabela";

    var thead = document.createElement("thead");
    var trHead = document.createElement("tr");
    ["CNPJ", "Nome", "CDAs", "Status"].forEach(function (titulo) {
        var th = document.createElement("th");
        th.textContent = titulo;
        trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    tabela.appendChild(thead);

    var tbody = document.createElement("tbody");
    dados.resultados.forEach(function (item) {
        var tr = document.createElement("tr");

        var tdCnpj = document.createElement("td");
        tdCnpj.textContent = item.cnpj || "\u2014";
        tr.appendChild(tdCnpj);

        var tdNome = document.createElement("td");
        tdNome.textContent = item.nome || "\u2014";
        tr.appendChild(tdNome);

        var tdCdas = document.createElement("td");
        tdCdas.textContent = item.total_cdas != null ? item.total_cdas : "\u2014";
        tr.appendChild(tdCdas);

        var tdStatus = document.createElement("td");
        var badge = document.createElement("span");
        var classeStatus = item.status === "concluido" ? "concluido" : item.status === "erro" ? "erro" : "pendente";
        badge.className = "badge badge-" + classeStatus;
        badge.textContent = item.status || "\u2014";
        tdStatus.appendChild(badge);
        tr.appendChild(tdStatus);

        tbody.appendChild(tr);
    });
    tabela.appendChild(tbody);
    wrapper.appendChild(tabela);
    container.appendChild(wrapper);
}

/* ===== Histórico ===== */

function carregarHistorico() {
    var corpo = document.getElementById("historico-corpo");

    fetch("/api/consultas/recentes")
        .then(function (resposta) {
            if (!resposta.ok) {
                throw new Error("Erro ao carregar histórico.");
            }
            return resposta.json();
        })
        .then(function (dados) {
            limparConteudo(corpo);

            if (!dados || dados.length === 0) {
                var tr = document.createElement("tr");
                var td = document.createElement("td");
                td.setAttribute("colspan", "3");
                td.className = "texto-centro";
                td.textContent = "Nenhuma consulta registrada.";
                tr.appendChild(td);
                corpo.appendChild(tr);
                return;
            }

            dados.forEach(function (item) {
                var tr = document.createElement("tr");

                var tdCnpj = document.createElement("td");
                tdCnpj.textContent = item.cnpj || "\u2014";
                tr.appendChild(tdCnpj);

                var tdStatus = document.createElement("td");
                var badge = document.createElement("span");
                var classeStatus = item.status === "concluido" ? "concluido" : item.status === "erro" ? "erro" : "pendente";
                badge.className = "badge badge-" + classeStatus;
                badge.textContent = item.status || "\u2014";
                tdStatus.appendChild(badge);
                tr.appendChild(tdStatus);

                var tdData = document.createElement("td");
                tdData.textContent = item.data || "\u2014";
                tr.appendChild(tdData);

                corpo.appendChild(tr);
            });
        })
        .catch(function () {
            limparConteudo(corpo);
            var tr = document.createElement("tr");
            var td = document.createElement("td");
            td.setAttribute("colspan", "3");
            td.className = "texto-centro";
            td.textContent = "Erro ao carregar histórico.";
            tr.appendChild(td);
            corpo.appendChild(tr);
        });
}

/* ===== Exportar JSON ===== */

function exportarJson(dados) {
    var jsonStr = typeof dados === "string" ? dados : JSON.stringify(dados, null, 2);
    var blob = new Blob([jsonStr], { type: "application/json" });
    var url = URL.createObjectURL(blob);

    var link = document.createElement("a");
    link.href = url;
    link.download = "resultado_consulta.json";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

/* ===== Upload CSV ===== */

function carregarCsv(inputFile) {
    var arquivo = inputFile.files[0];
    if (!arquivo) {
        return;
    }

    var reader = new FileReader();
    reader.onload = function (evento) {
        var conteudo = evento.target.result;
        var linhas = conteudo.split(/[\r\n]+/);
        var cnpjs = [];

        linhas.forEach(function (linha) {
            var campos = linha.split(/[,;\t]/);
            campos.forEach(function (campo) {
                var limpo = campo.trim().replace(/['"]/g, "");
                if (pareceCnpj(limpo)) {
                    cnpjs.push(limpo);
                }
            });
        });

        if (cnpjs.length === 0) {
            mostrarErro("lote-tabela-container", "Nenhum CNPJ encontrado no arquivo.");
            return;
        }

        document.getElementById("cnpjs-texto").value = cnpjs.join("\n");
    };
    reader.onerror = function () {
        mostrarErro("lote-tabela-container", "Erro ao ler o arquivo.");
    };
    reader.readAsText(arquivo);
}

function pareceCnpj(texto) {
    var apenasDigitos = texto.replace(/\D/g, "");
    return apenasDigitos.length === 14;
}

/* ===== Utilitários ===== */

function limparConteudo(elemento) {
    while (elemento.firstChild) {
        elemento.removeChild(elemento.firstChild);
    }
}

function mostrarErro(containerId, mensagem) {
    var container = document.getElementById(containerId);
    limparConteudo(container);
    var div = document.createElement("div");
    div.className = "mensagem-erro";
    div.textContent = mensagem;
    container.appendChild(div);
}

/* ===== Inicialização ===== */

document.addEventListener("DOMContentLoaded", function () {
    carregarHistorico();
});
