# -*- coding: utf-8 -*-
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';task='RsxEsWtX1524fec1'
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 keep={'BUG-01_列表缺少洗炉材料列.png':'991oXGVT','BUG-01_新增洗炉材料为普通文本.png':'VDBj3Xk4','BUG-01_导入模板.xlsx':'Vqy6MpKK','BUG-01_导入模板缺少洗炉材料.png':'QbmM98nT'}
 atts=(ones_helpers.get_task_attachments(page,team,task) or {}).get('attachments') or []
 delete=[]
 for a in atts:
  name=a.get('name');uid=a.get('uuid')
  if name in keep and uid!=keep[name]:delete.append(uid)
 resp=page.request.fetch(f'https://ones.shuyilink.com/project/api/project/team/{team}/res/attachments/delete',method='POST',headers={'Content-Type':'application/json'},data=json.dumps(delete,ensure_ascii=False))
 print('delete status',resp.status,'body',resp.text()[:1000],'uuids',delete)
 time.sleep(3)
 after=(ones_helpers.get_task_attachments(page,team,task) or {}).get('attachments') or []
 print('after',len(after),[(a.get('uuid'),a.get('name')) for a in after])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
