# -*- coding: utf-8 -*-
import json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';parent='MH4B2YPuolKGjBLL'
items=[
 ('BUG-01','208638','RsxEsWtX1524fec1','撤回关闭','洗炉材料字段未按需求实现且列表/导入均缺失'),
 ('BUG-02','208640','RsxEsWtX9a82b286','撤回关闭，需求变更非必填','导入污染源牌号标为非必填且空值成功落库'),
 ('BUG-03','208641','RsxEsWtXfecc0a71','有效','导入未校验污染源/目标牌号是否来自产品信息'),
 ('BUG-04','208642','RsxEsWtXc4329d1b','有效','500字以内中文规则说明触发数据库异常并终止整批导入'),
 ('BUG-05','208643','RsxEsWtX76bd25f0','有效','删除/审核/取消审核确认弹窗文案与需求不一致'),
 ('BUG-06','208644','RsxEsWtXc6881d6f','撤回关闭，非缺陷待前端修改','新增/编辑弹框未按补充规则移除洗炉材料字段'),
 ('BUG-07','208657','RsxEsWtXbd7612cb','有效','列表筛选后分页总数和页数未更新'),
 ('BUG-08','208658','RsxEsWtX12a88046','有效','导出未应用当前筛选且多个列值为空'),
]
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 rows=[]
 for key,num,uuid,state,title_part in items:
  info=ones_helpers.get_task_info(page,team,uuid) or {}
  fv={f.get('field_uuid'):f.get('value') for f in (info.get('field_values') or [])}
  html=str(fv.get('field016') or info.get('desc_rich') or '')
  rows.append({'key':key,'number':info.get('number'),'uuid':uuid,'state':state,'summary':info.get('summary'),'status_uuid':info.get('status_uuid'),'image_count':len(re.findall(r'<img',html)),'title_match':title_part in (info.get('summary') or '')})
 # Use page body comments to verify all related links were created; the parent related widget is virtualized.
 page.goto(f'https://ones.shuyilink.com/project/#/team/{team}/task/{parent}',wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(5000)
 body=page.locator('body').inner_text() or ''
 related_hits={r['key']: body.count('新增关联工作项')>=0 and r['title_match'] and r['summary'] in body for r in rows}
 result={'items':rows,'parent_url':page.url,'related_hits':related_hits,'related_comments':body.count('新增关联工作项'),'withdraw_comment':('本单撤回并关闭' in body)}
 out=Path('/Users/a77994/qa-skills/runs/2026-09-28_合金污染规则定义/json/ones_final_submission_verification.json');out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False)[:25000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
