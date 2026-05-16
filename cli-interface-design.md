# OpenCode CLI 界面外观与交互设计整理

本文整理 OpenCode CLI/TUI 的界面设计语言、信息架构和交互模式。内容基于当前代码与官方文档观察，重点描述“它为什么好用、好看，以及这些设计如何被复用”。

## 1. 整体设计定位

OpenCode 的 CLI 并不是传统命令行工具的一次性输出，而是一个完整的终端应用。它的核心体验可以概括为：

- **Prompt-first**：首页和会话页都把输入框作为主入口，用户无需先学习菜单结构。
- **终端原生**：保留终端的文字密度、键盘优先、可复制选择、滚动等习惯。
- **低装饰、高反馈**：不依赖复杂图形，而用边框、颜色、状态行、轻量动画和 hover 背景建立层次。
- **渐进披露**：常用动作直接暴露在输入框和底部提示中，高级能力通过命令面板、slash command、对话框进入。
- **可配置、可扩展**：主题、快捷键、插件 slot、命令、模型、agent 都是 TUI 体验的一部分。

这个界面的气质是“安静但活着”：默认界面很克制，但在模型运行、工具调用、权限确认、选择菜单等状态里会给出明确反馈。

## 2. 页面结构

### 首页

首页是一个居中布局：

- 上方为品牌 logo。
- 主输入框最大宽度约 75 列，避免在宽屏终端里输入行过长。
- 输入框提供随机 placeholder，例如代码修复、项目总结、测试修复等实际任务。
- 底部预留插件 footer slot。
- Toast 作为全局浮层，可在首页显示反馈。

首页没有导航栏和大面积说明文案，直接让用户开始输入。这让 CLI 更像一个工作台，而不是文档入口。

### 会话页

会话页采用“消息流 + 底部输入 + 可选右侧栏”的结构：

- 中央消息流使用 sticky scroll，默认贴近底部，符合聊天/任务执行场景。
- 底部输入框固定存在，除非当前存在权限请求、问题请求或子会话。
- 终端宽度大于 120 列时，右侧栏自动出现。
- 右侧栏宽度固定为 42 列，用于展示 session title、workspace 状态、分享链接和插件内容。
- 窄屏时右侧栏变成右侧 overlay，背景增加半透明遮罩。

这种布局在宽屏上提升信息密度，在窄屏上保持主任务不被挤压。

## 3. 视觉设计语言

### 色彩

OpenCode 使用主题 token，而不是硬编码单个配色。默认主题包含：

- `background`：主背景。
- `backgroundPanel`：消息卡片、侧栏、弹层主体。
- `backgroundElement`：输入框、hover、次级区块。
- `primary`：选中态、主要强调。
- `secondary`、`accent`：agent、文件、问题等辅助强调。
- `success`、`warning`、`error`、`info`：状态反馈。
- diff 专用颜色：新增、删除、上下文、行号和背景分别定义。

默认暗色主题以近黑背景、低饱和灰阶和暖橙 primary 为主，避免“霓虹终端”的疲劳感。它还支持浅色模式，并可随终端主题初始化。

### 边框

界面大量使用左边框表达结构：

- 用户消息左边框使用当前 agent 颜色。
- assistant 工具块、权限块、问题块使用左边框表示当前状态。
- 输入框左边框会根据状态变化：普通模式跟随 agent，shell 模式使用 primary，leader key 激活时使用 border。
- diff、tool block、revert 提示等都使用边框建立独立区块。

这种“单边框”比完整卡片更适合终端：清晰、节省空间，也不会显得笨重。

### 背景层级

常见层级如下：

- 主背景：消息流底色。
- `backgroundPanel`：消息、侧栏、dialog 内容。
- `backgroundElement`：输入框、hover、局部高亮。
- `backgroundMenu`：autocomplete 和工具块 hover。

层级变化很细，不靠大面积高对比色抢注意力。

### 字体与符号

界面以文本符号承担图标角色：

- `$` 表示 shell。
- `→` 表示 read。
- `←` 表示 write/edit/patch。
- `✱` 表示 glob/grep。
- `◇`、`◈` 表示 code search/web search。
- `△` 表示权限警告。
- `▣` 表示 assistant 响应结束元信息。

这些符号足够轻，不会破坏终端的文本质感。

## 4. 输入框设计

输入框是整个 TUI 的核心组件。

### 结构

输入框包含三层信息：

