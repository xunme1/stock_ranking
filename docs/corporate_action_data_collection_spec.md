# 回购与减持事件：新采集 Agent 作业规范（v2）

本文档是给新采集 agent 的**唯一交付规范**。目标是让 agent 直接产出可审计、可入库、可在前端展示的 V2 JSONL；服务器只做确定性校验、链接去重、股票池匹配和 SQLite 归档，**不会再用模型补猜 V2 的公司、日期、代码或数量**。

旧版 `corporate-action-candidate/v1` 仅为遗留兼容格式，不能用于新 agent。新任务一律使用 `corporate-action-event/v2`。

## 0. 一页式任务指令（可直接交给 agent）

> 在 `us`、`cn`、`hk` 市场分别搜索最近 30 个自然日的上市公司股份回购和既有股东减持。搜索不使用本项目股票池作为条件。打开并核验每个候选的原始页面；每行只交付一个明确的“公司 + 回购/减持事实”，使用 V2 JSONL。标题和摘要用忠实中文，所有数字、证券代码、日期、主体和行为方向必须来自 `evidence_text` 或来源页面；不确定即留空，不得推测。排除员工税务卖股、基金/ETF 调仓、公司增发和笼统市场评论。实际单日回购若原文明确披露，必须填写 `repurchase_shares`（股）和 `repurchase_shares_scope: "daily"`，以便生成价格走势柱状图。上传前按本规范的自检清单检查，并使用全新的 OSS 对象键。

## 1. 推荐工作流

1. **按市场独立搜集。** 美股、A 股、港股分别形成独立 JSONL 批次；每个市场同时覆盖 `buyback` 和 `reduction`。
2. **先找事件，再看股票池。** 不得在搜索词、筛选条件或入库条件中加入股票池公司、代码、行业或持仓限制。
3. **打开来源核验。** 搜索摘要只能作为线索。必须从具体新闻、公司公告、交易所公告或监管申报确认公司、事件、发布日期和链接。
4. **逐公司拆分。** 一条来源提及多家公司时，只有该来源能分别支持每家公司事实时才拆成多行；不得把“多只港股获回购”等汇总文章当成一个名为“港股多只个股”的事件。
5. **写 V2 事件。** 只填写来源明确披露的字段；将一小段能直接证明事件的原文放进 `evidence_text`。
6. **本批去重后上传。** 同一批内的 `agent_record_id` 必须唯一；同一“规范化链接 + 公司 + 事件类型”只保留一行。

## 2. 工作边界

- 覆盖市场：`us`（美股）、`cn`（A 股）、`hk`（港股）。
- 默认时间窗：最近 30 个自然日。每个批次应只包含来源页面发布时间落在约定时间窗内的事件。
- 搜索中心是公司回购和既有股东减持，不以项目股票池为检索条件。股票池匹配由服务器在入库后完成。
- 每一行只描述一个明确的“公司 + 事件类型 + 来源事实”。新闻同时涉及多家公司时可复用同一 `source_url`，但每行的证据、标题和摘要必须明确对应各自公司。
- agent 只上传标准化 JSONL，**不得**直接修改服务器 SQLite 数据库、股票池或前端数据。
- 同一公司同一类型的多次新闻会在页面中显示最新一条；较早的来源会自动归入“历史搜集记录”。因此应保留有新事实的后续公告/报道，不要为了避免重复而丢弃真实的执行更新。

## 3. 可纳入与必须排除的事件

### 可纳入

| `event_type` | 纳入情形 | 常见阶段 |
| --- | --- | --- |
| `buyback` | 上市公司已宣布、获授权、正在执行或已完成的股份回购；港股的股份回购及明确伴随回购的注销 | `announced`、`authorized`、`in_progress`、`executed`、`completed` |
| `reduction` | 现有主要股东、董事、高管、内幕人士、创始人或战略投资者的减持计划或实际出售股份 | `announced`、`in_progress`、`executed`、`completed` |

### 必须排除

- 员工期权归属、RSU 归属后为缴税进行的代扣代售，除非来源明确将其表述为重要股东减持。
- 被动指数基金调仓、ETF 申购赎回、基金普通持仓变化。
- 公募基金季报、北向/南向资金、券商席位或媒体根据持仓变化作出的“疑似减持”判断；除非来源明确指出既有股东/董事/高管实际出售或正式减持计划。
- 公司增发新股、配售、可转债转换、股权激励授予、稀释性发行；这些不是回购或既有股东减持。
- 只谈股价、估值、分析师观点或市场传闻，而没有明确公司回购/股东减持事实的内容。
- 转载中无法追溯原始来源、发布时间或受影响上市公司的内容。

不要根据常识补出数量、金额、证券代码、持股比例或行为主体；来源没有写明时，保持空值。代码不确定时可按公司名入库，但不要从相似名称猜代码。

## 4. 市场归类与来源要求

按受影响上市公司的交易市场填写 `market`，而不是按新闻媒体所在地填写。跨市场上市公司的同一事实，只有来源明确涉及相应上市证券时才分别提交。

来源优先级如下：

