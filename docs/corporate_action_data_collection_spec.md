# 回购与减持事件数据搜集与交付规范

本文档是向“回购与减持”事件中心供数的统一契约，供人工研究员或其他 agent 使用。目标是搜集可核验的新闻线索并归档到 OSS；服务器随后统一完成结构化提取、链接去重、股票池匹配和 SQLite 入库。

## 1. 工作边界

- 覆盖市场：`us`（美股）、`cn`（A 股）、`hk`（港股）。
- 默认时间窗：最近 30 个自然日。每个批次应只包含来源页面发布时间落在约定时间窗内的事件。
- 搜索中心是公司回购和既有股东减持，不以项目股票池为检索条件。股票池匹配由服务器在入库后完成。
- 每一行只描述一个“公司 + 事件类型”候选。新闻同时涉及多家公司时，拆成多行；可复用同一 `source_url`，但每行的标题和摘要必须明确对应各自公司。
- agent 只上传标准化候选 JSONL，**不得**直接修改服务器 SQLite 数据库、股票池或前端数据。

## 2. 可纳入与必须排除的事件

### 可纳入

| `event_type` | 纳入情形 | 常见阶段 |
| --- | --- | --- |
| `buyback` | 上市公司已宣布、获授权、正在执行或已完成的股份回购；港股的股份回购及明确伴随回购的注销 | `announced`、`authorized`、`in_progress`、`executed`、`completed` |
| `reduction` | 现有主要股东、董事、高管、内幕人士、创始人或战略投资者的减持计划或实际出售股份 | `announced`、`in_progress`、`executed`、`completed` |

### 必须排除

- 员工期权归属、RSU 归属后为缴税进行的代扣代售，除非来源明确将其表述为重要股东减持。
- 被动指数基金调仓、ETF 申购赎回、基金普通持仓变化。
- 公司增发新股、配售、可转债转换、股权激励授予、稀释性发行；这些不是回购或既有股东减持。
- 只谈股价、估值、分析师观点或市场传闻，而没有明确公司回购/股东减持事实的内容。
- 转载中无法追溯原始来源、发布时间或受影响上市公司的内容。

不要根据常识补出数量、金额、证券代码、持股比例或行为主体；来源没有写明时，保持不写。服务器会依据标题和摘要做第二次结构化，不确定代码时允许以公司名入库。

## 3. 市场归类与来源要求

按受影响上市公司的交易市场填写 `market`，而不是按新闻媒体所在地填写。跨市场上市公司的同一事实，只有来源明确涉及相应上市证券时才分别提交。

来源优先级如下：

1. **一级来源（`primary`）**：公司 IR、交易所公告、监管申报。美股优先公司公告/SEC；A 股优先巨潮资讯、上交所、深交所；港股优先 HKEXnews 和公司公告。
2. **主流财经媒体（`mainstream`）**：可明确引用原始公告或当事方、并给出发布日期的权威财经报道。
3. **其他来源（`other`）**：聚合站、社区或二次转载只能作为线索；必须保留其可访问链接，且标题/摘要中仍应有足以确认事件的原始事实。

`published_at` 必须是该来源页面的发布时间，格式 `YYYY-MM-DD`，不要使用搜索引擎收录日期、抓取日期或报道中提到的历史事件日期。事件实际发生日与发布时间不同的，在 `snippet` 中如实说明。

## 4. JSONL 交付格式

文件必须是 UTF-8 编码的 `.jsonl`；每个非空行是一个独立 JSON 对象。UTF-8 BOM 可接受。不可上传 CSV、Excel、HTML、Markdown 或一个包含数组的 JSON 文件。

### 必填字段

| 字段 | 类型/可选值 | 要求 |
| --- | --- | --- |
| `schema_version` | 固定字符串 | 必须为 `corporate-action-candidate/v1` |
| `market` | `us` / `cn` / `hk` | 小写市场代码 |
| `event_type` | `buyback` / `reduction` | 只能二选一 |
| `headline` | 字符串 | 与该公司事件对应的事实性标题，最多 500 字符；可用中文概述，但不能改变原意 |
| `published_at` | `YYYY-MM-DD` | 来源页面的发布日期 |
| `source_url` | 绝对 `http`/`https` URL | 指向具体新闻、公告或申报，不得是搜索结果页或频道首页 |

### 可选字段

| 字段 | 可选值/格式 | 使用规则 |
| --- | --- | --- |
| `snippet` | 字符串，最多 2,000 字符 | 写明公司全称、代码（如原文有）、主体身份、数量/金额/比例、事件日期等可核验事实；可中文摘要，不能杜撰 |
| `event_stage` | `announced` / `authorized` / `in_progress` / `executed` / `completed` | 不确定时省略，服务器默认 `announced` |
| `source_quality` | `primary` / `mainstream` / `other` | 按上节来源等级填写；省略时服务器按链接域名推断 |
| `source_domain` | 域名 | 省略时服务器从 `source_url` 提取 |
| `source_agent` | 字符串，最多 200 字符 | 建议写固定 agent 标识，便于审计和反馈 |

