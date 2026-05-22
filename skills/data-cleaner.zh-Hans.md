---
name: data-cleaner
description: 将任意记账工具（YNAB、Mint、银行导出、自定义表格等）的财务数据清洗为 Prospere 标准格式。支持 CSV、TSV、XLSX。
---

# 数据清洗器

将任意来源的财务数据文件转换为 Prospere 的标准输入格式：
- `processed_transactions.xlsx`（7 列：`unique_id`、`transaction_date`、`amount`、`currency`、`primary_category`、`secondary_category`、`account_name`）
- `processed_balances.json`（数组：`{account_name, balance, currency}`）

## 使用方式

```
/data-cleaner [file_path]
```

如果未提供文件路径，请向用户询问。

## 安装

将此文件复制到 `~/.claude/skills/` 或项目的 `.claude/skills/` 目录：

```bash
mkdir -p ~/.claude/skills
cp skills/data-cleaner.zh-Hans.md ~/.claude/skills/data-cleaner.md
```

## 前置条件

此 skill 依赖 Prospere 已安装。使用前请确保用户已运行 `pip install prospere` 或 `uv sync`。

检测方式：
```python
try:
    from prospere.ingestion.cleaner import analyze_file, clean_dataframe, suggest_column_mappings
    from prospere.ingestion.writer import write_dataset
    HAS_CLEANER = True
except ImportError:
    HAS_CLEANER = False
```

如果 `HAS_CLEANER` 为 False，告知用户先安装 Prospere。

## 工作流程

### 步骤 1：分析文件

调用 `cleaner.py` 的 `analyze_file(file_path)`。向用户呈现 `FileAnalysis` 结果：

1. 文件类型、编码、分隔符
2. 总行数、列数
3. 所有列的类型及示例值
4. `suggest_column_mappings()` 的建议列映射

### 步骤 2：确认列映射

展示建议的列映射，请用户确认或手动调整。

列映射规则请直接阅读 `cleaner.py` 源码中的 `_HEURISTIC_KEYWORDS`，匹配优先级为：精确 > 规范化精确 > 包含 > 前缀。

**特殊情况**：
- **MoneyWiz 格式**：如果 `is_moneywiz_format()` 返回 True，告知用户文件已是 MoneyWiz 格式，建议使用标准导入流程
- **缺少日期列**：停止并解释——日期为必需字段
- **缺少金额列**：停止并解释——金额为必需字段
- **超大文件（>10,000 行）**：建议先取样处理

用户可以：
- 确认自动匹配结果
- 覆写特定列的映射
- 告知特殊格式（如「金额列包含 $ 前缀和括号负数」）
- 指定分类分隔符（如 `::` 或 `>`）

### 步骤 3：清洗数据

用确认的映射构建 `ColumnHeuristics`，调用 `clean_dataframe(df, mapping)`：

```python
from prospere.ingestion.cleaner import ColumnHeuristics, clean_dataframe

mapping = ColumnHeuristics(
    date_column=用户确认的日期列,
    amount_column=用户确认的金额列,
    # ... 其他字段
)

transactions, balances = clean_dataframe(df, mapping)
```

`clean_dataframe` 返回 `list[Transaction]` 和 `list[AccountBalance]` —— 与 MoneyWiz 引擎相同的类型。清洗规则（`_DATE_FORMATS`、`_CATEGORY_DELIMITERS`、`_CURRENCY_SYMBOL_MAP`、`_KNOWN_ISO_CODES`）全部在 `cleaner.py` 源码中定义。

**展示清洗摘要**：
- 成功解析的日期数
- 已规范化的金额数
- 已标准化的货币数
- 生成的主分类/子分类
- 提取的余额记录数（如有）
- 生成的唯一 ID 数

### 步骤 4：写入并验证

询问用户输出位置：
- **选项 A**：写入 Prospere 工作区（需提供 `user` 和 `snapshot` 名称）
- **选项 B**：写入自定义目录

使用共享写入管线：
```python
from prospere.ingestion.writer import write_dataset

success, msg = write_dataset(transactions, balances, xlsx_path, json_path)
```

选 A 时，同时复制到工作区：
```python
from prospere.cli.process import import_preprocessed
success, msg = import_preprocessed(user, snapshot, xlsx_path, json_path)
```

**报告最终结果**：
- 「已清洗 X 笔交易和 Y 个余额。验证通过。」
- 或显示验证失败的具体原因。

### 步骤 5：建议后续操作

- 运行 `prospere` 启动 TUI 菜单进行模拟
- 使用引导向导基于此数据创建场景

## 边缘情况

### 仅有余额无交易
`clean_dataframe` 返回空 transactions 列表。告知用户余额已导入，但需要交易数据才能计算波动率并运行模拟。

### 编码错误
`analyze_file` 按顺序尝试：utf-8-sig → utf-8 → latin-1 → cp1252。全部失败则显示错误并建议检查文件完整性。

### 同名列冲突
如果多个列匹配同一个标准字段，列出冲突并请用户手动选择。

### 无标题行
如果文件没有标题行（列为数字索引），展示前 3 行数据并请用户提供列名。

### 负数表示不一致
检查金额分布：如果大部分值为负数，可能方向相反，询问用户是否需要翻转符号。