1. **一级来源（`primary`）**：公司 IR、交易所公告、监管申报。美股优先公司公告/SEC；A 股优先巨潮资讯、上交所、深交所；港股优先 HKEXnews 和公司公告。
2. **主流财经媒体（`mainstream`）**：可明确引用原始公告或当事方、并给出发布日期的权威财经报道。
3. **其他来源（`other`）**：聚合站、社区或二次转载只能作为线索；必须保留其可访问链接，且标题/摘要中仍应有足以确认事件的原始事实。

`published_at` 必须是该来源页面的发布时间，格式 `YYYY-MM-DD`，不要使用搜索引擎收录日期、抓取日期或报道中提到的历史事件日期。实际发生日不同的，填写 `event_date`；两者都必须能由来源支持。

## 5. V2 JSONL 交付格式

文件必须是 UTF-8 编码的 `.jsonl`；每个非空行是一个独立 JSON 对象。UTF-8 BOM 可接受。不可上传 CSV、Excel、HTML、Markdown 或一个包含数组的 JSON 文件。

### 首选：完整事件直入 v2

新采集 agent 必须使用 `schema_version: "corporate-action-event/v2"`。每一行是一个完整公司事件；通过校验后直接入库，不会二次调用 DeepSeek。

| 字段 | 要求 |
| --- | --- |
| `agent_record_id` | agent 在该 OSS 对象内唯一的稳定标识 |
| `source_agent` | 固定 agent 标识，最多 200 字符 |
| `market` | `us` / `cn` / `hk` |
| `company_name` | 受影响上市公司名称 |
| `event_type` | `buyback` / `reduction` |
| `event_stage` | `announced` / `authorized` / `in_progress` / `executed` / `completed` |
| `headline` | 原始标题或忠实原文标题，最多 500 字符 |
| `headline_zh` | 忠实中文标题，最多 500 字符；无可靠翻译时可与 `headline` 相同 |
| `summary_zh` | 中文事实摘要，最多 1,000 字符；只写已核验的公司、行动、主体、数量/金额、日期 |
| `published_at` | 来源页面发布日期，`YYYY-MM-DD` |
| `source_url` | 具体来源的绝对 HTTP(S) 链接 |
| `source_quality` | `primary` / `mainstream` / `other` |
| `confidence` | agent 置信度，必须在 `0.70` 到 `1.00` |
| `evidence_text` | 支撑该事件的短原文证据，最多 1,000 字符；必须能直接证明“谁、做了什么、何时/多少”（缺少的事实不补写），不得只写链接、结论或模型推理 |
| `repurchase_shares` | 可选；仅回购事件使用，必须是原文明确披露的实际股数数值，统一以“股”为单位，不得填“万股/百万股”等缩写单位或估算值 |
| `repurchase_shares_scope` | `repurchase_shares` 存在时必填：`daily`（单日实际回购）、`cumulative`（截至某日累计回购）或 `program_total`（计划/授权总额） |

可选字段：`ticker`、`exchange`、`actor_name`、`actor_type`、`quantity_text`、`amount_text`、`ownership_change_text`、`event_date`、`source_domain`、`repurchase_shares`、`repurchase_shares_scope`。日期字段一律为 `YYYY-MM-DD`。可选事实缺失时使用空字符串或省略，禁止补造。

代码填写规则：美股用交易代码（如 `MSFT`）；A 股用六位数字（如 `000001`）；港股用五位数字加 `.HK`（如 `00700.HK`）。若来源没有足以确认代码的信息，省略 `ticker`。

### 回购图表字段：必须区分口径

页面只有在以下四项同时满足时才显示“查看回购走势”：

1. `event_type` 是 `buyback`；
2. `event_stage` 是 `executed` 或 `completed`；
3. `event_date` 是实际回购发生日；
4. `repurchase_shares` 是该**单日实际回购**的纯数字股数，且 `repurchase_shares_scope` 为 `daily`。

常见正确写法：原文说“8 月 21 日回购 441.5 万股”，填 `repurchase_shares: 4415000`、`repurchase_shares_scope: "daily"`、`event_date: "2026-08-21"`。

- “截至某日累计回购 2,500 万股”填 `cumulative`，不会画成单日柱。
- “最多可回购 10% / 5 亿美元”属于授权或计划，应填 `program_total`（或只写 `amount_text`），不会画成单日柱。
- 不能从回购金额和股价反推股数；不确定是否为当日数时，不填 `repurchase_shares`。

`daily` 口径用于页面的回购走势柱状图，因此必须同时提供实际 `event_date`，且阶段必须是 `executed` 或 `completed`。累计口径和计划总额会保留为文字事实，**不会**被绘制成“当日回购”柱。

```jsonl
{"schema_version":"corporate-action-event/v2","agent_record_id":"hk-repurchase-20260820-001","source_agent":"hk-repurchase-agent","market":"hk","ticker":"00020.HK","company_name":"示例公司","exchange":"HKEX","event_type":"buyback","event_stage":"executed","headline":"Example Company repurchased shares","headline_zh":"示例公司已回购股份","summary_zh":"公告披露公司于指定日期回购股份，数量和金额以原公告为准。","quantity_text":"1,000,000 shares","repurchase_shares":1000000,"repurchase_shares_scope":"daily","amount_text":"HK$10,000,000","ownership_change_text":"","published_at":"2026-08-20","event_date":"2026-08-19","source_url":"https://example.com/announcement/example-buyback","source_domain":"example.com","source_quality":"primary","confidence":0.95,"evidence_text":"The Company repurchased 1,000,000 shares on 19 August 2026."}
```

