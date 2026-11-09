# JJC 数据中心测试计划

## 自动化验证

运行 `python -m unittest tests.test_jjc_data_center_navigation`，使用 Python `unittest` 和 `HTMLParser` 检查四个 HTML 入口的站点名称、三个导航链接、唯一 `aria-current="page"` 当前项，以及排名 `grid`、对局查询 `search-form`、对阵 `submit-search` 等原有 DOM。测试同时检查对局查询页窄屏媒体规则包含纵向站点头部布局。

## 浏览器冒烟

计划在桌面视口访问 `index.html`、`jjc-ranking-stats.html`、`jjc-synced-matches.html`、`jjc-matchups.html`，检查导航跳转和关键查询控件；在约 375px 宽移动视口检查站点头部纵向排列、导航可访问且页面无横向溢出。

本次环境未提供可用的浏览器运行时，因此未执行真实浏览器冒烟，也无法离线验证外部统计接口、查询弹窗、分页和导出交互。静态契约测试覆盖了页面结构和响应式 CSS 契约。

## 风险

排名首页与兼容入口仍是独立 HTML 副本，后续修改排名业务脚本时存在同步漂移风险；外部 API 不可用时需按页面现有错误状态回归。移动端无溢出结论需在浏览器环境补测。
