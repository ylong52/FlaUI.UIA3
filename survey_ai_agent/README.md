# survey_ai_agent

独立的英文问卷分析与答题服务：接收完整问卷 HTML 与受访者资料，自动识别题目/选项/题型，
调用 **PydanticAI + DeepSeek V3**（OpenAI-compatible API）生成整页结构化答题计划，并做
格式与逻辑一致性校验。服务不依赖 Codex / Claude Code。

- 语言：Python 3.11+
- Agent：PydanticAI 2.65（`OpenAIChatModel` + `OpenAIProvider`，注册
  `lookup_profile_fact` / `lookup_history_answer` 两个只读工具）
- 模型：DeepSeek（模型名可配置，默认 API 别名 `deepseek-chat`）
- 解析：BeautifulSoup + lxml
- 接口：FastAPI
- 持久化：MySQL / MariaDB，与 `survey_bg_manage` **共用同一个数据库**，新增表统一 `ai_agent_*` 前缀
- 测试：pytest（30 个）

---

## 一、目录结构

```text
survey_ai_agent/
├── main.py                    # uvicorn 入口
├── config.py                  # 环境变量 / .env 配置
├── agent/
│   ├── survey_agent.py        # 主流程：提取 → 复用 → 生成 → 校验 → 落库
│   ├── model_client.py        # PydanticAI + DeepSeek 客户端、错误分类、重试、超时
│   ├── question_analyzer.py   # 内置任务指令、LLM 结构化输出、提示词
│   ├── answer_engine.py       # mock/规则引擎（只使用真实资料）
│   ├── context_manager.py     # 任务上下文
│   └── answer_validator.py    # 选项/数量/范围/互斥/条件/历史一致性校验
├── parser/
│   ├── html_parser.py
│   ├── question_extractor.py
│   └── option_extractor.py
├── schemas/
│   ├── request.py
│   ├── question.py
│   └── answer.py
├── api/routes.py
├── storage/
│   ├── base.py
│   ├── memory_store.py        # 测试 / 无数据库时使用
│   ├── mysql_store.py         # 共用 survey_bg_manage 库
│   └── schema.sql
├── scripts/
│   ├── init_db.py             # 初始化 ai_agent_* 表
│   ├── inspect_page.py        # 解析任意 HTML，打印题目概览
│   └── live_check.py          # 本地接口联调
├── tests/
└── README.md
```

---

## 二、快速开始

### 1. 启动 MariaDB

便携版 MariaDB 与数据目录已随项目一起维护，位于项目根目录 `tools\` 下（不再依赖
`survey_bg_manage` 源码目录）：

```powershell
& "E:\chromium_dev_items\FlaUI.UIA3\tools\mariadb\bin\mariadbd.exe" `
  --basedir="E:\chromium_dev_items\FlaUI.UIA3\tools\mariadb" `
  --datadir="E:\chromium_dev_items\FlaUI.UIA3\tools\mariadb-data" `
  --port=3306 --bind-address=127.0.0.1 --console
```

> `start.cmd` 的 `[1/5]` 会自动完成同样的启动与 40 秒等待，无需手工执行。
> 库名仍为 `survey_bg_manage`（仅作为 SQL 库名保留），二进制与数据都在项目内。

首次在新机器上初始化数据目录：

```powershell
& "E:\chromium_dev_items\FlaUI.UIA3\tools\mariadb\bin\mariadb-install-db.exe" `
  "--datadir=E:\chromium_dev_items\FlaUI.UIA3\tools\mariadb-data" "--password=" "--port=3306"
```

### 2. 安装依赖

项目已带 `.venv`（Python 3.12.15）。重新安装：

```powershell
cd E:\chromium_dev_items\FlaUI.UIA3\survey_ai_agent
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

### 3. 配置

**DeepSeek Key 的配置文件是项目根目录下的 `.env`（绝对路径）：**

```text
E:\chromium_dev_items\FlaUI.UIA3\survey_ai_agent\.env
```

填写这一行：

```dotenv
SURVEY_AI_DEEPSEEK_API_KEY=sk-你的真实Key
```

`.env.example` 是模板；`.env` 已被 `.gitignore` 忽略，不会提交。
代码使用绝对路径读取该文件，从其他工作目录启动也能生效。系统环境变量优先级更高，
可用于临时覆盖。

与问卷库共用的配置默认已匹配：

```dotenv
SURVEY_AI_DB_HOST=127.0.0.1
SURVEY_AI_DB_PORT=3306
SURVEY_AI_DB_USER=root
SURVEY_AI_DB_PASSWORD=
SURVEY_AI_DB_NAME=survey_bg_manage
```

DeepSeek：

```dotenv
SURVEY_AI_LLM_MODE=deepseek
SURVEY_AI_DEEPSEEK_API_KEY=         # 必填，未配置时 analyze 返回 502
SURVEY_AI_DEEPSEEK_BASE_URL=https://api.deepseek.com
SURVEY_AI_DEEPSEEK_MODEL=deepseek-chat
```

