"""El diálogo optativo conserva cancelación y envía la opción solo al aceptarla."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_contexto_automatico_respeta_cancelacion_doble_clic_y_lenguaje():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node permite comprobar el diálogo real sin llamadas a IA.")
    frontend = Path(__file__).parents[2] / "src/qagent/frontend"
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const nodos=new Map();
function $(id){if(!nodos.has(id))nodos.set(id,{innerHTML:'',textContent:'',checked:false,
  disabled:false,focus(){},classList:{toggle(){},add(){},remove(){}}});return nodos.get(id);}
const ctx=vm.createContext({$,console,assert,registrarComponente(){},I:()=>'',
  escHtml:x=>String(x).replaceAll('<','&lt;'),openModal(){},
  window:{addEventListener(){},pywebview:{api:{}}},
  document:{querySelectorAll:()=>[],addEventListener(){},activeElement:null},
  setInterval:()=>0,clearInterval(){},setTimeout,clearTimeout});
for(const ruta of JSON.parse(fs.readFileSync(0,'utf8'))){
  const fuente=fs.readFileSync(ruta,'utf8');
  for(const nombre of fuente.match(/ICO_[A-Z_]+/g)||[])ctx[nombre]='';
  vm.runInContext(fuente,ctx);
}
vm.runInContext(`(async()=>{
  PROYECTO_NOMBRE_LENGUAJE='TypeScript';
  MODULES=[{path:'fib.ts',sel:true,fns:[{n:'nthFibonacci',inc:true,
    orientacion:{categoria:'revisar',motivo:'Falta contexto'}}]}];
  go=()=>{}; toast=()=>{}; entornoListo=true; profile='humo'; projectPath='C:/prueba';
  eleccionPruebas={modo:'nuevas',unitarias:true,endpoints:false,integracion:false};
  INFERIR_SIN_DOCSTRING=false; REVISAR_INFERIDOS=false;
  const llamadas=[];
  window.pywebview.api.start_run=async(...a)=>{llamadas.push(a);return {status:'en_curso',mensaje:'Simulado'}};
  const cancelada=startMonitor();
  assert.equal(llamadas.length,0);
  $('ctxCompletar').checked=true;
  resolverContextoAutomatico(false);
  await cancelada;
  assert.equal(llamadas.length,0);
  assert.equal(COMPLETAR_CONTEXTO,false);
  const activada=startMonitor(), doble=startMonitor();
  $('ctxCompletar').checked=true;
  resolverContextoAutomatico(true);
  await Promise.all([activada,doble]);
  assert.equal(llamadas.length,1);
  assert.equal(llamadas[0][5],true);
  assert.equal(llamadas[0][3],false); // Conserva la elección independiente de inferencia.
  const desactivada=startMonitor();
  $('ctxCompletar').checked=false;
  resolverContextoAutomatico(true);
  await desactivada;
  assert.equal(llamadas[1].length,5);
  COMPLETAR_CONTEXTO=true; PROYECTO_NOMBRE_LENGUAJE='Python';
  assert.equal(usarContextoAutomatico(),false);
  PROYECTO_NOMBRE_LENGUAJE='TypeScript'; profile='reg';
  assert.equal(usarContextoAutomatico(),false);
  profile='humo';eleccionPruebas.unitarias=false;
  assert.equal(usarContextoAutomatico(),false);
})()`,ctx).catch(e=>{console.error(e);process.exitCode=1});
"""
    resultado = subprocess.run(
        [node, "-e", script],
        input=json.dumps(
            [
                str(frontend / "componentes/vista-previa/vista-previa.js"),
                str(frontend / "componentes/revision/modal-contexto.js"),
                str(frontend / "componentes/monitor/monitor.js"),
            ]
        ),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
