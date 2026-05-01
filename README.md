# mocharpa

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

现代、可扩展的 RPA（机器人流程自动化）框架 —— 面向对象与函数式风格的 API，支持多后端驱动与声明式流水线编排。

## 特性

- **声明式查找器** — 流式 API 定位 UI 元素并执行操作
- **函数式工具集** — `retry`、`pipe`、`tap`、`maybe`、`wait_until` 等组合子
- **流程控制** — 条件分支、循环、顺序执行、结构化异常处理
- **流水线引擎** — 步骤编排器，支持 YAML/JSON 声明式定义
- **插件体系** — Browser / Database / Excel / HTTP / Word，可按需加载
- **异步支持** — AsyncFind、`async_retry`、`gather` 并发执行
- **多后端驱动** — 抽象驱动层，内置 MockDriver 用于测试，Playwright 用于浏览器

## 安装

```bash
# 基础安装
pip install mocharpa

# 含浏览器自动化
pip install mocharpa[browser]

# 含 Excel / Word
pip install mocharpa[excel,word]

# 全部插件
pip install mocharpa[plugins]
```

## 快速开始

```python
from mocharpa import Find, retry, AutomationContext
from mocharpa.drivers.mock_driver import MockDriver

# 构建上下文
driver = MockDriver()
driver.connect()
ctx = AutomationContext(timeout=10, driver=driver)

# 声明式查找 + 操作
Find().with_context(ctx).name("Submit").type("Button").do(lambda e: e.click())

# 带重试
@retry(max_retries=3, delay=0.5)
def click_save():
    Find().with_context(ctx).name("Save").do(lambda e: e.click())
```

## 核心模块

### 查找器 (`mocharpa.builder`)

流式 API 构建定位条件，链式操作不可变：

```python
Find().name("Login").type("Window").within(5).get()
Find().id("input1").do(lambda e: e.send_keys("hello"))
Find().class_name("submit-btn").get_all()
```

支持的定位策略：`ById`、`ByName`、`ByType`、`ByClass`、`ByRegion`、`ByImage`。

字符串解析：

```python
from mocharpa import LocatorFactory
locator = LocatorFactory.create("name:Login Window > type:Edit")
```

### 函数式工具 (`mocharpa.functional`)

| 函数 | 说明 |
|------|------|
| `retry(max_retries, delay)` | 失败自动重试 |
| `pipe(*funcs)` | 函数组合管道 |
| `tap(fn)` | 副作用注入（不改变值） |
| `maybe(fn)` | 安全执行，返回 `None` 而非抛异常 |
| `wait_until(condition, timeout)` | 轮询等待条件满足 |
| `ignore_err(fn)` | 忽略指定异常 |

```python
process = pipe(
    lambda s: s.strip().upper(),
    tap(lambda s: print(f"→ {s}")),
)
process(" hello ")   # → HELLO
```

### 流程控制 (`mocharpa.flow`)

条件：`exists`、`visible`、`enabled`、`eq`、`contains`、`AND`、`OR`、`NOT` 等。

```python
from mocharpa.flow import if_, while_, sequence, try_catch

# 条件分支
if_(visible("SaveBtn"), lambda: click_save()).else_(lambda: print("Not found"))

# 循环
while_(enabled("NextBtn"), lambda: click_next())

# 顺序执行
sequence(
    lambda: open_dialog(),
    lambda: fill_form(),
    lambda: click_submit(),
)

# 异常处理
try_catch(
    lambda: risky_operation(),
    catch={ElementNotFound: lambda e: log_and_skip(e)},
    finally_=lambda: cleanup(),
)
```

### 流水线 (`mocharpa.pipeline`)

步骤编排引擎，支持 YAML/JSON 定义：

```python
from mocharpa import Pipeline, PipelineContext, Step

ctx = PipelineContext(automation_ctx)
pipeline = Pipeline(
    name="LoginFlow",
    context=ctx,
    steps=[
        Step(name="fill_user", action="send_keys", target="name:Username", value="admin"),
        Step(name="fill_pass", action="send_keys", target="name:Password", value="secret"),
        Step(name="submit",   action="find_click", target="name:LoginButton"),
    ],
)
result = pipeline.run()
```

从 YAML 加载：

```python
pipeline = Pipeline.from_yaml("flows/login.yaml")
```

### 插件系统 (`mocharpa.plugin`)

插件遵循 `initialize(context)` / `cleanup()` 生命周期：

```python
from mocharpa import PluginManager

class LogPlugin:
    name = "logger"
    def initialize(self, ctx):
        ctx.register_hook("pre_action", self._on_action)
    def _on_action(self, **kw):
        print(f"Action: {kw}")
    def cleanup(self):
        pass

mgr = PluginManager(context=ctx)
mgr.register(LogPlugin())
mgr.start_all()
```

内置插件：

| 插件 | 模块 | 依赖 |
|------|------|------|
| PlaywrightDriver | `mocharpa.plugins.browser` | playwright |
| HTTPPlugin | `mocharpa.plugins.http` | requests |
| ExcelPlugin | `mocharpa.plugins.excel` | openpyxl |
| WordPlugin | `mocharpa.plugins.word` | python-docx |
| DatabasePlugin | `mocharpa.plugins.database` | sqlalchemy |

### 异步 API (`mocharpa.async_api`)

```python
from mocharpa.async_api import AsyncFind, async_retry, gather

@async_retry(max_retries=3)
async def click_login():
    await AsyncFind().name("LoginBtn").do(lambda e: e.click())

# 并发
results = await gather(
    click_login(),
    fetch_data(),
)
```

### 驱动适配器 (`mocharpa.core.driver`)

`DriverAdapter` 抽象接口，实现即可接入新后端：

```python
class MyDriver(DriverAdapter):
    def connect(self): ...
    def disconnect(self): ...
    def find_element(self, locator, timeout): ...
    def find_elements(self, locator): ...
```

内置 `MockDriver` 用于单元测试。

## 项目结构

```
mocharpa/
├── core/           # 核心抽象：驱动、元素、定位器、异常、上下文
├── builder/        # 声明式查找构建器
├── functional/     # 函数式工具（retry/pipe/tap/maybe）
├── flow/           # 流程控制（条件/分支/循环/序列）
├── pipeline/       # 流水线引擎 + YAML 加载器
├── plugin/         # 插件协议与管理器
├── plugins/        # 内置插件（browser/database/excel/http/word）
├── drivers/        # 驱动实现（含 MockDriver）
└── async_api/      # 异步封装
```

## 开发

```bash
git clone https://github.com/hezuofu/mocha-rpa.git
cd mocha-rpa
pip install -e ".[dev]"
pytest
```

## 许可

MIT License
