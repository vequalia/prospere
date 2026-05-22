---
name: data-cleaner
description: 將任意記帳工具（YNAB、Mint、銀行匯出、自訂表格等）的財務數據清理為 Prospere 標準格式。支援 CSV、TSV、XLSX。
---

# 數據清理器

將任意來源的財務數據檔案轉換為 Prospere 的標準輸入格式：
- `processed_transactions.xlsx`（7 欄：`unique_id`、`transaction_date`、`amount`、`currency`、`primary_category`、`secondary_category`、`account_name`）
- `processed_balances.json`（陣列：`{account_name, balance, currency}`）

## 使用方式

```
/data-cleaner [file_path]
```

如果未提供檔案路徑，請向使用者詢問。

## 安裝

將此檔案複製到 `~/.claude/skills/` 或專案的 `.claude/skills/` 目錄：

```bash
mkdir -p ~/.claude/skills
cp skills/data-cleaner.zh-Hant.md ~/.claude/skills/data-cleaner.md
```

## 前置條件

此 skill 依賴 Prospere 已安裝。使用前請確保使用者已執行 `pip install prospere` 或 `uv sync`。

檢測方式：
```python
try:
    from prospere.ingestion.cleaner import analyze_file, clean_dataframe, suggest_column_mappings
    from prospere.ingestion.writer import write_dataset
    HAS_CLEANER = True
except ImportError:
    HAS_CLEANER = False
```

如果 `HAS_CLEANER` 為 False，告知使用者先安裝 Prospere。

## 工作流程

### 步驟 1：分析檔案

呼叫 `cleaner.py` 的 `analyze_file(file_path)`。向使用者呈現 `FileAnalysis` 結果：

1. 檔案類型、編碼、分隔符
2. 總行數、欄位數
3. 所有欄位的型別及範例值
4. `suggest_column_mappings()` 的建議欄位對應

### 步驟 2：確認欄位對應

展示建議的欄位對應，請使用者確認或手動調整。

欄位對應規則請直接閱讀 `cleaner.py` 原始碼中的 `_HEURISTIC_KEYWORDS`，匹配優先級為：精確 > 規範化精確 > 包含 > 前綴。

**特殊情況**：
- **MoneyWiz 格式**：如果 `is_moneywiz_format()` 返回 True，告知使用者檔案已是 MoneyWiz 格式，建議使用標準匯入流程
- **缺少日期欄位**：停止並解釋——日期為必要欄位
- **缺少金額欄位**：停止並解釋——金額為必要欄位
- **超大檔案（>10,000 行）**：建議先取樣處理

使用者可以：
- 確認自動匹配結果
- 覆寫特定欄位的對應
- 告知特殊格式（如「金額欄位包含 $ 前綴和括號負數」）
- 指定分類分隔符（如 `::` 或 `>`）

### 步驟 3：清理數據

用確認的對應建構 `ColumnHeuristics`，呼叫 `clean_dataframe(df, mapping)`：

```python
from prospere.ingestion.cleaner import ColumnHeuristics, clean_dataframe

mapping = ColumnHeuristics(
    date_column=使用者確認的日期欄位,
    amount_column=使用者確認的金額欄位,
    # ... 其他欄位
)

transactions, balances = clean_dataframe(df, mapping)
```

`clean_dataframe` 返回 `list[Transaction]` 和 `list[AccountBalance]` —— 與 MoneyWiz 引擎相同的型別。清理規則（`_DATE_FORMATS`、`_CATEGORY_DELIMITERS`、`_CURRENCY_SYMBOL_MAP`、`_KNOWN_ISO_CODES`）全部在 `cleaner.py` 原始碼中定義。

**展示清理摘要**：
- 成功解析的日期數
- 已正規化的金額數
- 已標準化的貨幣數
- 產生的主分類/子分類
- 提取的餘額記錄數（如有）
- 產生的唯一 ID 數

### 步驟 4：寫入並驗證

詢問使用者輸出位置：
- **選項 A**：寫入 Prospere 工作區（需提供 `user` 和 `snapshot` 名稱）
- **選項 B**：寫入自訂目錄

使用共享寫入管線：
```python
from prospere.ingestion.writer import write_dataset

success, msg = write_dataset(transactions, balances, xlsx_path, json_path)
```

選 A 時，同時複製到工作區：
```python
from prospere.cli.process import import_preprocessed
success, msg = import_preprocessed(user, snapshot, xlsx_path, json_path)
```

**報告最終結果**：
- 「已清理 X 筆交易和 Y 個餘額。驗證通過。」
- 或顯示驗證失敗的具體原因。

### 步驟 5：建議後續操作

- 執行 `prospere` 啟動 TUI 選單進行模擬
- 使用引導精靈基於此數據建立場景

## 邊緣情況

### 僅有餘額無交易
`clean_dataframe` 返回空 transactions 列表。告知使用者餘額已匯入，但需要交易數據才能計算波動率並執行模擬。

### 編碼錯誤
`analyze_file` 按順序嘗試：utf-8-sig → utf-8 → latin-1 → cp1252。全部失敗則顯示錯誤並建議檢查檔案完整性。

### 同名欄位衝突
如果多個欄位匹配同一個標準欄位，列出衝突並請使用者手動選擇。

### 無標題行
如果檔案沒有標題行（欄位為數字索引），展示前 3 行數據並請使用者提供欄位名稱。

### 負數表示不一致
檢查金額分佈：如果大部分值為負數，可能方向相反，詢問使用者是否需要翻轉符號。
