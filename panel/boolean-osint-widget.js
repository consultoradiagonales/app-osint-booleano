class BooleanOsintWidget extends HTMLElement {
  connectedCallback() {
    this.api = this.getAttribute("api") || "http://127.0.0.1:8765/api/bridge";
    this.innerHTML = `
      <style>
        .bos-card{font-family:Inter,system-ui,sans-serif;color:#e9ffff;background:#061a22;border:1px solid #00e5ff55;border-radius:14px;padding:18px;box-shadow:0 0 24px #00e5ff16}
        .bos-head{display:flex;align-items:center;gap:10px;margin-bottom:14px}.bos-dot{width:10px;height:10px;border-radius:50%;background:#00e5ff;box-shadow:0 0 12px #00e5ff}
        .bos-title{font-weight:800;letter-spacing:.04em}.bos-sub{font-size:12px;color:#8ecbd2;margin-left:auto}
        .bos-row{display:grid;grid-template-columns:1fr auto;gap:10px}.bos-input{min-width:0;background:#031016;color:#e9ffff;border:1px solid #1a5964;border-radius:9px;padding:12px}
        .bos-btn{border:0;border-radius:9px;padding:0 18px;background:#00d7ed;color:#001318;font-weight:800;cursor:pointer}.bos-btn:disabled{opacity:.45;cursor:wait}
        .bos-options{display:flex;gap:12px;margin:10px 0;color:#a7d6dc;font-size:12px}.bos-options input{width:62px;background:#031016;color:#fff;border:1px solid #1a5964;border-radius:5px;padding:4px}
        .bos-status{font-size:13px;min-height:20px;color:#83f3ff}.bos-summary{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0}.bos-pill{background:#0b2b35;border:1px solid #145666;border-radius:999px;padding:5px 9px;font-size:12px}
        .bos-results{display:grid;gap:8px;max-height:420px;overflow:auto}.bos-item{background:#04151c;border-left:3px solid #00d7ed;padding:10px;border-radius:6px}.bos-item a{color:#d9fcff;text-decoration:none;font-weight:700}.bos-meta{font-size:11px;color:#79b3bb;margin-top:6px}.bos-error{color:#ff9d9d}
        .bos-alerts{margin-top:18px;padding-top:16px;border-top:1px solid #145666}.bos-alert-head{display:flex;align-items:center;gap:9px;margin-bottom:10px}.bos-alert-title{font-weight:750}.bos-email-status{margin-left:auto;font-size:11px;padding:4px 8px;border-radius:999px;background:#102f38;color:#a7d6dc}.bos-email-status.ok{color:#8affc1;border:1px solid #2a8b61}
        .bos-recipient-form{display:grid;grid-template-columns:1fr 1fr auto;gap:8px}.bos-small-btn{border:1px solid #207080;background:#092b34;color:#d9fcff;border-radius:8px;padding:9px 11px;cursor:pointer}.bos-small-btn.danger{color:#ffb0b0;border-color:#744}
        .bos-recipient-list{display:grid;gap:7px;margin-top:10px}.bos-recipient{display:grid;grid-template-columns:auto 1fr auto auto;gap:9px;align-items:center;background:#04151c;padding:8px;border-radius:7px}.bos-recipient-main{min-width:0}.bos-recipient-email{font-size:13px;overflow-wrap:anywhere}.bos-recipient-name{font-size:11px;color:#79b3bb}.bos-help{font-size:11px;color:#79b3bb;margin-top:8px}
        @media(max-width:650px){.bos-row,.bos-recipient-form{grid-template-columns:1fr}.bos-btn{min-height:42px}.bos-sub{display:none}.bos-recipient{grid-template-columns:auto 1fr auto}.bos-test{grid-column:2}.bos-options{flex-wrap:wrap}}
      </style>
      <section class="bos-card">
        <div class="bos-head"><span class="bos-dot"></span><span class="bos-title">RASTREADOR OSINT–BOOLEANO</span><span class="bos-sub">Local · sin IA · sin APIs pagas</span></div>
        <div class="bos-row">
          <input class="bos-input" placeholder='UCR AND (convención OR autoridades) NOT nacional' aria-label="Consulta booleana">
          <button class="bos-btn">Ejecutar rastreo</button>
        </div>
        <div class="bos-options">
          <label>Días <input class="bos-days" type="number" min="1" max="3650" value="7"></label>
          <label>Máximo <input class="bos-max" type="number" min="1" max="500" value="100"></label>
          <span>Monitores: cada 10 minutos</span>
        </div>
        <div class="bos-status" role="status"></div>
        <div class="bos-summary"></div>
        <div class="bos-results"></div>
        <section class="bos-alerts">
          <div class="bos-alert-head"><span class="bos-alert-title">Suscriptores de Google Calendar</span><span class="bos-email-status">Verificando Calendar…</span></div>
          <div class="bos-recipient-form">
            <input class="bos-input bos-email" type="email" autocomplete="email" placeholder="correo@cliente.com" aria-label="Correo del destinatario">
            <input class="bos-input bos-name" placeholder="Nombre o cliente (opcional)" aria-label="Nombre del destinatario">
            <button class="bos-small-btn bos-add" type="button">Agregar</button>
          </div>
          <div class="bos-recipient-list"></div>
          <div class="bos-help">Cada persona recibe una única invitación al calendario compartido. Los cables posteriores aparecen en Calendar, sin correos de alerta.</div>
        </section>
      </section>`;
    this.querySelector(".bos-btn").addEventListener("click", () => this.run());
    this.querySelector(".bos-input").addEventListener("keydown", event => {
      if (event.key === "Enter") this.run();
    });
    this.querySelector(".bos-add").addEventListener("click", () => this.addRecipient());
    this.loadRecipients();
    this.loadCalendarStatus();
  }

  async request(path, options = {}) {
    const response = await fetch(`${this.api}${path}`, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.deliveries?.[0]?.error || `HTTP ${response.status}`);
    return data;
  }

  async loadCalendarStatus() {
    const badge = this.querySelector(".bos-email-status");
    try {
      const data = await this.request("/calendar/status");
      badge.textContent = data.configured ? `Calendar activo · ${data.organizer}` : "Calendar pendiente de autorizar";
      badge.classList.toggle("ok", data.configured);
    } catch (error) { badge.textContent = "Calendar no disponible"; }
  }

  async loadRecipients() {
    const list = this.querySelector(".bos-recipient-list");
    try {
      const data = await this.request("/recipients");
      list.innerHTML = data.recipients.map(recipient => `
        <div class="bos-recipient" data-id="${recipient.id}">
          <input class="bos-enabled" type="checkbox" ${recipient.enabled ? "checked" : ""} aria-label="Activar ${this.escape(recipient.email)}">
          <div class="bos-recipient-main"><div class="bos-recipient-email">${this.escape(recipient.email)}</div><div class="bos-recipient-name">${this.escape(recipient.name || "Sin nombre")}</div></div>
          <button class="bos-small-btn bos-test" type="button">Probar</button>
          <button class="bos-small-btn danger bos-delete" type="button" aria-label="Eliminar">×</button>
        </div>`).join("") || '<div class="bos-meta">Todavía no hay destinatarios cargados.</div>';
      list.querySelectorAll(".bos-recipient").forEach(row => {
        row.querySelector(".bos-enabled").addEventListener("change", event => this.toggleRecipient(row.dataset.id, event.target.checked));
        row.querySelector(".bos-delete").addEventListener("click", () => this.deleteRecipient(row.dataset.id));
        row.querySelector(".bos-test").addEventListener("click", event => this.testRecipient(row.dataset.id, event.target));
      });
    } catch (error) { list.innerHTML = `<span class="bos-error">${this.escape(error.message)}</span>`; }
  }

  async addRecipient() {
    const email = this.querySelector(".bos-email");
    const name = this.querySelector(".bos-name");
    if (!email.value.trim() || !email.checkValidity()) { email.reportValidity(); return; }
    try {
      await this.request("/recipients", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:email.value.trim(), name:name.value.trim()})});
      email.value = ""; name.value = ""; await this.loadRecipients();
    } catch (error) { this.querySelector(".bos-status").innerHTML = `<span class="bos-error">${this.escape(error.message)}</span>`; }
  }

  async toggleRecipient(id, enabled) {
    try { await this.request(`/recipients/${id}`, {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({enabled})}); }
    catch (error) { await this.loadRecipients(); this.querySelector(".bos-status").innerHTML = `<span class="bos-error">${this.escape(error.message)}</span>`; }
  }

  async deleteRecipient(id) {
    try { await this.request(`/recipients/${id}`, {method:"DELETE"}); await this.loadRecipients(); }
    catch (error) { this.querySelector(".bos-status").innerHTML = `<span class="bos-error">${this.escape(error.message)}</span>`; }
  }

  async testRecipient(id, button) {
    button.disabled = true;
    try { await this.request("/calendar/test", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({recipient_id:Number(id)})}); button.textContent = "Creado"; }
    catch (error) { this.querySelector(".bos-status").innerHTML = `<span class="bos-error">${this.escape(error.message)}</span>`; button.textContent = "Falló"; }
    finally { setTimeout(() => { button.disabled = false; button.textContent = "Probar"; }, 2500); }
  }

  async run() {
    const query = this.querySelector(".bos-input").value.trim();
    const status = this.querySelector(".bos-status");
    const button = this.querySelector(".bos-btn");
    if (!query) { status.innerHTML = '<span class="bos-error">Ingresá una consulta.</span>'; return; }
    button.disabled = true;
    status.textContent = "Consultando fuentes públicas…";
    this.querySelector(".bos-results").innerHTML = "";
    try {
      const response = await fetch(`${this.api}/run`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          query,
          since_days: Number(this.querySelector(".bos-days").value),
          max_results: Number(this.querySelector(".bos-max").value)
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      status.textContent = `Corrida ${data.run_id} finalizada`;
      this.render(data);
      this.dispatchEvent(new CustomEvent("osint-complete", {detail: data, bubbles: true}));
    } catch (error) {
      status.innerHTML = `<span class="bos-error">${this.escape(error.message)}</span>`;
    } finally {
      button.disabled = false;
    }
  }

  render(data) {
    this.querySelector(".bos-summary").innerHTML = `
      <span class="bos-pill">Descubiertos: ${data.total_discovered}</span>
      <span class="bos-pill">Coincidencias: ${data.total_matched}</span>
      <span class="bos-pill">Errores de fuente: ${data.errors.length}</span>`;
    this.querySelector(".bos-results").innerHTML = data.results.map(item => `
      <article class="bos-item">
        <a href="${this.escape(item.url)}" target="_blank" rel="noopener noreferrer">${this.escape(item.title)}</a>
        <div class="bos-meta">${this.escape(item.source)} · confianza ${item.confidence} · relevancia ${item.relevance_score}/100 · ${item.mentions} hallazgo/s · ${item.corroborating_sources.length} fuente/s</div>
      </article>`).join("") || '<div class="bos-meta">No hubo coincidencias para esta expresión.</div>';
  }

  escape(value) {
    return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
  }
}

customElements.define("boolean-osint-widget", BooleanOsintWidget);
