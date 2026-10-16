# -*- coding: utf-8 -*-
import json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 info=ones_helpers.get_task_info(page,'2YPZxEgX','RsxEsWtX1524fec1') or {}
 fv={f.get('field_uuid'):f.get('value') for f in (info.get('field_values') or [])}
 html=str(fv.get('field016') or info.get('desc_rich') or '')
 att=(ones_helpers.get_task_attachments(page,'2YPZxEgX','RsxEsWtX1524fec1') or {}).get('attachments') or []
 data={'field016':html,'attachments':att}
 p=Path('/Users/a77994/qa-skills/runs/2026-09-28_合金污染规则定义/json/ones_208638_attachment_inspect.json');p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 print('HTML image tags:')
 for m in re.finditer(r'<img[^>]+>',html): print(m.group(0)[:1000])
 print('\nAttachments:')
 for a in att: print(json.dumps({k:a.get(k) for k in ('uuid','name','create_time','size','download_url')},ensure_ascii=False))
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
