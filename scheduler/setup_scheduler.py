"""
Windows 定时任务安装/卸载脚本

用法：
    python scheduler/setup_scheduler.py install    # 安装定时任务
    python scheduler/setup_scheduler.py uninstall  # 卸载定时任务
    python scheduler/setup_scheduler.py status     # 查看任务状态
"""

import sys
import subprocess
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
TASKS_XML = os.path.join(SCRIPT_DIR, "alpha-pick-tasks.xml")

# 定时任务名称
TASK_NAMES = [
    "alpha_pick_premarket",
    "alpha_pick_alerts", 
    "alpha_pick_review",
]


def run_cmd(cmd, check=True):
    """运行命令"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        print(f"❌ 命令失败: {cmd}")
        print(f"   错误: {result.stderr}")
        return False
    return True


def install():
    """安装定时任务"""
    print("📦 安装 alpha-pick 定时任务...")
    print(f"   项目目录: {PROJECT_DIR}")
    print(f"   任务XML: {TASKS_XML}")
    print()

    if not os.path.exists(TASKS_XML):
        print(f"❌ 任务文件不存在: {TASKS_XML}")
        return False

    # 检查管理员权限
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("⚠️  需要管理员权限，请以管理员身份运行")
        print("   或手动在任务计划程序中导入 XML 文件")
        print()
        print("   任务配置：")
        print("   1. 盘前选股: 每周一至周五 09:00")
        print("   2. 盘中预警: 每5分钟 09:30-15:00")
        print("   3. 盘后复盘: 每周一至周五 15:30")
        return False

    # 卸载已有任务
    print("   卸载已有任务...")
    for name in TASK_NAMES:
        run_cmd(f'schtasks /Delete /TN "{name}" /F', check=False)

    # 导入任务
    print("   导入任务配置...")
    if not run_cmd(f'schtasks /Create /F /XML "{TASKS_XML}"'):
        print("❌ 导入失败")
        return False

    # 验证
    print("\n   验证安装...")
    all_ok = True
    for name in TASK_NAMES:
        result = subprocess.run(
            f'schtasks /Query /TN "{name}"', 
            shell=True, capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode == 0:
            print(f"   ✅ {name} 已安装")
        else:
            print(f"   ⚠️  {name} 未找到")
            all_ok = False

    if all_ok:
        print("\n✅ 定时任务安装成功！")
        print("\n任务列表：")
        print("  🔔 alpha_pick_premarket  - 盘前选股 (09:00)")
        print("  🔔 alpha_pick_alerts     - 盘中预警 (09:30-15:00, 每5分钟)")
        print("  🔔 alpha_pick_review     - 盘后复盘 (15:30)")
        print("\n💡 提示：交易日历未配置，周末也会运行（不会执行交易，仅推送）")
        print("   如需跳过周末，可手动在任务计划程序中编辑触发器")
    else:
        print("\n⚠️  部分任务未安装，请检查权限")

    return all_ok


def uninstall():
    """卸载定时任务"""
    print("🗑️  卸载 alpha-pick 定时任务...")
    
    for name in TASK_NAMES:
        result = subprocess.run(
            f'schtasks /Delete /TN "{name}" /F', 
            shell=True, capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode == 0:
            print(f"   ✅ {name} 已卸载")
        else:
            print(f"   ⚠️  {name} 不存在或卸载失败")

    print("\n✅ 卸载完成")


def status():
    """查看任务状态"""
    print("=" * 60)
    print("📋 alpha-pick 定时任务状态")
    print("=" * 60)
    
    for name in TASK_NAMES:
        result = subprocess.run(
            f'schtasks /Query /TN "{name}" /V /FO LIST',
            shell=True, capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            status_line = ""
            for line in lines:
                if "状态" in line or "Status" in line:
                    status_line = line.strip()
                    break
            print(f"\n   📌 {name}")
            print(f"      {status_line}")
        else:
            print(f"\n   ❌ {name} - 未安装")


def main():
    if len(sys.argv) < 2:
        print("用法: python setup_scheduler.py <install|uninstall|status>")
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "install":
        success = install()
        sys.exit(0 if success else 1)
    elif action == "uninstall":
        uninstall()
        sys.exit(0)
    elif action == "status":
        status()
        sys.exit(0)
    else:
        print(f"未知操作: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
