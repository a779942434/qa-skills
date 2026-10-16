# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
imgs=[
 Path('/Users/a77994/qa-skills/bug-reports/合金污染规则定义/BUG-05_删除确认文案.png'),
 Path('/Users/a77994/qa-skills/bug-reports/合金污染规则定义/BUG-05_审核确认文案.png'),
]
pw=browser=ctx=page=None;results=[]
try:
 pw,browser,ctx,page=ones_helpers.connect()
 for img in imgs:
  try:
   page.goto('https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/RsxEsWtX76bd25f0',wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(5000)
   r=ones_helpers.append_task_description_images(page,'2YPZxEgX','RsxEsWtX76bd25f0',[img],timeout=180)
   results.append({'file':img.name,'ok':True,'result':{k:v for k,v in r.items() if k!='after_html'}})
  except Exception as exc:
   results.append({'file':img.name,'ok':False,'error':str(exc)[:500]})
 print(json.dumps(results,ensure_ascii=False)[:12000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