- 多行 textarea，最小 1 行，最大 6 行。
- 下方 metadata 行，展示 agent、model、provider、variant。
- 最底部提示行，展示快捷操作、token/cost、运行状态或中断提示。

输入框背景使用 `backgroundElement`，左边框作为状态指示。这个设计使输入区域稳定可见，但不会像 modal 一样打断上下文。

### 普通模式与 Shell 模式

输入框支持两种模式：

- 普通模式：发送 prompt、slash command、自定义 command。
- Shell 模式：当用户在输入开头输入 `!` 时进入，placeholder 变为命令示例，提交后以 shell command 运行。

Shell 模式可以通过 `esc` 或在空输入处 backspace 退出。底部提示会明确显示 `esc exit shell mode`。

### 附件与粘贴

粘贴交互处理得比较细：

- 图片和 PDF 会以虚拟 token 插入，如 `[Image 1]`、`[PDF 1]`。
- SVG 会作为文本内容处理。
- 长文本或多行粘贴会折叠为 `[Pasted ~N lines]`，提交时再展开真实内容。
- 文件引用、agent 引用和粘贴块都用 extmark 虚拟文本呈现，避免输入框里塞入大量原文。

这让复杂上下文进入 prompt 时仍然保持可读。

## 5. Autocomplete 与命令入口

OpenCode 有两个主要的 inline 入口：

### `@` 引用

输入 `@` 后会打开 autocomplete，内容包括：

- 文件模糊搜索。
- 隐藏 primary agent 之外的 subagent。
- MCP resources。
- 文件行号范围，例如 `@file.ts#10-20`。

文件排序结合 frecency、目录深度和名称排序。列表最多展示 10 项，出现在输入框上方，避免挡住底部输入状态。

### `/` 命令

输入 `/` 会打开 slash command autocomplete，内容包括：

- 内置命令。
- 自定义命令。
- MCP command。
- 命令别名。

命令也可通过命令面板进入。命令面板默认 `ctrl+p`，有搜索框、分类、suggested 区域和快捷键 footer。

这种设计让命令既可以被“记住后快速输入”，也可以被“搜索后发现”。

## 6. 键盘交互

OpenCode 的快捷键设计以 leader key 为核心：

- 默认 leader 为 `ctrl+x`。
- 大部分全局动作使用 `<leader> + key`，减少和终端、shell、textarea 的冲突。
- leader 激活后会暂时 blur 当前 focus，并在 2 秒内等待下一键。
- 常见输入编辑保留 readline/Emacs 风格，如 `ctrl+a`、`ctrl+e`、`ctrl+b`、`ctrl+f`、`ctrl+k`、`ctrl+u`、`ctrl+w`。

常用快捷键包括：

- `ctrl+p`：命令面板。
- `tab` / `shift+tab`：切换 agent。
- `f2` / `shift+f2`：切换最近模型。
- `ctrl+t`：切换模型 variant。
- `escape`：中断当前 session；需要二次按下确认中断运行中的任务。
- `<leader>n`：新会话。
- `<leader>l`：session 列表。
- `<leader>m`：模型列表。
- `<leader>t`：主题列表。
- `<leader>b`：侧栏显示/隐藏。
- `<leader>x`：导出会话。
- `<leader>u` / `<leader>r`：undo/redo。

核心思路是：输入编辑不被全局快捷键打扰，全局功能通过 leader 进入。

## 7. 消息流设计

### 用户消息

用户消息使用 panel 背景和左边框：

- 左边框颜色来自 agent。
- hover 时背景变为 `backgroundElement`。
- 点击用户消息可打开 message dialog，支持把历史内容重新放回 prompt。
- 文件附件用小 badge 展示 mime 类型和文件名。
- pending 队列消息用 `QUEUED` badge 标记。
- 时间戳默认可隐藏，需要时可切换显示。

### Assistant 消息

assistant 内容按 part 渲染：

- 文本用 markdown/code renderer，支持 streaming。
- reasoning 以弱化样式显示，并可整体隐藏。
- 末尾 metadata 展示 mode、model、耗时和 interrupted 状态。
- 如果响应里有 task tool，会提示进入 subagent session。

Assistant 的视觉重点在内容本身，元信息退到末尾，降低干扰。

## 8. 工具调用展示

工具调用分为 inline tool 和 block tool。

### Inline Tool

适合简短状态：

