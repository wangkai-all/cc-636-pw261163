# 数据收件台

把 SPSS `.sav` 与 Stata `.dta` 读成一套**可核对**的结构化数据：先检查变量定义、取值标签、
日期起点与缺失规则，再选择字段与转换方式；某个缺失码要当作有效值试算时，先列出受影响的行、
统计范围与导出格式，确认后才生成新结果。原始文件与首次解释始终不变。

- 后端：Python 3.11 · pyreadstat 1.3.8 · FastAPI · pandas
- 前端：React 19 · TypeScript · Vite

## 快速开始

```bash
# 1) 后端依赖（仓库里已有 .venv 时可直接跳过）
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2) 前端依赖
cd frontend && npm install && cd ..

# 3) 生成演示样例（首次运行时自动生成也可以）
.venv/bin/python scripts/build_samples.py

# 4) 一条命令同时启动后端与前端
.venv/bin/python scripts/dev.py
#   后端 http://127.0.0.1:8000/api/health
#   前端 http://127.0.0.1:5173/
```

也可以分别启动：

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --reload
cd frontend && npm run dev        # Vite 已把 /api 代理到 127.0.0.1:8000
```

运行测试：

```bash
.venv/bin/python -m pytest backend/tests -q
cd frontend && npm run typecheck && npm run build
```

数据目录默认是 `<仓库>/data`（可用 `INTAKE_DATA_DIR` 覆盖），上传文件、首次解释与每次结果
都保存在这里；它已被 `.gitignore` 忽略。

## 页面流程

1. **读取**：拖入 `.sav`/`.dta`，或直接载入 `samples/` 下的两个演示文件。读取时会校验文件头
   （`$FL2`/`$FL3`/`<stata_dta>`），扩展名与内容不符会明确报错。
2. **检查定义**：左侧变量列表按字段展示存储类型/宽度、显示宽度、源格式、值标签、缺失规则与
   状态统计；右侧逐格对照「原始值 / 显示标签 / 分析值 / 缺失状态」，可读取全部行。
3. **字段与试算**：勾选字段与要保留的层，日期字段可选「按源格式解释」或「保留原始数值」；
   对某个缺失码选择「保持原义 / 恢复为有效值 / 设为指定值 / 转为系统缺失」。
4. **预览与确认**：列出每条转换命中的行号、转换前后统计（n、均值、标准差、最小/最大、零值）、
   输出列与可用导出格式。勾选确认后才会写新结果；预览令牌与当前选择不一致时后端返回 409。
5. **结果与核对**：查询（跨列关键词搜索）、分页查看、按格式下载；每个导出文件生成后立即重新
   读取，逐格比对值、值标签与缺失规则，并可随时点「重新读取并核对」再次验证。

## 语义约定

### 三层 + 状态

每个单元格同时保存：

| 层 | 含义 | 例 |
| --- | --- | --- |
| `raw` | 文件里实际存储的值 | `9`、`".a"`、`""` |
| `label` | 软件会显示的文本 | `拒答`、`2020-02-29` |
| `analysis` | 供分析使用的值，缺失为空 | `None`、`2020-02-29` |
| `state` | 缺失类型与试算标记 | `user_missing`、`missing_extended:.a->set` |

### 三类缺失互不合并

- **系统缺失**：空数值 / 空字符串 / Stata 基础缺失 `.`。
- **用户定义缺失**：SPSS 的离散码、区间与字符串缺失（如 `group=9`、`age∈[-9,-1]`、
  `remark="拒答"`），只对声明它的字段生效。
- **扩展缺失**：Stata `.a`–`.z`，以文本保留编码，与 `.` 和有效值都不同。

同一编码在不同字段可以含义不同（演示数据里 `9` 既是 `group` 的「拒答」，也是
`edu_years` 的「九年级」；`99` 既是有效年龄，也是满意度「拒答」）。因此**没有全局字典**：
标签和缺失规则都挂在单个字段上，数据集层面只报告冲突清单。

### 日期与时间

按源格式与显式起点换算，无法确定的格式拒绝解释：

| 来源 | 格式 | 起点 / 单位 |
| --- | --- | --- |
| SPSS | `DATE/ADATE/EDATE/JDATE/SDATE` | 1582-10-14，秒 |
| SPSS | `DATETIME` | 1582-10-14，秒 |
| SPSS | `TIME/DTIME/MTIME` | 时长（秒），没有日历起点 |
| Stata | `%td` | 1960-01-01，天（含小数时保留时间） |
| Stata | `%tc` / `%tC` | 1960-01-01，毫秒（`%tC` 的闰秒标度已标注未转换） |
| Stata | `%tm/%tq/%th/%ty` | 1960m1 / 1960q1 / 1960h1 / 日历年 |
| Stata | `%tw`、`%tb`、`%tg` | **不支持**：保留原值，`state=unsupported`，分析值为空 |

SPSS 中未知的数字格式同样标为 `unsupported`，不会被猜成普通数字。

### 字符串

编码、存储宽度（字节）与显示宽度（字符）分别记录；Stata `strL` 按 8 字节引用说明，并同时
给出观测最大字符数/字节数。

## 导入导出

| 格式 | 保留内容 | 已知限制 |
| --- | --- | --- |
| SAV | 变量标签、值标签、SPSS 用户缺失（离散/区间/字符串）、源日期格式 | 显示宽度按列内最长值重算 |
| DTA | 变量标签、值标签、扩展缺失码 `.a`–`.z`、源日期格式 | 没有 SPSS 显示宽度；SPSS 用户缺失无等价物 |
| CSV | 数据单元格；同目录 `result.schema.json` 保存标签与缺失规则 | UTF-8 BOM，缺失为空字符串 |
| XLSX | `data` + `dictionary` + `readme` 三个工作表 | 标签/缺失含义只在 dictionary 中 |

导出的 `sav`/`dta` 重新读取后，逐格核对三层值；SPSS 缺失规则与 Stata 扩展码分别与清单比对，
而不是只比较行数。CSV/XLSX 的核对以对应的 schema/dictionary 为准。

## 目录

```
backend/app/       reader / missing / timecodes / compiler / export / dta_io / storage / main
backend/tests/     读取语义、时间换算、DTA 字节补丁、编译器、四种格式往返、API 全流程
frontend/src/      React 收件台（Intake → Workspace → Configure → Results）
frontend/scripts/  以 SSR 渲染四个视图的冒烟检查
samples/           demo_intake.sav / demo_intake.dta（12 行，两层来源的同一批问卷）
scripts/           build_samples.py 生成样例；dev.py 同时启动前后端
```

## 演示数据里有什么

12 行问卷，同时包含：

- 带标签的有效零：`group=0`「对照组（有效零）」、`satisfaction=0`「零分（有效零值）」；
- 多种缺失：SAV 的离散缺失（`group=9`、`satisfaction=99`）、区间缺失（`age=-3/-5`）、
  字符串缺失（`remark="拒答"`）、系统缺失；DTA 的扩展缺失 `.a`/`.b`/`.c`；
- 日期与时间：日期、日期时间、SPSS `MTIME` 时长、Stata `%tm` 月份；
- 长中文字符串：`note` 在 SAV 中存储宽度 6021 字节、显示宽度 40 字符（观测最长 2527 字符 / 6021 字节）；
- 不支持的格式：DTA 的 `%tw` 周编号列；
- 跨字段编码冲突：`9`、`99`、`0`、`1`、`2`。
