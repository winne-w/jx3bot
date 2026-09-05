# JJC 数据中心统一入口实现报告

## 本次范围

完成执行计划 Task 1–3：

- 新增 `public/index.html`，从完整排名统计页复制并保留原有 DOM、脚本、接口路径和统计渲染逻辑。
- 在 `public/index.html`、`public/jjc-ranking-stats.html`、`public/jjc-synced-matches.html`、`public/jjc-matchups.html` 增加统一品牌头部和三项相对链接导航。
- 为各页当前导航项增加 `aria-current="page"` 和激活态样式。
- 增加窄屏下的纵向站点头部和可水平滚动导航，避免导航压缩主要内容。

## 验证

执行命令：

```bash
python - <<'PY'
from html.parser import HTMLParser
from pathlib import Path

class ContractParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.ids=set()
    def handle_starttag(self, tag, attrs):
        d=dict(attrs)
        if tag == 'a': self.links.append((d.get('href'), d.get('aria-current')))
        if d.get('id'): self.ids.add(d['id'])

files = ['index.html','jjc-ranking-stats.html','jjc-synced-matches.html','jjc-matchups.html']
nav_links = ['index.html','jjc-synced-matches.html','jjc-matchups.html']
for name in files:
    source = (Path('public') / name).read_text(encoding='utf-8')
    parser = ContractParser(); parser.feed(source)
    assert 'JJC 数据中心' in source
    for link in nav_links: assert f'href="{link}"' in source
    assert 'class="site-header"' in source and 'class="site-nav"' in source
    print(name, 'ok', sorted(parser.ids & {'grid','search-form','submit-search'}))
assert 'JJC 数据中心 · 心法排名统计' in (Path('public') / 'index.html').read_text(encoding='utf-8')
assert (Path('public') / 'index.html').read_text(encoding='utf-8').count('fetch(') >= 1
print('static navigation contract: PASS')
PY
git diff --check
```

输出：

```text
index.html ok ['grid']
jjc-ranking-stats.html ok ['grid']
jjc-synced-matches.html ok ['search-form']
jjc-matchups.html ok ['submit-search']
static navigation contract: PASS
```

`git diff --check` 未发现空白错误；Git 对原页面 CRLF/LF 转换给出提示，但不影响 HTML 解析。

## 风险与疑虑

- 本次未启动浏览器或在线统计接口，无法在离线环境证明外部 API 数据加载和移动端实际渲染；首页复制自排名页，因此脚本和接口路径与排名页一致。
- OpenSpec CLI 当前报告 `tasks.md` 缺失而无法进入标准 apply 状态；本次依据同目录的 `02-execution-plan.md` 完成明确指定的 Task 1–3。
