# -*- coding: utf-8 -*-
import json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
items=[
 ('BUG-01','208638','RsxEsWtX1524fec1',3),
 ('BUG-02','208640','RsxEsWtX9a82b286',1),
 ('BUG-03','208641','RsxEsWtXfecc0a71',1),
 ('BUG-04','208642','RsxEsWtXc4329d1b',1),
 ('BUG-05','208643','RsxEsWtX76bd25f0',2),
]
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 out=[]
 for key,num,uuid,expected_imgs in items:
  info=ones_helpers.get_task_info(page,'2YPZxEgX',uuid) or {}
  fv={f.get('field_uuid'):f.get('value') for f in (info.get('field_values') or [])}
  html=str(fv.get('field016') or info.get('desc_rich') or '')
  attachments=(ones_helpers.get_task_attachments(page,'2YPZxEgX',uuid) or {}).get('attachments') or []
  out.append({'key':key,'number':info.get('number'),'expected_number':num,'summary':info.get('summary'),'status_uuid':info.get('status_uuid'),'image_count':len(re.findall(r'<img',html)),'expected_images':expected_imgs,'attachment_count':len(attachments),'attachment_names':[a.get('name') for a in attachments]})
 parent=ones_helpers.get_task_info(page,'2YPZxEgX','MH4B2YPuolKGjBLL') or {}
 titles=ones_helpers.list_related_tasks(page,'2YPZxEgX','MH4B2YPuolKGjBLL',parent.get('summary') or '')
 number_hits=[t for t in titles if any(n in t for n in [x[1] for x in items])]
 result={'items':out,'related_count':len(titles),'number_hits':number_hits,'duplicates':ones_helpers.dedup_check(titles)}
 p=Path('/Users/a77994/qa-skills/runs/2026-09-28_合金污染规则定义/json/ones_submission_verification.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False)[:30000])
finally:
 try:
  if page is not None:
   for sel in ('.task-drawer .close','.task-drawer [aria-label="关闭"]','button[aria-label="关闭"]'):
    loc=page.locator(sel)
    if loc.count() and loc.first.is_visible():loc.first.click();break
 except Exception:pass
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except Exception:pass
