# 数据库与接口辅助

优先复用本机 DataGrip 已配置的连接（内含各环境、各环节数据库），不要要求用户重新提供连接串；
需要数据查验/数据对比时，自行连接查询。

1. 自动发现：`python scripts/datagrip_datasources.py list` 列出 DataGrip 中所有数据源
   （名称、类型、地址、用户、密码状态）。扫描范围：DataGrip 全局配置
   （各版本 `options/dataSources/`）+ 项目级配置
   （默认 `~/DataGripProjects/*/.idea/dataSources.xml`，
   可用环境变量 `DATAGRIP_PROJECTS_DIR` 指定其它项目根）。
2. 查数据：`python scripts/datagrip_datasources.py query <数据源名> "SELECT ..." [--limit N]`；
   列结构：`tables <数据源名>`；详情：`info <数据源名>`。
3. 连接方式：脚本按 DataGrip 配置的地址**直接走本机网络**连接
   （DataGrip 能连的库脚本就能连，无需额外解析/隧道配置）；
   若在受网络限制的沙箱环境执行报 DNS/`Operation not permitted`，改用非沙箱方式运行。
4. 凭据：本技能**不含任何账号密码**（可安全分享）。连接凭据按顺序取：
   环境变量 `DB_PASSWORD_<数据源名>` → 本机用户凭据文件
   `~/.codex/credentials/databases.yaml`（默认 `default_user` / `default_password`，
   个别库可在 `databases` 下覆盖）→ DataGrip 明文（老版本）→ 空密码。
   技能内 `scripts/config/databases.yaml` 仅为无密码模板，不要写真实凭据；
   可用环境变量 `DATAGRIP_CREDENTIALS_FILE` 指定其它凭据文件。
5. 连接数据库前先确认环境（生产/测试/预发布），每个环境连接地址不同，以 DataGrip 数据源名称为准。
6. 数据库只允许用户授权范围内的 `SELECT`，禁止增删改、建表、锁表、压测查询
   （脚本已强制只读，非 SELECT/WITH 拒绝执行）。
7. 查询前先限制范围：使用主键、单号、条码、时间窗口、`LIMIT`。
8. 遇到查询超时，先改写为窄条件查询或只查必要字段，避免 `SELECT *` 和无索引大范围扫描。
9. 接口请求中必须脱敏 Authorization、Cookie、手机号、身份证、真实姓名等敏感值。
10. 页面、接口、数据库结果不一致时，优先输出核对 SQL 或核对口径，避免直接武断定性。
11. 核心链路（新增/编辑/删除）执行后，主动查对应库表做"页面 vs 数据库"一致性核对
    （数量、编号、创建人、状态字段），发现差异即为缺陷证据。