- read、glob、grep、webfetch、websearch、task 等默认以一行展示。
- pending 时显示 spinner 或 `~ Writing command...` 之类的状态。
- completed 后颜色转为 muted。
- denied/error 会用删除线或 error 文本反馈。

### Block Tool

适合大输出或结构化输出：

- bash 有输出时展示 `$ command` 和最多 10 行输出，超出可点击展开。
- write 展示写入内容和诊断。
- edit/apply_patch 展示 diff。
- todowrite 展示 todo 列表。
- generic tool 可按配置展示完整输出，默认更克制。

### Diff

diff 视图根据终端宽度自适应：

- 宽度大于 120 列时优先 split view。
- 窄屏或配置为 `stacked` 时使用 unified view。
- 支持行号、word wrap、added/removed/context 专用颜色。

这让代码修改既能快速扫一眼，也能在终端里认真 review。

## 9. 权限与问题交互

当 session 有权限请求或问题请求时，底部输入框会被对应 prompt 替代，避免用户继续输入导致状态混乱。

### Permission Prompt

权限请求会展示：

- `Permission required` 标题。
- 工具类型、目标文件/命令/搜索 query 等摘要。
- edit 权限会直接展示 diff preview。
- 操作项：`Allow once`、`Allow always`、`Reject`。
- `Allow always` 会进入二次确认，展示将被允许的 pattern。
- reject 在某些场景下允许输入“希望模型怎么改”的说明。

它把安全决策放在具体上下文中，而不是只问一个抽象的 yes/no。

### Question Prompt

模型提问时会出现结构化问答面板：

- 单问题直接选择后提交。
- 多问题使用 tab 页切换，并提供 Confirm 页回顾答案。
- 支持数字键选择、上下键或 `j/k` 导航、左右键或 tab 切换问题。
- 多选项使用 `[x]` 状态。
- 允许自定义答案时提供内嵌 textarea。

这比自由文本追问更稳定，也更适合插件或 agent 发起的结构化澄清。

## 10. Dialog、Toast 与临时反馈

### Dialog

Dialog 是居中 overlay：

- 背景使用半透明黑色遮罩。
- 内容宽度分为 medium 60、large 88、xlarge 116。
- 顶部大约从屏幕 1/4 处开始，使弹层视觉上更靠近用户注意力区域。
- `esc` 或 `ctrl+c` 关闭。
- 点击遮罩关闭，点击内容区阻止冒泡。

DialogSelect 是主要选择器模式：

- 顶部标题 + `esc` 提示。
- 搜索框自动 focus。
- 结果按 category 分组。
- 当前项用 `●` 标记。
- 选中项使用 primary 背景和自动计算的前景色。
- footer 显示快捷键或额外说明。

### Toast

Toast 出现在右上角：

- 最大宽度为 60 列或终端宽度减 6。
- 使用左右边框和状态色区分 `success`、`warning`、`error`、`info`。
- 自动消失。

Toast 适合复制成功、分享链接、错误提示、升级状态等不需要阻塞用户的反馈。

### Startup Loading

插件加载超过 500ms 才显示 loading，避免短暂闪烁。显示后至少保留约 3 秒，文案在 ready 后变为 `Finishing startup...`。这是一个很细的感知性能设计。

## 11. 鼠标交互

虽然这是键盘优先的 TUI，但鼠标不是摆设：

- 默认启用 mouse capture，可通过配置关闭。
- hover 会改变消息、工具块、菜单项背景。
- 点击菜单项可选择。
- 点击用户消息可打开历史消息操作。
- 选择文本后可复制，部分模式下右键或 mouse up 会触发 copy。
- `ctrl+y` 绑定为 copy selection。

鼠标交互被设计成增强能力，不替代键盘主路径。

## 12. 可定制能力

### 主题

内置主题很多，包括 `opencode`、`tokyonight`、`github`、`dracula`、`nord`、`catppuccin`、`gruvbox` 等。主题可来自：

- 默认主题。
- 插件主题。
- 用户自定义主题文件。
- 系统生成主题。

主题支持 dark/light 两套值和 token 引用。

### 快捷键

快捷键通过 `tui.json` 配置，可把任意 action 改为其他组合，也可设为 `none` 禁用。Windows 下会对 `terminal_suspend` 和 `input_undo` 做平台适配。

### TUI 配置

TUI 支持：

- `scroll_speed`
- `scroll_acceleration`
- `diff_style`
- `mouse`
- `theme`
- `keybinds`
- `plugin`
- `plugin_enabled`

