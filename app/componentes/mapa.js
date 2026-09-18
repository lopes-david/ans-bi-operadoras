// Mapa do Brasil clicável. Recebe {geo, valores, selecionado} e devolve o clique como trigger "clique".
const NS = "http://www.w3.org/2000/svg";
const PADRAO = ["#cde2fb", "#184f95"];

function rgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}

function cor(valor, min, max, paleta) {
  if (!valor) return "rgba(128,128,128,0.25)";
  const t = max > min ? (Math.log(valor) - Math.log(min)) / (Math.log(max) - Math.log(min)) : 1;
  const [claro, escuro] = paleta.map(rgb);
  const c = claro.map((v, i) => Math.round(v + (escuro[i] - v) * t));
  return `rgb(${c.join(",")})`;
}

function construir(raiz, geo, avisar) {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `-40 -30 ${geo.largura + 80} ${geo.altura + 60}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Mapa do Brasil por estado");
  const grupo = document.createElementNS(NS, "g");
  const rotulos = document.createElementNS(NS, "g");
  svg.append(grupo, rotulos);

  geo.estados.forEach((e, i) => {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", e.d);
    p.setAttribute("class", "estado");
    p.setAttribute("tabindex", "0");
    p.dataset.uf = e.uf;
    p.style.animationDelay = `${i * 18}ms`;
    p.addEventListener("click", () => avisar(e.uf));
    p.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        avisar(e.uf);
      }
    });
    grupo.appendChild(p);

    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", e.cx);
    t.setAttribute("y", e.cy);
    t.setAttribute("class", "rotulo");
    t.dataset.uf = e.uf;
    t.textContent = e.uf;
    rotulos.appendChild(t);

    if (e.uf === "DF") {
      // o DF é pequeno demais para clicar: área de clique extra
      const alvo = document.createElementNS(NS, "circle");
      alvo.setAttribute("cx", e.cx);
      alvo.setAttribute("cy", e.cy);
      alvo.setAttribute("r", 9);
      alvo.setAttribute("class", "alvo-df");
      alvo.addEventListener("click", () => avisar("DF"));
      rotulos.before(alvo);
    }
  });

  const dica = document.createElement("div");
  dica.className = "dica";
  const legenda = document.createElement("div");
  legenda.className = "legenda";
  legenda.innerHTML = '<span class="menos"></span><span class="barra"></span><span class="mais"></span>';
  raiz.append(svg, dica, legenda);

  // garantia: se o navegador não avançar a animação de entrada (aba em segundo plano,
  // economia de energia), o mapa aparece mesmo assim
  setTimeout(() => {
    grupo.querySelectorAll(".estado").forEach((p) =>
      p.getAnimations().forEach((a) => {
        if (a.animationName === "surgir") a.finish();
      }),
    );
  }, 1500);
  return { svg, grupo, dica, legenda };
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  if (!data || !data.geo) return;

  let raiz = parentElement.querySelector(".mapa-root");
  if (!raiz) {
    raiz = document.createElement("div");
    raiz.className = "mapa-root";
    parentElement.appendChild(raiz);
    raiz._partes = construir(raiz, data.geo, (uf) => {
      // clicar de novo no estado selecionado desmarca
      const atual = raiz.dataset.selecionado || null;
      setTriggerValue("clique", { uf: uf === atual ? null : uf, em: Date.now() });
    });
  }
  const { grupo, dica, legenda } = raiz._partes;
  const paleta = data.paleta || PADRAO;
  const textos = data.legenda || ["menos", "mais"];
  legenda.querySelector(".menos").textContent = textos[0];
  legenda.querySelector(".mais").textContent = textos[1];
  legenda.querySelector(".barra").style.background = `linear-gradient(90deg, ${paleta[0]}, ${paleta[1]})`;
  const valores = data.valores || {};
  const lista = Object.values(valores).map((v) => v.valor).filter((v) => v > 0);
  const min = Math.min(...lista);
  const max = Math.max(...lista);
  const sel = data.selecionado || "";
  raiz.dataset.selecionado = sel;
  raiz.classList.toggle("com-selecao", Boolean(sel));

  grupo.querySelectorAll(".estado").forEach((p) => {
    const uf = p.dataset.uf;
    const v = valores[uf] || {};
    p.style.fill = cor(v.valor, min, max, paleta);
    p.setAttribute("aria-label", `${v.nome || uf}: ${v.texto || "sem dados"}`);
    const estava = p.classList.contains("selecionado");
    p.classList.toggle("selecionado", uf === sel);
    if (uf === sel && !estava) grupo.appendChild(p); // traz o estado para a frente
    p.onpointermove = (ev) => {
      const r = raiz.getBoundingClientRect();
      dica.innerHTML = "";
      const b = document.createElement("b");
      b.textContent = v.nome || uf;
      dica.append(b, document.createTextNode(v.texto || "sem dados"));
      dica.style.left = `${Math.min(ev.clientX - r.left + 14, r.width - dica.offsetWidth - 4)}px`;
      dica.style.top = `${ev.clientY - r.top + 14}px`;
      dica.classList.add("visivel");
    };
    p.onpointerleave = () => dica.classList.remove("visivel");
  });
  raiz.querySelectorAll(".rotulo").forEach((t) => t.classList.toggle("visivel", t.dataset.uf === sel));
}
