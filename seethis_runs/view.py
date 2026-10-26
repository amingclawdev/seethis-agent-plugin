"""Generate a static run page. Log files are selected and read in browser memory."""

import argparse
import html
import json
import os
from pathlib import Path
import sys
import webbrowser

from seethis_runs.store import Store, now, reference_id, store_path


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>SeeThis · Reference runs</title>
<style>
:root{color-scheme:light;--ink:#182b32;--muted:#62737b;--line:#dce5e4;--green:#006b55}
*{box-sizing:border-box}body{margin:0;background:#f5f7f4;color:var(--ink);font:15px/1.55 system-ui,sans-serif}
main{max-width:1120px;margin:auto;padding:48px 28px}header{border-bottom:1px solid var(--line);padding-bottom:25px}
.eyebrow{color:var(--green);font-size:12px;letter-spacing:.15em;font-weight:700}h1{font-size:36px;letter-spacing:-.04em;line-height:1.15;margin:12px 0}h2{font-size:18px;margin:0}
p{margin:8px 0}.muted{color:var(--muted)}code{font:13px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}.ref{font-size:16px}
.stats{display:flex;gap:8px;flex-wrap:wrap;margin:25px 0}.stat{border:1px solid var(--line);padding:6px 12px;border-radius:30px;background:white}
article{padding:24px;margin:16px 0;background:white;border:1px solid var(--line);border-radius:16px}.top{display:flex;justify-content:space-between;gap:15px;align-items:center}
.badge{display:inline-block;border-radius:7px;padding:4px 10px;background:#edf1f2;font-size:13px;font-weight:650}.done{background:#e0f2e8;color:#096446}.blocked{background:#fff0d2;color:#805100}.interrupted,.stopped-without-end{background:#f9e9df;color:#874929}
.summary{font-size:17px;margin:17px 0}.facts{display:grid;grid-template-columns:1fr 1fr;gap:9px 24px;margin:18px 0}.label{font-size:12px;color:var(--muted);display:block}
details{border-top:1px solid var(--line);padding-top:13px;margin-top:16px}summary{cursor:pointer;font-weight:600}button{border:1px solid var(--line);background:white;color:var(--ink);border-radius:7px;padding:8px 12px;cursor:pointer;font:inherit}button:hover{background:#f0f5f3}button:disabled{cursor:default;opacity:.5}
.reader{margin-top:14px;padding:16px;background:#f6f8f6;border-radius:10px}.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:15px 0}.status{font-size:13px;white-space:pre-wrap}.log{white-space:pre-wrap;overflow-wrap:anywhere;max-height:460px;overflow:auto;font:12px/1.6 ui-monospace,monospace;border-top:1px solid var(--line);padding-top:15px}.log:empty{display:none}.note{font-size:13px}.empty{padding:36px 0}
@media(max-width:650px){main{padding:25px 16px}h1{font-size:30px}.facts{grid-template-columns:1fr}article{padding:18px}.top{align-items:flex-start}}
</style></head><body><main>
<header><div class="eyebrow">SEETHIS / CODEX DEMO</div><h1>Reference runs</h1>
<code class="ref">__REFERENCE__</code><p class="muted">Each hand-in adds a run. Reported results and host inferences stay distinct.</p>
<p class="muted note">Snapshot __GENERATED__ · Re-run the command to refresh.</p></header>
<div id="stats" class="stats"></div><section id="runs" aria-label="Run history"></section>
<footer class="muted note">Local static page · No server · No log uploads or saved log copies.<br>Choose a rollout file to read its recorded interval. Missing or invalid anchors never fall back to the entire conversation.</footer>
</main><script id="data" type="application/json">__DATA__</script><script>
'use strict';
const model = JSON.parse(document.getElementById('data').textContent);
function el(tag, text, cls) {const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x;}
function fact(label, value) {const x=el('div');x.append(el('span',label,'label'),el('code',value??'Unavailable'));return x;}
const knownStatuses=new Set(['done','blocked','in-progress','stopped-without-end','interrupted']);
const counts={};for(const r of model.runs)counts[r.status]=(counts[r.status]||0)+1;
document.getElementById('stats').append(el('span',model.runs.length+' runs','stat'));
for(const [name,n] of Object.entries(counts))document.getElementById('stats').append(el('span',n+' '+name,'stat'));
if(!model.runs.length)document.getElementById('runs').append(el('p','No run has been recorded for this reference. This does not prove that no work happened.','empty muted'));

// File reads are bounded, user-selected and transient. No fetch or browser storage.
async function readRun(file, run) {
  const start=run.start?.locator, endRecord=run.reported_end||run.inferred_end, end=endRecord?.locator;
  if(!start?.path || !Number.isSafeInteger(start.byte) || start.byte<0 || !end || !Number.isSafeInteger(end.byte) || end.byte<start.byte || end.path!==start.path)
    throw Error('Recorded interval unavailable. This run has no complete start/end location.');
  if(end.byte>file.size)throw Error('The selected file is shorter than the recorded interval.');
  if(end.byte-start.byte>4*1024*1024)throw Error('This interval exceeds the 4 MiB demo limit. Use the displayed locations in a local log viewer.');
  if(file.name!==start.path.split('/').pop())throw Error('Choose the rollout filename shown for this run.');
  const prefix=await file.slice(0,256*1024).text();
  const lineEnd=prefix.indexOf('\n');
  if(lineEnd<0)throw Error('Cannot verify the session header within the demo read limit.');
  let header;try{header=JSON.parse(prefix.slice(0,lineEnd));}catch{throw Error('Invalid session header.');}
  if(header.type!=='session_meta'||header.payload?.id!==run.session_id)throw Error('The selected file belongs to another session.');
  const bytes=await file.slice(start.byte,end.byte).arrayBuffer();
  const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  const lines=text.split('\n');if(lines[lines.length-1]==='')lines.pop();
  let events;try{events=lines.map(line=>JSON.parse(line));}catch{throw Error('The recorded interval is incomplete or cannot be parsed.');}
  const begin=events[0];
  if(begin?.type!=='event_msg'||begin.payload?.type!=='task_started'||begin.payload?.turn_id!==run.turn_id)
    throw Error('The start anchor no longer matches this run.');
  // A delayed explicit ending may span later turns in the same conversation.
  // The stored end byte is the cutoff; an unfinished turn is never expanded.
  return {text:events.filter(e=>e.type==='event_msg'||e.type==='response_item')
    .map(e=>'['+(e.timestamp||'')+'] '+e.type+' / '+(e.payload?.type||'')+'\n'+JSON.stringify(e.payload,null,2)).join('\n\n'),count:events.length};
}

for(const run of model.runs){
  const card=el('article');const top=el('div',undefined,'top');
  top.append(el('h2',run.start.at),el('span',run.status,'badge '+(knownStatuses.has(run.status)?run.status:'')));card.append(top);
  card.append(el('p',run.summary||'No explicit summary reported.','summary'));
  const end=run.reported_end||run.inferred_end;
  const facts=el('div',undefined,'facts');facts.append(fact('Result source',run.reported_end?'Agent report':end?'Host inference · '+end.event:'Prompt hook · no ending yet'),fact('Ended at',end?.at),fact('Session',run.session_id),fact('Run',run.run_id));card.append(facts);
  if(run.reported_end&&run.inferred_end)card.append(el('p','Earlier inference retained: '+run.inferred_end.status+' · '+run.inferred_end.at,'muted note'));
  const details=el('details');details.append(el('summary','Log location & reader'));
  const path=run.start.locator.path;
  details.append(el('p',path||'Log path unavailable.','note'),fact('Turn',run.turn_id),fact('Recorded byte interval',String(run.start.locator.byte??'?')+' → '+String(end?.locator?.byte??'?')));
  const reader=el('div',undefined,'reader');reader.append(el('p','Select this local rollout file. Its recorded range is displayed only in this page’s memory.','note'));
  const actions=el('div',undefined,'actions');const choose=el('input');choose.type='file';choose.accept='.jsonl';choose.setAttribute('aria-label','Select rollout for '+run.run_id);
  const clear=el('button','Clear log');const status=el('p','No file selected.','status muted');status.setAttribute('role','status');const output=el('pre','','log');
  let generation=0;
  clear.onclick=()=>{generation++;choose.value='';output.textContent='';status.textContent='Log cleared from this page.';};
  choose.onchange=async()=>{const ticket=++generation;output.textContent='';const file=choose.files[0];if(!file){status.textContent='No file selected.';return;}status.textContent='Reading recorded interval…';
    try{const result=await readRun(file,run);if(ticket!==generation)return;output.textContent=result.text;status.textContent='Read '+result.count+' records through the stored end position. Reload or Clear log to remove them.';}
    catch(error){if(ticket===generation)status.textContent=error instanceof Error?error.message:'Unable to read this file.';}
  };
  actions.append(choose,clear);reader.append(actions,status,output);details.append(reader);card.append(details);document.getElementById('runs').append(card);
}
</script></body></html>'''


def render(reference, runs):
    encoded = json.dumps({"reference_id": reference, "runs": runs}, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    # Data is inserted last so user-written summaries cannot become placeholders.
    return PAGE.replace("__REFERENCE__", html.escape(reference)).replace("__GENERATED__", html.escape(now())).replace("__DATA__", encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", help="32-hex reference ID only, not the capability URL")
    parser.add_argument("--output", type=Path, help="New HTML file; existing files are never overwritten")
    parser.add_argument("--open", action="store_true", help="Open the generated page in the default browser")
    args = parser.parse_args()
    try:
        ref = reference_id(args.reference)
        # VIEW is strictly read-only: do not create, chmod, lock or replace the store.
        path = store_path()
        with path.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("store limit")
        data = json.loads(raw)
        if data.get("schema_version") != 1 or not isinstance(data.get("references"), dict):
            raise ValueError("store schema")
        runs = [Store.present(r) for r in reversed(data["references"].get(ref, []))]
        output = args.output or Path("build") / ("runs-" + ref + "-" + now().replace(":", "-") + ".html")
        if output.suffix.lower() != ".html":
            raise ValueError("HTML destination required")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(render(ref, runs))
        print(output.resolve())
        if args.open:
            webbrowser.open(output.resolve().as_uri())
    except (OSError, ValueError, KeyError, TypeError):
        print("View unavailable: check the reference ID, run store and new HTML destination. No run data was changed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