**模型名说明**：`deepseek-chat` 是 DeepSeek 的 API 别名（当前指向 V3 系列）；如需固定版本，
请填写服务商提供的版本化模型 ID。二者不要混为一谈，代码只做透传，不做版本映射。

也兼容 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` 以及
`survey_bg_manage` 的 `SB_DB_*` 变量名。

`SURVEY_AI_LLM_MODE`：

- `deepseek`（默认）：必须真实调用；无 Key 直接返回明确错误，不产生假成功。
- `mock`：确定性规则模式，只用资料/历史，绝不编造个人事实；测试与离线演示用。
- `auto`：有 Key 用 DeepSeek，否则 mock。

### 4. 初始化表

```powershell
.venv\Scripts\python.exe scripts\init_db.py
```

会在 `survey_bg_manage` 库中创建：

- `ai_agent_tasks`
- `ai_agent_pages`
- `ai_agent_answers`
- `ai_agent_context`
- `ai_agent_llm_usage`

### 5. 启动服务

```powershell
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8790
```

健康检查：

```powershell
curl http://127.0.0.1:8790/healthz
```

---

## 三、接口

### POST /api/v1/agent/analyze

请求：

```json
{
  "task_id": "task_001",
  "page_id": "page_001",
  "html": "<html>...</html>",
  "respondent_profile": {
    "age": 29,
    "country": "CN",
    "products": ["Pumps"],
    "years": 5
  },
  "answer_history": [],
  "respondent_id": null,
  "survey_id": null
}
```

- `respondent_profile` 可为空；涉及个人事实的题目会返回 `needs_review`。
- `respondent_id` 可选：会从同库的 `inv_respondent_profiles`（找不到再查
  `survey_responses`）补齐年龄、性别、国家等，请求中的资料优先。
- `answer_history` 可选：跨页面已确认答案。

响应：

```json
{
  "task_id": "task_001",
  "page_id": "page_001",
  "status": "partial",
  "answers": [
    {
      "question_id": "Q1",
      "question_type": "single_choice",
      "selected_options": ["25-34"],
      "answer_text": null,
      "status": "ready",
      "source": "respondent_profile"
    }
  ],
  "questions": [
    {
      "question_id": "Q1",
      "text": "How old are you?",
      "question_type": "single_choice",
      "options": [{"id": "25-34", "label": "25-34"}],
      "...": "..."
    }
  ],
  "usage": {"model": "deepseek-chat", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "warnings": []
}
```

`answers[].status`：`ready` / `needs_review` / `skipped` / `invalid`。
页面 `status`：`complete` / `partial` / `error`（请求级错误走 HTTP 错误码）。

答案字段：

- `selected_options`：单选/多选/下拉的选项 ID
- `answer_text`：文本题答案
- `matrix_selections`：`{row_id: column_id}`
- `ranking`：排序题完整顺序（全部选项 ID）
- `numeric_value`：数字题/评分题数值

其他接口：

- `GET /healthz`：DB 与模型配置状态
- `GET /api/v1/tasks/{task_id}/context`：任务上下文

错误格式统一：

```json
{"error": {"code": "llm_not_configured", "message": "..."}}
```

关键错误码：

| code | HTTP | 场景 |
|---|---|---|
| `no_questions` | 400 | HTML 中识别不到题目 |
| `llm_not_configured` | 502 | deepseek 模式但未配置 Key |
| `llm_upstream_error` | 502 | DeepSeek 超时/失败/输出校验失败 |
| `store_unavailable` | 503 | MySQL 不可用 |
| `internal_error` | 500 | 未预期异常（不返回假成功） |

---

## 四、题型识别

综合题干文字、控件语义、选项结构、题目容器来判断，不只看标签名：

- 单选：同名 `radio` 组 / `role=radio(group)`
- 多选：同名 `checkbox` 组 / `role=checkbox`
- 文本：`textarea`、`input[type=text/email/tel/url]`、`contenteditable`
- 数字：`input[type=number]`、`inputmode=numeric/decimal`、`role=spinbutton`
- 下拉：`select`（`multiple` 视为多选）、`role=combobox`
- 矩阵：包含 radio 的 `table`，行列来自表头与行标题
- 评分：`input[type=range]`、`role=slider`
- 排序：`rank/sort/order/draggable` 列表
- 条件题：`data-depends-on` + `data-depends-value`（或 `data-show-if`)元数据

无法可靠识别时返回 `unknown`，校验阶段转为 `needs_review`。

### 关于 Vue / 动态页面

- **请提交渲染后的 DOM**（如 `document.documentElement.outerHTML`），不要提交 Vue 模板源码。
  模板源码里的 `v-for` 只对应一个占位节点，选项是 `{{ o }}` 这类未解析文本。
- 选项里出现未解析模板时标记 `options_unresolved`，该题强制 `needs_review`，不会瞎猜。
- 题干被替换成无 `alt` 图片时标记 `text_unavailable`；若选项能推断出年龄/国家/性别，则用
  推断主题继续安全匹配资料，否则 `needs_review`。

---

## 五、答案生成与安全规则

1. 个人事实只能来自 `respondent_profile` / 已确认历史 / 显式结构化答案。
   其他来源一律 `needs_review` 并清空答案。
2. 没有资料时返回 `needs_review`，不编造购买经历、品牌使用、身份信息。
3. 单选只能选一个；多选检查 `min/max`；`None of the above` 等互斥项不能与其他项同选。
4. 数字/评分检查 `min/max`；文本必填检查非空。
5. 矩阵必须覆盖全部必填行且列 ID 有效；排序必须是页面全部选项的一个排列。
6. 年龄答案与资料年龄不一致、国家与资料不一致、与历史答案冲突 → `needs_review`。
7. 条件题依赖未满足 → `skipped`。
8. LLM 输出统一经 Pydantic + 业务校验；任何选项 ID 不存在都会被拒绝。

---

## 六、动态页面与增量分析

- 每道题计算 `fingerprint`（题干 + 题型 + 选项/矩阵结构）。
- 同一 `task_id` 下再次提交页面时，未变化且已验证的 `ready` 答案直接复用，不再调用模型。
- 资料发生变化时，个人事实题会重新分析；其余未变化题目继续复用。
- 新增/修改的题目进入新一轮分析；删除的题目不再出现在当前页答案中。
- 上下文（资料、已确认答案、页面哈希）保存在 `ai_agent_context`。

---

## 七、测试

```powershell
# 单元 + API 测试
.venv\Scripts\python.exe -m pytest -q

# 真实 MySQL 集成测试（需要 MariaDB 运行）
$env:SURVEY_AI_TEST_MYSQL="1"
.venv\Scripts\python.exe -m pytest tests/test_mysql_store.py -q
```

当前结果：

- `29 passed, 1 skipped`（默认）
- 打开 MySQL 集成后：`1 passed`（合计 30 个）

覆盖：题目/选项提取、9 类题型、图片题干、模板选项、单选/多选/互斥/矩阵/排序/数字范围、
年龄与国家一致性、个人事实分类与保护、条件题跳过、mock 分析、规则预填（个人事实不交给模型）、
增量复用、FastAPI 200/400/422/502、PydanticAI 结构化输出契约、DeepSeek Agent 与只读工具注册
（不联网）、MySQL 往返。

### 真实环境验证

- mock + MySQL：`POST /api/v1/agent/analyze` 返回 200；4 题 `ready`、6 题 `needs_review`、
  1 题 `skipped`，页面 `partial`；答案/页面/上下文均已写入 `survey_bg_manage`。
- 未配置 Key 的隔离配置下：`healthz` 显示 `configured=false`，`analyze` 返回
  **502 `llm_not_configured`**，没有产生任何假成功结果。
- **配置真实 DeepSeek Key 后**：真实 `POST https://api.deepseek.com/chat/completions`
  返回 200，页面 `partial`，本次使用 **9689 tokens**（prompt 8976 / completion 713），
  用量已写入 `ai_agent_llm_usage`：
  - Q1/Q2/Q4/Q8：由资料确定性作答（`respondent_profile`）
  - Q3 开放题、Q6 评分 90、Q7 排序（完整排列）：由 DeepSeek 作答（`llm_inference`）
  - Q5 矩阵：缺公司实践资料 → `needs_review`
  - Q9：条件依赖不满足 → `skipped`
  - Q10 性别：资料缺性别 → `needs_review`
  - Q11：选项为未解析模板 → `needs_review`
- 真实测试页 `survey-test.html` 原始模板：识别出 15 个题目节点，动态选项正确标记
  `options_unresolved`；排序题因模板只有一个 `v-for` 占位节点而无法展开（提交渲染 DOM 即可）。

---

## 八、已知限制

- 条件表达式只识别 `data-depends-on` / `data-depends-value` / `data-show-if` 元数据，
  不执行任意 JS/Vue 表达式。
- 题干是图片时只能从选项推断 age/country/gender，其余主题返回 `needs_review`。
- 矩阵列 ID 优先取输入框 `value`，否则按表头生成 `col_N`；执行端需按同一映射回填。
- 排序题需要渲染后的全部列表项；单占位节点会被视为无法解析。
- DeepSeek 真实调用的准确性依赖模型；服务层只保证结构合法、选项存在、不编造个人事实。
- MySQL 表自动创建；生产环境可关闭 `SURVEY_AI_DB_AUTO_INIT` 并用 `scripts/init_db.py` 预建。

---

## 九、执行端对接约定

外部程序负责把答案计划落到页面上：

1. 用 `question_id` 找到控件容器。
2. 单选/多选/下拉：按 `selected_options` 中的选项 ID 点击/选择。
3. 文本：填写 `answer_text`。
4. 数字/评分：填写 `numeric_value`。
5. 矩阵：按 `matrix_selections` 的 `row_id -> column_id` 选择。
6. 排序：按 `ranking` 顺序重排。
7. 只执行 `status == "ready"` 的题目；`needs_review` 交人工确认，`skipped` 不操作。
