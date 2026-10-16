# -*- coding: utf-8 -*-
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
imgs=[
 Path('/Users/a77994/qa-skills/bug-reports/合金污染规则定义/BUG-01_新增洗炉材料为普通文本.png'),
 Path('/Users/a77994/qa-skills/bug-reports/合金污染规则定义/BUG-01_导入模板缺少洗炉材料.png'),
 Path('/Users/a77994/qa-skills/bug-reports/合金污染规则定义/BUG-01_列表缺少洗炉材料列.png'),
]
pw=browser=ctx=page=None
results=[]
try:
 pw,browser,ctx,page=ones_helpers.connect()
 for img in imgs:
  try:
   url='https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/RsxEsWtX1524fec1'
   page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(4500)
   result=ones_helpers.append_task_description_images(page,'2YPZxEgX','RsxEsWtX1524fec1',[img],timeout=120)
   results.append({'file':img.name,'ok':True,'result':{k:v for k,v in result.items() if k!='after_html'}})
  except Exception as exc:
   results.append({'file':img.name,'ok':False,'error':str(exc)[:500]})
 print(json.dumps(results,ensure_ascii=False)[:12000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
