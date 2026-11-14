"""Selección voluntaria y consentimiento previo al gasto, con los componentes JS reales."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_aviso_permite_cancelar_aceptar_y_elegir_funciones_manualmente():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node permite comprobar el comportamiento de selección.")
    frontend = Path(__file__).parents[2] / "src/qagent/frontend"
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const rutas=JSON.parse(fs.readFileSync(0,'utf8'));
const nodos=new Map();
function $(id){if(!nodos.has(id))nodos.set(id,{innerHTML:'',textContent:'',disabled:false,
  classList:{toggle(){},add(){},remove(){}}});return nodos.get(id);}
const ctx=vm.createContext({$,assert,console,registrarComponente(){},I:()=>'',
  escHtml:x=>String(x),window:{addEventListener(){},pywebview:{api:{}}},
  document:{querySelectorAll:()=>[],addEventListener(){}},
  setInterval:()=>0,clearInterval(){},setTimeout,clearTimeout});
for(const ruta of rutas){
  const fuente=fs.readFileSync(ruta,'utf8');
  for(const nombre of fuente.match(/ICO_[A-Z_]+/g)||[])ctx[nombre]='';
  vm.runInContext(fuente,ctx);
}
vm.runInContext(`
  MODULES=[{path:'service.py',sel:true,fns:[
    {n:'sumar',inc:true,orientacion:{categoria:'recomendada',motivo:'Lógica de datos'}},
    {n:'get_service',inc:true,orientacion:{categoria:'revisar',motivo:'Devuelve un servicio'}}
  ]},{path:'excluida.py',sel:false,fns:[{n:'otra',inc:false,orientacion:{categoria:'recomendada'}}]}];
  renderFns=()=>{}; guardarSeleccionExplorar=()=>{}; toast=()=>{};
  go=v=>{window.destino=v};
  entornoListo=true; profile='humo'; projectPath='C:/proyecto';
  eleccionPruebas={modo:'nuevas',unitarias:true,endpoints:false,integracion:false};
  INFERIR_SIN_DOCSTRING=true; REVISAR_INFERIDOS=false;
  window.generaciones=0; window.consultas=0; window.dialogos=0; window.aceptar=false;
  window.confirm=texto=>{window.dialogos++;window.aviso=texto;return window.aceptar};
  window.pywebview.api.start_run=async()=>{window.generaciones++;return {status:'en_curso',mensaje:'doble de prueba'}};
  window.pywebview.api.obtener_vista_previa=async(ruta,consentimiento)=>{
    assert.equal(consentimiento,true);window.consultas++;
    return {recomendacion:{origen:'reglas',recomendaciones:[]}};
  };
`,ctx);
vm.runInContext(`(async()=>{
  aplicarSeleccionRecomendada();
  assert.equal(MODULES[0].fns[0].inc,true);
  assert.equal(MODULES[0].fns[1].inc,false);
  assert.equal(MODULES[1].fns[0].inc,false);
  assert.equal(window.generaciones,0);
  toggle(0,1,'inc');
  assert.equal(MODULES[0].fns[1].inc,true); // La advertida sigue siendo seleccionable.
  await startMonitor();
  assert.equal(window.generaciones,0);
  assert.equal(window.destino,'preview');
  assert.match(window.aviso,/puede consumir tokens/);
  window.aceptar=true;
  await startMonitor();
  assert.equal(window.generaciones,1);
  toggle(0,1,'inc');
  window.aceptar=false;
  const dialogos=window.dialogos;
  await startMonitor();
  assert.equal(window.generaciones,2);
  assert.equal(window.dialogos,dialogos);
  await solicitarRecomendacionIA();
  assert.equal(window.consultas,0);
  window.aceptar=true;
  await solicitarRecomendacionIA();
  assert.equal(window.consultas,1);
  window.pywebview.api.obtener_vista_previa=async()=>{
    recibirRecomendacionIA({ruta:projectPath,recomendacion:{origen:'ia',recomendaciones:[]}});
    return {recomendacion:{origen:'reglas',recomendaciones:[]},recomendacion_ia_pendiente:true};
  };
  await solicitarRecomendacionIA();
  assert.equal(RECOMENDACION.recomendacion.origen,'ia');
  assert.equal(RECO_IA_PENDIENTE,false);
  let liberar;
  window.pywebview.api.obtener_vista_previa=()=>{window.consultas++;return new Promise(r=>liberar=r)};
  const primera=solicitarRecomendacionIA();
  const segunda=solicitarRecomendacionIA();
  assert.equal(window.consultas,2); // Un doble clic no duplica consultas pagadas.
  liberar({recomendacion:{origen:'reglas',recomendaciones:[]}});
  await Promise.all([primera,segunda]);
  toggle(0,1,'inc');
  profile='reg';
  const antes=window.dialogos;
  assert.equal(confirmarOrientacionAntesDeIA(),true);
  profile='humo';eleccionPruebas.unitarias=false;eleccionPruebas.endpoints=true;
  assert.equal(confirmarOrientacionAntesDeIA(),true);
  assert.equal(window.dialogos,antes);
})()`,ctx).catch(e=>{console.error(e);process.exitCode=1});
"""
    resultado = subprocess.run(
        [node, "-e", script],
        input=json.dumps(
            [
                str(frontend / "componentes/vista-previa/vista-previa.js"),
                str(frontend / "componentes/monitor/monitor.js"),
            ]
        ),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
