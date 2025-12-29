# Repository Guidelines

## 项目结构与模块分工
- `bot.py` 负责启动 NoneBot、注册插件并连接 NapCat 的反向 WebSocket。
- 核心命令集中在 `src/plugins/jx3bot.py`，`wanbaolou/`、`config_manager.py` 与 `status_monitor.py` 提供物价别名、调度与健康检查能力。
- 通用工具位于 `src/utils/`，可复用的模板与素材保存在 `templates/`、`mpimg/`、`data/`；对外提供的 PHP/HTML 页面统一放在 `public/`。
- 根目录下的 `test_*.py`、`example_*.py`、`debug_kungfu_by_role.py` 用于手动排查；`Dockerfile`、`docker-compose.yml`、`start.sh` 需随部署流程同步更新，并在 README 系列文档中同步说明。
- `README.md`、`README-Docker.md` 及 PlantUML 图 (`*.puml`) 提供架构参考，流程更新时请同时修订这些文档。
- `requirements.txt` 与 `pyproject.toml` 记录依赖与元数据，调整版本时务必双向更新并通知运维。

## 构建、测试与开发命令
- `python -m venv .venv && source .venv/bin/activate` —— 创建 Python 3.9+ 虚拟环境。
- `pip install -r requirements.txt` —— 安装依赖，如遇编码报错请转存为 UTF-8。
- `python bot.py` —— 本地运行机器人前需配置好 `config.py`、`groups.json` 以及反向 WebSocket。
- `bash start.sh` —— 模拟容器入口并启用 `mpimg/` 静态资源，适用于容器外的快速演练。
- `docker compose up --build` —— 重新构建并启动 docker-compose 定义的完整环境。
- `python test_jx3bot_ranking.py` / `python test_tuilan_request.py` —— 手动验证竞技场与推栏接口。
- `python example_tuilan_request.py` —— 处理复杂参数时可借助示例脚本观察请求体与响应。

## 代码风格与命名约定
- 统一使用四空格缩进与 `snake_case` 标识符，保持注释简洁。
- 插件需返回结构化数据，通过 `templates/` 下的 Jinja 模板输出最终消息或图片；涉及截图时注意分辨率与字体兼容。
- 推荐统一使用 `loguru` 与 `nonebot.logger` 进行输出，避免混用标准库 logging 导致格式漂移。
- 配置常量集中放在 `config.py` 或模块级字典，避免在业务逻辑中硬编码服务器、令牌或 CDN。
- 日志务必包含命令、服务器、接口等上下文，方便快速定位问题，必要时补充请求 ID。

## 测试指引
- 现有测试依赖在线服务，修改相关模块后请运行对应 `test_*.py` 并在调试时记录 `log.txt`。
- 新增测试脚本遵循 `test_<feature>.py` 命名，在 `if __name__ == "__main__":` 中封装入口，同时说明放入 `data/` 的模拟数据。
- 引入复杂解析、缓存或并发逻辑前，优先补充 pytest 或 CI 自动化，降低回归风险；如依赖外部服务，请在说明中给出 mock 策略。
- 推送前建议运行 `pytest` 或 `nb plugin list --json` 等快速检查命令，确认插件加载与关键函数正常。

## 提交与合并请求规范
- 延续仓库现有格式（`feat: …`、`fix: …`），标题控制在 72 字符内，可使用中英双语简述。
- 自动生成或手写的 commit 信息需使用中文描述，必要时可附带少量英文专有名词。
- PR 描述需阐明问题、方案、关联的 Issue/流程图，并列出执行过的手工测试。
- 若改动 `mpimg/` 素材或模板渲染，请附截图，并明确写出部署或调度影响；牵涉接口兼容时提供回滚建议。
- Review 时可附上 `git diff --stat` 或关键命令输出，帮助审核者快速了解影响范围。

## 安全与配置提示
- 秘钥放置在环境变量或平台密钥管理中，切勿写入 `config.py`；本地调试可借助 `.env` 文件，提交前务必忽略。
- 调整 `config.py`、`groups.json`、别名数据或 `waiguan.json` 时要同步通知运维并说明是否需要重启，确保别名缓存按计划刷新。
- 新增依赖需在 `requirements.txt`（可结合 `pip-tools`）中锁定，确保镜像可重现，同时确认 `start.sh` 的自检步骤仍然适用。
- 更新 `docker-compose.yml` 或启动脚本后，在 PR 中列出需调整的环境变量、端口映射与 volume，便于同步到 CI/CD pipeline。
