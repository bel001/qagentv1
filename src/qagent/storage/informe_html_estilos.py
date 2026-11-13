"""Hoja de estilo del informe HTML interactivo (HU-22)."""

from __future__ import annotations

CSS_INFORME = """body{font-family:system-ui,-apple-system,sans-serif;background:#0e1117;color:#f0f6fc;margin:0;padding:24px;line-height:1.5}
.wrap{max-width:1100px;margin:0 auto}
.header{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;margin-bottom:18px}
.header-top{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.header-title{margin:0;font-size:20px;font-weight:700;display:flex;align-items:center;gap:10px}
.header-meta{margin:0 0 16px 0;font-size:13px;color:#8b949e}
.respuesta{font-size:17px;font-weight:600;color:#f0f6fc;margin:0 0 16px 0;padding:12px 16px;background:#21262d;border-radius:8px;border-left:4px solid #1f6feb}
.cifras-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:16px}
.cifra-card{background:#21262d;border:1px solid #30363d;border-radius:8px;padding:14px}
.cifra-etq{font-size:12px;color:#8b949e;margin-bottom:4px}
.cifra-val{font-size:22px;font-weight:800;color:#f0f6fc}
.cifra-val.val-bug{color:#f85149}
.cifra-sub{font-size:11px;color:#6e7681;margin-top:2px}
.tabs{display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap}
.tab{padding:9px 16px;border-radius:8px;background:#161b22;border:1px solid #30363d;color:#8b949e;cursor:pointer;font-weight:600;font-size:13px}
.tab:hover{color:#f0f6fc;background:#21262d}
.tab.active{background:#1f6feb;border-color:#388bfd;color:#fff}
.panel{display:none;background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px}
.panel.active{display:block}
table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{padding:10px 12px;border-bottom:1px solid #30363d;text-align:left;font-size:13px}
th{color:#8b949e;font-weight:600}
.pill{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11.5px;font-weight:700}
.pill.pass{background:#0d2818;color:#3fb950;border:1px solid #238636}
.pill.fail{background:#3a0e10;color:#f85149;border:1px solid #da3633}
.pill.info{background:#13233a;color:#58a6ff;border:1px solid #1f6feb}
.badge{display:inline-block;padding:3px 8px;border-radius:6px;font-size:11px;font-weight:700}
.badge-exito{background:#0d2818;color:#3fb950;border:1px solid #238636}
.badge-bug{background:#3a0e10;color:#f85149;border:1px solid #da3633}
.badge-error{background:#2a123d;color:#d2a8ff;border:1px solid #8957e5}
.badge-aviso{background:#341f02;color:#d29922;border:1px solid #9e6a03}
.salud-card{background:#161b22;border:1px solid #30363d;border-left:4px solid #1f6feb;border-radius:8px;padding:16px;margin:16px 0}
.salud-col{background:#21262d;border:1px solid #30363d;border-radius:8px;padding:12px}
.fn-card{padding:14px;border:1px solid #30363d;border-radius:8px;margin-bottom:12px;background:#0e1117}
.agent-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:10px}
.agent-box{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px}
.agent-box h4{margin:0 0 6px 0;font-size:13px;color:#f0f6fc}
.agent-box p{margin:4px 0;font-size:12px;color:#8b949e}
.agent-box ul{margin:4px 0 4px 18px;padding:0;font-size:11.5px;color:#8b949e}
.agent-box details summary{cursor:pointer;color:#388bfd;font-size:12px;margin-top:4px}
.prioridad-card{background:#21262d;border:1px solid #30363d;border-left:4px solid #388bfd;border-radius:8px;padding:14px;margin-bottom:12px}
.alerta-laundering{background:#341f02;border:1px solid #9e6a03;color:#f0e6d2;padding:8px 12px;border-radius:6px;margin:8px 0;font-size:12px}
.caso{padding:8px 10px;border-left:3px solid #30363d;margin:6px 0;background:#161b22;border-radius:6px;font-size:12px}
.caso.paso{border-color:#3fb950}.caso.fallo{border-color:#f85149}.caso.omitido{border-color:#8b949e}
.caso pre,details pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0e1117;border:1px solid #30363d;border-radius:6px;padding:8px;font-size:12px}
.caso pre.fallo,pre.fallo{color:#ff7b72;background:#3a0e10;border:1px solid #da3633;padding:10px;border-radius:6px;white-space:pre-wrap}
pre{background:#0e1117;border:1px solid #30363d;border-radius:6px;padding:12px;overflow-x:auto;font-size:12px}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.comparison-card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;margin-bottom:18px}
.comparison-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.comparison-summary div{background:#21262d;border:1px solid #30363d;border-radius:8px;padding:10px;display:flex;flex-direction:column}
.comparison-summary b{font-size:20px}.comparison-summary span{font-size:11px;color:#8b949e}
"""
