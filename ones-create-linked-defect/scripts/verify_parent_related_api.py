# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 base='https://ones.shuyilink.com/project/api/project/team/2YPZxEgX'
 for method,path in [('GET','/task/MH4B2YPuolKGjBLL/related_tasks'),('POST','/task/MH4B2YPuolKGjBLL/related_tasks')]:
  try:
   if method=='GET':r=page.request.fetch(base+path,method=method)
   else:r=page.request.fetch(base+path,method=method,headers={'Content-Type':'application/json'},data=json.dumps({'page':1,'size':100}))
   print(method,r.status,r.text()[:5000])
  except Exception as e:print(method,'ERR',str(e)[:300])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