未通过 v2 校验的行不会进入新闻主表，而会带着原始 JSON、来源对象键和错误原因进入隔离区，等待修复。不要把无效 v2 记录改为 v1 来规避校验。

### 遗留兼容：候选线索 v1

仅限既有遗留批次使用 `schema_version: "corporate-action-candidate/v1"`；服务器会对 v1 再次调用结构化模型。新 agent 不得因为字段不全或无法核验而降级为 V1，应舍弃该线索或补充核验后交付 V2。

### v1 必填字段

| 字段 | 类型/可选值 | 要求 |
| --- | --- | --- |
| `schema_version` | 固定字符串 | 必须为 `corporate-action-candidate/v1` |
| `market` | `us` / `cn` / `hk` | 小写市场代码 |
| `event_type` | `buyback` / `reduction` | 只能二选一 |
| `headline` | 字符串 | 与该公司事件对应的事实性标题，最多 500 字符；可用中文概述，但不能改变原意 |
| `published_at` | `YYYY-MM-DD` | 来源页面的发布日期 |
| `source_url` | 绝对 `http`/`https` URL | 指向具体新闻、公告或申报，不得是搜索结果页或频道首页 |

### v1 可选字段

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

## 6. 搜集与去重流程

1. 先按市场和事件类型广泛检索，不加入本项目股票池名称、代码或行业限制词。
2. 打开候选链接，核验受影响公司、行为、主体、发布时间和原始链接。
3. 为每个公司事件生成一行 JSONL。标题、摘要和 `evidence_text` 只保留该行公司可验证的事实。
4. 在单个批次内，按“规范化链接 + 公司 + `event_type`”自行去重；同一链接的更新报道或补充事实，可以保留为新来源，但摘要应说明这是新的执行/进展/完成事实。
5. 不要为了覆盖率重复上传旧文章。服务器仍会以市场、公司身份、事件类型和规范化链接做幂等去重。

标题、摘要可以翻译为中文以支持前端展示；数字、公司名称、代码、主体身份和行动方向必须与来源一致。无法可靠翻译时保留原文，并在摘要中给出忠实中文说明。

## 7. OSS 路径和上传约定

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
- 单个对象默认最多 `1,000` 个非空 JSONL 行；超过时整个对象会在入库前被拒绝。v1 候选行默认最多 `200` 条，避免触发过量服务器结构化调用；v2 完整事件不受该 v1 子限额影响。
- 新闻发布时间默认必须落在导入日期向前 `30` 天至向后 `1` 天的窗口内；服务器可通过 `CORPORATE_ACTION_OSS_LOOKBACK_DAYS` 调整回溯天数。超窗行会被隔离，不会进入新闻主表。
- 不要把访问密钥、Cookie、搜索 API Key、完整网页正文或内部推理过程写进 OSS 对象。
- 上传 agent 应只被授予其专属前缀的 `PutObject` 权限；服务器导入账号需要 `GetObject`，定时前缀扫描还需要该前缀的 `ListObjects` 权限。

## 8. 交付前检查清单

- [ ] 每行都是有效 JSON，文件为 UTF-8 JSONL。
- [ ] 所有必填字段齐全，`schema_version` 和枚举值完全符合本规范。
- [ ] 链接能打开到具体来源，且 `published_at` 是该页面的发布日期。
- [ ] 事件确为上市公司回购或既有股东减持，未混入员工代扣、基金调仓或增发。
- [ ] 每行只对应一个公司事件；多公司文章已拆行。
- [ ] 摘要中的名称、代码、数量、金额、比例和主体均能在来源中找到依据。
- [ ] `evidence_text` 是支撑本行事件的短原文，不是搜索摘要、链接或推理说明。
- [ ] 对已实施的单日回购，已按“股”填写 `repurchase_shares`、`daily` 和实际 `event_date`；累计数与计划额度没有冒充单日回购。
- [ ] 同批次没有同一“链接 + 公司 + 事件类型”的重复行。
- [ ] 使用新的 OSS 对象键，未覆盖历史批次。

## 9. 服务器归档与反馈

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

导入器会记录 `bucket + object_key + ETag`。已成功或部分成功的同一对象版本不会重复导入；替换对象会产生新的 ETag，因此不允许覆盖历史对象。导入后服务器对 V2 完成确定性校验、链接标准化去重和股票池标记；股票池内事件自动为 `high` 关注级别，其余为 `normal`。V2 校验失败行会进入隔离区并出现在导入摘要中；应修正后用新的对象键重新上传，不能改成 V1 规避校验。

如果服务器在模型或网络暂时故障后把对象记录为 `partial`，运维人员可在故障恢复后用 `--retry-partial` 重试同一对象版本；事件和隔离记录均为幂等写入。