这些选项覆盖了视觉、输入、滚动、diff 和插件扩展。

## 13. 插件化设计

TUI 预留了大量 slot：

- `app`
- `home_logo`
- `home_prompt`
- `home_prompt_right`
- `home_bottom`
- `home_footer`
- `session_prompt`
- `session_prompt_right`
- `sidebar_title`
- `sidebar_content`
- `sidebar_footer`

插件可以注册命令、路由、主题和 UI slot。这个设计让 TUI 核心保持稳定，同时允许用户或生态扩展界面。

## 14. 可复用设计原则

如果要借鉴 OpenCode 的 CLI 设计，可以提炼为以下原则：

1. **把输入入口做成界面中心**  
   用户打开工具后应立即知道可以做什么，不需要先读说明。

2. **用左边框而不是厚重卡片表达结构**  
   终端空间宝贵，单边框足以表达层级和状态。

3. **让颜色承担语义，而不是装饰**  
   agent、权限、错误、diff、选中态各自有稳定颜色含义。

4. **命令既可输入，也可搜索**  
   `/command` 服务熟练用户，命令面板服务发现和记忆。

5. **长内容用虚拟 token 收起**  
   文件、图片、PDF、长粘贴不直接占满输入框。

6. **阻塞决策使用底部面板，不轻易打断上下文**  
   权限和问题替代输入框，保持用户仍在当前 session 里。

7. **工具调用先摘要，必要时展开**  
   默认保持消息流可扫读，大输出和 diff 再进入 block view。

8. **宽屏增加信息密度，窄屏保持主路径**  
   右侧栏只在宽屏常驻，窄屏使用 overlay。

9. **快捷键使用 leader 降低冲突**  
   输入框仍保留用户熟悉的编辑习惯。

10. **反馈要及时但不吵**  
    Spinner、toast、hover、status line 和 terminal title 都是轻量反馈。

## 15. 主要源码依据

- TUI 入口、renderer、全局命令和路由：[packages/opencode/src/cli/cmd/tui/app.tsx](../packages/opencode/src/cli/cmd/tui/app.tsx)
- 首页布局：[packages/opencode/src/cli/cmd/tui/routes/home.tsx](../packages/opencode/src/cli/cmd/tui/routes/home.tsx)
- 会话页、消息流、工具展示：[packages/opencode/src/cli/cmd/tui/routes/session/index.tsx](../packages/opencode/src/cli/cmd/tui/routes/session/index.tsx)
- 输入框：[packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx](../packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx)
- Autocomplete：[packages/opencode/src/cli/cmd/tui/component/prompt/autocomplete.tsx](../packages/opencode/src/cli/cmd/tui/component/prompt/autocomplete.tsx)
- 命令面板：[packages/opencode/src/cli/cmd/tui/component/dialog-command.tsx](../packages/opencode/src/cli/cmd/tui/component/dialog-command.tsx)
- Dialog 和选择器：[packages/opencode/src/cli/cmd/tui/ui/dialog.tsx](../packages/opencode/src/cli/cmd/tui/ui/dialog.tsx)、[packages/opencode/src/cli/cmd/tui/ui/dialog-select.tsx](../packages/opencode/src/cli/cmd/tui/ui/dialog-select.tsx)
- Toast：[packages/opencode/src/cli/cmd/tui/ui/toast.tsx](../packages/opencode/src/cli/cmd/tui/ui/toast.tsx)
- 主题系统：[packages/opencode/src/cli/cmd/tui/context/theme.tsx](../packages/opencode/src/cli/cmd/tui/context/theme.tsx)
- 默认主题：[packages/opencode/src/cli/cmd/tui/context/theme/opencode.json](../packages/opencode/src/cli/cmd/tui/context/theme/opencode.json)
- 快捷键系统：[packages/opencode/src/cli/cmd/tui/context/keybind.tsx](../packages/opencode/src/cli/cmd/tui/context/keybind.tsx)
- TUI 配置 schema：[packages/opencode/src/cli/cmd/tui/config/tui-schema.ts](../packages/opencode/src/cli/cmd/tui/config/tui-schema.ts)
- 官方 TUI 文档：[packages/web/src/content/docs/tui.mdx](../packages/web/src/content/docs/tui.mdx)
- 官方 keybind 文档：[packages/web/src/content/docs/keybinds.mdx](../packages/web/src/content/docs/keybinds.mdx)
