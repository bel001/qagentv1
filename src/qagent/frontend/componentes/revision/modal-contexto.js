// Recuperación documental optativa antes de iniciar una corrida.
registrarComponente('revision/modal-contexto', `
<div class="overlay" id="m-contexto" onclick="event.stopImmediatePropagation();if(event.target===this)resolverContextoAutomatico(false)">
  <div class="modal contexto-modal" role="dialog" aria-modal="true" aria-labelledby="ctxTitulo" aria-describedby="ctxDescripcion">
    <div class="mhead"><span id="ctxTitulo">Antes de generar las pruebas</span></div>
    <div class="mcontent">
      <p id="ctxDescripcion">Estas funciones necesitan revisión. Puedes buscar contexto documentado antes de generar sus pruebas.</p>
      <ul id="ctxObjetivos" class="esp-lista contexto-objetivos"></ul>
      <label class="prep-casilla" id="ctxOpcion">
        <input type="checkbox" class="exp-caja" id="ctxCompletar" onchange="pintarAccionContexto()" aria-describedby="ctxAyuda">
        <span><b>Completar contexto automáticamente</b><span class="prep-desc" id="ctxAyuda">Buscar ejemplos con resultados documentados en el archivo, README y docs. La búsqueda no usa IA ni cambia tus archivos. El informe indicará las fuentes.</span></span>
      </label>
      <p class="prep-desc">La generación posterior puede consumir tokens. Si no hay evidencia suficiente, la función se omite. Completar contexto no garantiza que la prueba pase.</p>
    </div>
    <div class="mfoot"><button type="button" class="btn" id="ctxCancelar" onclick="resolverContextoAutomatico(false)">Revisar selección</button><button type="button" class="btn primary" id="ctxComenzar" onclick="resolverContextoAutomatico(true)">Comenzar</button></div>
  </div>
</div>`);

let COMPLETAR_CONTEXTO = false;
let CONTEXTO_RESOLVER = null;
let CONTEXTO_FOCO_ANTERIOR = null;

function contextoAutomaticoDisponible(){
  return typeof PROYECTO_NOMBRE_LENGUAJE !== 'undefined' && ['JavaScript','TypeScript'].includes(PROYECTO_NOMBRE_LENGUAJE);
}

function usarContextoAutomatico(){
  return COMPLETAR_CONTEXTO && contextoAutomaticoDisponible() && !['reg','reg_deep'].includes(profile) && eleccionPruebas.unitarias === true;
}

function abrirContextoAutomatico(funciones){
  if (CONTEXTO_RESOLVER) return Promise.resolve(false);
  $('ctxObjetivos').innerHTML = funciones.slice(0,8).map(f=>`<li><b>${escHtml(f.n)}</b><span class="prep-desc">${escHtml(f.orientacion.motivo)}</span></li>`).join('');
  $('ctxOpcion').classList.toggle('hide', !contextoAutomaticoDisponible());
  $('ctxCompletar').checked = COMPLETAR_CONTEXTO;
  CONTEXTO_FOCO_ANTERIOR = document.activeElement;
  pintarAccionContexto();
  openModal('m-contexto');
  const promesa = new Promise(resolver=>{ CONTEXTO_RESOLVER=resolver; });
  (contextoAutomaticoDisponible() ? $('ctxCompletar') : $('ctxCancelar')).focus();
  return promesa;
}

function pintarAccionContexto(){
  $('ctxComenzar').textContent = contextoAutomaticoDisponible() && $('ctxCompletar').checked ? 'Completar contexto y comenzar' : 'Comenzar con esta selección';
}

function resolverContextoAutomatico(continuar){
  if (!CONTEXTO_RESOLVER) return;
  if (continuar) COMPLETAR_CONTEXTO = contextoAutomaticoDisponible() && $('ctxCompletar').checked;
  const resolver = CONTEXTO_RESOLVER;
  CONTEXTO_RESOLVER = null;
  $('m-contexto').classList.remove('show');
  if (CONTEXTO_FOCO_ANTERIOR && CONTEXTO_FOCO_ANTERIOR.isConnected) CONTEXTO_FOCO_ANTERIOR.focus();
  resolver(continuar);
}

document.addEventListener('keydown', e=>{
  if (!CONTEXTO_RESOLVER) return;
  if (e.key === 'Escape') { e.preventDefault(); resolverContextoAutomatico(false); }
  if (e.key === 'Tab') {
    const controles = Array.from($('m-contexto').querySelectorAll('button,input')).filter(n=>!n.disabled && n.getClientRects().length);
    const primero = controles[0], ultimo = controles[controles.length-1];
    if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
    else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
  }
});
