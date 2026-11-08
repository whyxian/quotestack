# 录制样本（fixtures）

上游改了响应结构，单测仍然绿——因为单测读的是这一堆**历史快照**。
所以这里的内容必须来自真实请求，不能是手写的"大概长这样"。

---

## 目录约定

```
tests/fixtures/
├── eastmoney/
│   ├── quote_600519.json          正常样本
│   └── kline_600519.json
├── tiantian/
│   ├── nav_166002.js
│   ├── holdings_166002.html
│   └── fund_list.js
├── binance/
│   └── exchange_info.json
└── bad/
    ├── eastmoney_quote_no_data.json     坏的：少 envelope
    └── tiantian_holdings_no_quarters.html
```

**命名**：`<能力>_<代码或说明>.<原始扩展名>`，保留原始字节。

**坏样本放 `bad/`**，文件名写出它坏在哪。每个适配器至少要有一个坏样本，
用来断言 `SchemaChangedError`——没有它，解析器对结构变更毫无防御。

---

## 怎么录

```bash
curl -s 'https://push2.eastmoney.com/api/qt/ulist.np/get?secids=1.600519&fields=f1,f2,f3,f4,f12,f13,f14,f124' \
  > tests/fixtures/eastmoney/quote_600519.json
```

**必须原样保存**，不要格式化、不要裁剪字段。字段少了就测不出"解析器能不能处理缺字段"。

---

## 怎么用

```python
from tests.fixtures import load


@respx.mock
async def test_quote_parses():
    respx.get(...).mock(
        return_value=httpx.Response(200, content=load("eastmoney/quote_600519.json"))
    )
```

`load()` 返回 `bytes`，因为腾讯和东财的部分接口是 GBK，按字符串读会坏。

---

## 什么时候重录

每日探测（`.github/workflows/live-probe.yml`）失败时：

1. 先确认真的是上游变了，而不是网络抖动
2. 重新录制受影响的样本
3. 跑测试，看解析器要不要改
4. 改完在提交信息里写清"上游改了什么"

**不要为了让测试通过而改坏样本**——那等于把警报器拆了。
