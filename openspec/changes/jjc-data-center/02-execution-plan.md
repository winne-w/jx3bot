# JJC 数据中心统一入口执行计划

## Purpose / Big Picture

为三个已有 JJC 静态页面增加统一站点入口和导航，使用户访问 `public/index.html` 后默认进入心法排名统计，并可在三个页面之间顺畅切换。

## Progress
- [ ] 新增统一首页入口
- [ ] 为三个页面接入统一站点头部和导航
- [ ] 完成响应式布局与当前项高亮
- [ ] 完成静态契约测试与浏览器冒烟

## Surprises & Discoveries

当前三个页面均为大型独立 HTML 文档，排名页包含完整数据渲染脚本；实现应避免复制业务脚本，优先让 `index.html` 复用排名页内容或以兼容跳转方式承载首页。

## Decision Log

采用普通相对链接，不引入前端路由器或框架。保留三个原始页面 URL，统一导航只负责页面跳转和当前项识别。

## Outcomes & Retrospective

实现完成后补充测试结果、浏览器验证结果和未覆盖风险。

## Context and Orientation

相关文件为 `public/jjc-ranking-stats.html`、`public/jjc-synced-matches.html`、`public/jjc-matchups.html`。三页已有各自的页面头部和样式，修改范围集中在文档入口、头部导航和响应式样式，不触碰 API 调用与业务渲染函数。

## Plan of Work

先确定排名页入口复用策略并新增 `public/index.html`，再在三个页面加入同一套站点导航标记和样式。随后补静态契约检查，验证链接、标题、`aria-current` 和移动端样式；最后用浏览器检查三个页面和原有核心交互。

## Concrete Steps

### Task 1: 新增统一首页入口

**Files:**
- Create: `public/index.html`

- [ ] 从排名统计页复制现有完整文档到 `index.html`，保留脚本、样式、接口路径和 DOM id 不变。
- [ ] 将首页文档标题和站点标识统一为“JJC 数据中心 · 心法排名统计”。
- [ ] 确保首页上的导航链接指向 `index.html`、`jjc-synced-matches.html`、`jjc-matchups.html`。
- [ ] 用浏览器直接访问 `index.html`，确认统计接口仍能加载。

### Task 2: 接入统一站点头部与导航

**Files:**
- Modify: `public/index.html`
- Modify: `public/jjc-ranking-stats.html`
- Modify: `public/jjc-synced-matches.html`
- Modify: `public/jjc-matchups.html`

- [ ] 在各页面现有主内容上方加入统一站点头部，包含站点名称、页面说明和三项导航。
- [ ] 为当前页面导航项加入 `aria-current="page"` 和激活样式。
- [ ] 保留现有页面标题、查询控件、弹窗容器和脚本所需 DOM 结构。
- [ ] 统一品牌链接返回 `index.html`，并为直接访问 `jjc-ranking-stats.html` 的用户提供兼容入口。

### Task 3: 补充响应式壳层样式

**Files:**
- Modify: `public/index.html`
- Modify: `public/jjc-ranking-stats.html`
- Modify: `public/jjc-synced-matches.html`
- Modify: `public/jjc-matchups.html`

- [ ] 使用各页现有 CSS 变量和颜色体系定义站点头部、导航间距、边框、圆角和激活态。
- [ ] 在窄屏下让导航水平滚动或自然换行，避免压缩页面主要内容。
- [ ] 确保导航与页面原有 topbar、page-header 不发生重复堆叠或横向溢出。

### Task 4: 添加静态契约验证

**Files:**
- Create or modify: `tests/test_jjc_data_center_navigation.py`

- [ ] 检查四个 HTML 文件均存在统一站点名称和三个目标链接。
- [ ] 检查三个页面分别声明正确的当前导航项或等价激活标记。
- [ ] 检查原有关键容器仍存在：排名页 `grid`、对局查询页 `search-form`、对阵页 `submit-search`。
- [ ] 运行针对该测试文件的测试并修复失败。

### Task 5: 浏览器回归与验收记录

**Files:**
- Modify: `openspec/changes/jjc-data-center/03-test-plan.md`
- Create: `openspec/changes/jjc-data-center/04-review.md`
- Create: `openspec/changes/jjc-data-center/05-acceptance.md`

- [ ] 在桌面视口访问 `index.html`，验证排名数据加载和导航跳转。
- [ ] 分别访问对局查询、心法对阵，验证导航当前项、页面加载、查询控件和详情弹窗。
- [ ] 在移动视口检查导航可操作、无横向溢出、主要内容仍可读。
- [ ] 记录测试命令、通过结果、外部接口依赖和剩余风险。

## Validation and Acceptance

自动化验证至少运行：

```bash
python -m unittest tests.test_jjc_data_center_navigation
```

浏览器验收覆盖 `/index.html`、`/jjc-ranking-stats.html`、`/jjc-synced-matches.html`、`/jjc-matchups.html` 四个入口，确认页面导航、数据接口、查询控件和移动端布局均正常。实现前不修改后端 API、数据库和业务统计逻辑。

## 2026-10-20 宽度与排名入口一致性修复

延续用户确认的 1920×1080 四列排名布局：将最大 1920px 内容宽度统一放在 `public/jjc-site.css`，移除四个入口各自的 `.page` 宽度定义与排名页专用覆盖，保留桌面每侧 24px、手机每侧 14px 边距。同步 `index.html` 与 `jjc-ranking-stats.html` 的完整内容，并在现有导航测试中增加两入口一致性契约，避免后续布局或脚本遗漏同步。调整现有壳层契约测试，使其读取共享样式中的页面规则。

验证先确认入口一致性测试能复现失败，再运行导航、排名、对阵相关测试；使用 Playwright 对四入口在桌面、平板、手机和超宽视口逐一比较页面宽度与左右边距，并验证 1920×1080 排名四列、排名入口渲染一致及导航切换。验证使用本地资源与模拟接口，不依赖线上 API。回滚范围为本次共享样式、入口同步与契约测试改动。

2026-10-20 提交前复验：将暂存区页面与测试导出至 `/tmp/jjc-layout-staged/`，导航、排名、对阵 30 项测试通过。Playwright 对 4 个入口 × 6 个视口（1920、2560、1366、735、390、375px）共 24 组检查通过，验证最大宽度、边距、无横向溢出、1920px 四列、两排名入口一致、导航切换、橙武开关和明细展开；未发现页面运行错误。所有接口使用模拟数据。
