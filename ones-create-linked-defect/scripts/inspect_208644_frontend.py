# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 info=ones_helpers.get_task_info(page,'2YPZxEgX','RsxEsWtXc6881d6f') or {}
 fv={f.get('field_uuid'):f.get('value') for f in (info.get('field_values') or [])}
 hits=ones_helpers.search_user(page,'2YPZxEgX','王斌') or {}
 print(json.dumps({'summary':info.get('summary'),'handler_uuid':fv.get('95jUV2Mb'),'user_search':hits},ensure_ascii=False)[:12000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
