# EcompVision Inspector（发布目录说明）

通用的产品尺寸外观检测软件平台：4/6面外观检测机、非标自动化尺寸外观检测机。

本目录（`output/`）为程序发布目录，`EcompVision Inspector.exe` 为单文件可执行程序，
双击即可运行，无需安装。程序版本 / 版权信息见 exe「属性 → 详细信息」。

- 软件名称：EcompVision Inspector
- 运行窗口：按 1920×1080 显示器设计，默认最大化显示，最小尺寸 1366×768
- 版权信息：By：ZY.SHAW

## 目录内容

| 文件 / 目录 | 说明 |
|---|---|
| `EcompVision Inspector.exe` | 主程序（单文件，无需安装，双击运行） |
| `assets/` | 运行期所需资源（相机样张等），**必须与 exe 同级目录** |
| `output/` | 运行期由程序内生成/维护的调试输出、结果图片等（首次运行自动创建） |
| `app_icon.ico` | 程序窗口 / 任务栏图标 |
| `users.json` | 用户账号与权限配置（首次运行自动生成默认账号） |
| `device_config.json` | 设备参数配置 |
| `alarm_config.json` | 报警配置 |
| `shift_defaults.json` | 时段默认配置 |
| `debug_view_config.json` | 调试界面偏好（筛选状态等），程序自动维护 |
| `detect_defaults.json` | 检测项默认设置（「设置为默认」保存处） |
| `*_save_config.json` / `copilot_config.json` | 日志 / 图像保存 / 视觉助手配置 |
| `theme.json` | 主题配置 |
| `playback_diag.log` / `startup_diag.log` | 运行期诊断日志，可随时删除 |

## 运行说明

1. 直接双击 `EcompVision Inspector.exe` 运行；请勿把 exe 与 `assets/`、`app_icon.ico` 分开存放。
2. 登录账号（见 `users.json`）：
   - `admin` / `admin123` —— 超级管理员（全部权限）
   - `devadmin01`、`eng01`、`tech01`、`operator01` / `123456` —— 设备管理员 / 工程师 / 技术员 / 操作员（权限依次收窄）
3. 各配置文件均可在程序界面内修改；不慎删改后程序会按默认值重新生成。

## 主要功能

- **生产运行**：设备启动 / 停止、实时生产统计、报警与日志。
- **相机调试**：图像效果调节、产品定位及区域分割、计算元素精确查找（目标查找参数设置支持「分布」查看与**自动调参**）。
- **检测项列表**：规格上下限维护，支持**规格自动调整**（基于分布样本推荐上下限并重新判定结果）；「出料设置」对应「收料位置」列，可对全部检测项逐项设置收料位置。
- **检测流程设计**：左侧算子工具箱（分类可展开），双击插入算子；画布左下角有半透明操作提示（滚轮缩放、左键拖拽连线 / 平移、右键拖拽移动算子）；选中画布算子后，右侧竖栏「算法参数」展开分页面板（基础设置 + 算法参数）。
- 其余：用户权限管理、产品方案管理、良率统计（含饼图与报表导出）、运行日志、设备状态、成像状态、AI 助手、亮/暗色主题切换等。

## 重建 / 打包（开发者）

- 打包：仓库根目录 `python build_b.py`（PyInstaller，配置见同目录 `EcompVision Inspector.spec`）。
- 演示程序包：`python make_demo_zip.py`。
- 本 README 由仓库根 `README.release.md` 在每次构建时同步生成，请勿直接编辑 `output/README.md`。
- 开发环境：Python 3.13 / PyQt6 6.11 / PyInstaller 6.22。
