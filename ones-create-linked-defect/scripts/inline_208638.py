# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
imgs=[
 Path('/Users/a77994/qa-skills/bug-reports/合金污染规则定义/BUG-01_新增洗炉材料为普通文本.png'),
 Path('/Users/a77994/qa-skills/bug-reports/合金污染规则定义/BUG-01_导入模板缺少洗炉材料.png'),
 Path('/Users/a77994/qa-skills/bug-reports/合金污染规则定义/BUG-01_列表缺少洗炉材料列.png'),
]
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 url='https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/RsxEsWtX1524fec1'
 page.goto(url,wait_until='domcontentloaded',timeout=60000)
 page.wait_for_timeout(6000)
 loc=page.locator('.richtext-input-viewer-wrapper')
 print('viewer count',loc.count(),'visible',loc.first.is_visible() if loc.count() else None,'box',loc.first.bounding_box() if loc.count() else None)
 page.screenshot(path='/Users/a77994/qa-skills/runs/2026-09-28_合金污染规则定义/bug-reports/合金污染规则定义/BUG-01_编辑描述页.png',full_page=True)
 result=ones_helpers.append_task_description_images(page,'2YPZxEgX','RsxEsWtX1524fec1',imgs,timeout=180)
 print(json.dumps({k:v for k,v in result.items() if k!='after_html'},ensure_ascii=False))
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
