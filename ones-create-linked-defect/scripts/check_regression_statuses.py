# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
items=[('208641','RsxEsWtXfecc0a71'),('208642','RsxEsWtXc4329d1b'),('208643','RsxEsWtX76bd25f0'),('208644','RsxEsWtXc6881d6f'),('208657','RsxEsWtXbd7612cb')]
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 out=[]
 for num,uuid in items:
  info=ones_helpers.get_task_info(page,'2YPZxEgX',uuid) or {};tr=(ones_helpers.get_transitions(page,'2YPZxEgX',uuid) or {}).get('transitions') or []
  out.append({'number':num,'summary':info.get('summary'),'status_uuid':info.get('status_uuid'),'transitions':[{'name':t.get('name'),'end_status_uuid':t.get('end_status_uuid')} for t in tr]})
 print(json.dumps(out,ensure_ascii=False,indent=2)[:18000])
finally:
 if pw is not None:ones_helpers.disconnect(pw)