当前导入接口以标题和摘要为结构化依据。若已知公司代码、法定名称或交易所，请把它们按原始来源事实写入 `headline` 或 `snippet`，不要依赖未定义的自造字段。

### 有效示例

以下链接域名仅用于展示字段格式，实际交付必须替换为真实、可访问的来源链接。

```jsonl
{"schema_version":"corporate-action-candidate/v1","source_agent":"us-buyback-agent","market":"us","event_type":"buyback","event_stage":"authorized","headline":"示例公司董事会批准最高 5 亿美元股份回购计划","snippet":"来源称 Example Corp（EXM）董事会批准最高 5 亿美元回购普通股；公告未披露具体执行日。","published_at":"2026-08-19","source_url":"https://example.com/news/example-buyback","source_domain":"example.com","source_quality":"primary"}
{"schema_version":"corporate-action-candidate/v1","source_agent":"cn-shareholder-agent","market":"cn","event_type":"reduction","event_stage":"announced","headline":"示例科技：持股 5% 以上股东披露减持计划","snippet":"公告显示，股东张某拟在规定期间减持不超过公司总股本 1.00%的股份；证券代码和公告日期以原公告为准。","published_at":"2026-08-19","source_url":"https://example.com/announcement/example-reduction","source_domain":"example.com","source_quality":"primary"}
```

## 5. 搜集与去重流程

1. 先按市场和事件类型广泛检索，不加入本项目股票池名称、代码或行业限制词。
2. 打开候选链接，核验受影响公司、行为、主体、发布时间和原始链接。
3. 为每个公司事件生成一行 JSONL。标题和摘要只保留该行公司可验证的事实。
4. 在单个批次内，按“规范化链接 + 公司 + `event_type`”自行去重；同一链接的更新报道或补充事实，可保留，但应在摘要中说明更新点。
5. 不要为了覆盖率重复上传旧文章。服务器仍会以市场、公司身份、事件类型和规范化链接做幂等去重。

标题、摘要可以翻译为中文以支持前端展示；数字、公司名称、代码、主体身份和行动方向必须与来源一致。无法可靠翻译时保留原文，并在摘要中给出忠实中文说明。

## 6. OSS 路径和上传约定

默认 OSS 入站前缀为：

```text
corporate-actions/v1/incoming/
```

推荐对象键：

```text
corporate-actions/v1/incoming/{market}/dt=YYYY-MM-DD/{source-agent}/{YYYYMMDDThhmmssZ}-{uuid}.jsonl
```

例如：

```text
corporate-actions/v1/incoming/hk/dt=2026-08-20/hk-repurchase-agent/20260820T023000Z-6f5495e3.jsonl
```

- 上传文件必须视为不可变对象：每次交付使用新的对象键，禁止覆盖历史文件。
- 一个文件可以包含多个市场，但推荐按市场拆分，便于失败重试和质量追踪。
- 不要把访问密钥、Cookie、搜索 API Key、完整网页正文或内部推理过程写进 OSS 对象。
- 上传 agent 应只被授予其专属前缀的 `PutObject` 权限；服务器导入账号需要 `GetObject`，定时前缀扫描还需要该前缀的 `ListObjects` 权限。

## 7. 交付前检查清单

- [ ] 每行都是有效 JSON，文件为 UTF-8 JSONL。
- [ ] 所有必填字段齐全，`schema_version` 和枚举值完全符合本规范。
- [ ] 链接能打开到具体来源，且 `published_at` 是该页面的发布日期。
- [ ] 事件确为上市公司回购或既有股东减持，未混入员工代扣、基金调仓或增发。
- [ ] 每行只对应一个公司事件；多公司文章已拆行。
- [ ] 摘要中的名称、代码、数量、金额、比例和主体均能在来源中找到依据。
- [ ] 同批次没有同一“链接 + 公司 + 事件类型”的重复行。
- [ ] 使用新的 OSS 对象键，未覆盖历史批次。

## 8. 服务器归档与反馈

服务器在配置 OSS 环境变量后可先做无写入检查：

```powershell
.\.venv\Scripts\python.exe -B scripts\import_corporate_action_oss.py --dry-run
```

再导入新对象：

```powershell
.\.venv\Scripts\python.exe -B scripts\import_corporate_action_oss.py
```

若服务器账号没有 `ListObjects` 权限，可按已知对象键导入：

```powershell
.\.venv\Scripts\python.exe -B scripts\import_corporate_action_oss.py --object-key corporate-actions/v1/incoming/cn/dt=2026-08-20/agent-a/batch.jsonl
```

导入器会记录 `bucket + object_key + ETag`。已成功或部分成功的同一对象版本不会重复导入；替换对象会产生新的 ETag，因此不允许覆盖历史对象。导入后由服务器完成结构化提取、链接标准化去重和股票池标记；股票池内事件自动为 `high` 关注级别，其余为 `normal`。
