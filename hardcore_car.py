#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬核推理车队招募助手 - Hardcore Car Manager v1.2
面向资深车头的极简命令行工具（长期多群发车工作台）
"""

import sys
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

from models import Car, Player, Registration, CarTemplate, Group
from storage import (
    load_db, save_db,
    add_car, get_car, list_cars, update_car_status, delete_car,
    add_player, get_player, find_player_by_nickname, update_player,
    add_registration, remove_registration, get_registrations_by_car,
    get_player_registrations,
    update_registration_status,
    add_template, get_template, list_templates, delete_template,
    add_player_tag, remove_player_tag, list_players_by_tag, PRESET_TAGS,
    add_group, get_group, get_default_group, list_groups, delete_group,
)
from matcher import triage_registrations, MatchResult


BANNER = r"""
╔══════════════════════════════════════════╗
║  🔥 硬核推理车队招募助手 v1.3 🔥         ║
║  Hardcore Detective Car Manager         ║
║  多群长期发车 · 工作台版                ║
╚══════════════════════════════════════════╝
"""

HELP = """
命令列表：
  new [-t 模板名] [-g 群]      开新车（可用 -t 模板，-g 指定群）
  copy <车ID> [-g 群]          从已有车复制出新车（可改时间/店铺/群）
  add <车ID> [-g 来源群]       为指定车添加报名（含来源群记录）
  view <车ID> [选项]           查看报名分析（含来源群、跨群重复提示）
       筛选选项： --pending / --eligible / --approved / --bench / --conflict
       排序选项： --sort score|experience|time|created
       批量操作: a1-3 approve / b4,5 bench / k6 kick（用屏幕上的序号）
  draft <车ID> [群名...]       生成多群报名文案（支持一次生成多群不同版本）
  export <车ID> [格式] [范围]
       格式: all(默认) / notice(群公告) / check(审核表) / shop(店铺表)
       范围: approved(仅已确认) / bench(已确认+替补)
  list                   列出所有车辆
  status <车ID> <open|full|done|cancel>
  approve/bench/kick <车ID> <序号...>
  info <车ID>            车辆详情（含归属群、标签）
  del <车ID>             删除车辆
  players [标签]         玩家资料库（含常用来源群）
  tag <玩家昵称> +/-<标签>  给玩家加/减长期标签
  group save <群名> [简称]   保存群配置（可设默认、文案偏好）
  group list              列出所有群
  group del <群名/ID/简称>  删除群配置
  template save/list/del   模板管理
  help / ?               显示此帮助
  quit / exit / q        退出

使用示例：
  > group save 硬核老玩家群 A群 --default
  > new -t "周末硬核标配" -g A群
  > copy ab12cd34 -g B群
  > add ef56gh78 -g A群
  > view ef56gh78 --pending --sort experience
  > draft ef56gh78 A群 B群 C群        # 同时生成三群不同版本
  > export ef56gh78 notice approved
"""


COLORS = {
    "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
    "blue": "\033[94m", "purple": "\033[95m", "cyan": "\033[96m",
    "bold": "\033[1m", "reset": "\033[0m", "dim": "\033[2m",
}


def color(text: str, *tags: str) -> str:
    if not sys.stdout.isatty():
        return text
    prefix = "".join(COLORS.get(t, "") for t in tags)
    return prefix + text + COLORS["reset"]


def prompt(msg: str, default=None, required=True, validator=None):
    while True:
        suffix = f" [默认:{default}]" if default is not None else ""
        val = input(f"  {msg}{suffix}: ").strip()
        if not val and default is not None:
            val = str(default)
        if not val and not required:
            return val
        if not val and required:
            print(color("  ! 必填项，不能为空", "red"))
            continue
        if validator:
            result = validator(val)
            if isinstance(result, tuple):
                ok, err = result
            else:
                ok, err = result, ""
            if not ok:
                print(color(f"  ! {err}", "red"))
                continue
        return val


def prompt_bool(msg: str, default: bool = False) -> bool:
    d = "Y" if default else "N"
    while True:
        val = input(f"  {msg} (y/N) [默认:{d}]: ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes", "1", "是", "对"):
            return True
        if val in ("n", "no", "0", "否", "不"):
            return False
        print(color("  ! 请输入 y 或 n", "red"))


# ===== 验证器：区分"必须正整数"和"允许0的非负整数" =====

def v_int_pos(text):
    """必须 > 0 的正整数（用于人数、时长等）"""
    try:
        n = int(text)
        if n > 0:
            return True, ""
        return False, "必须是正整数（不能为0或负数）"
    except ValueError:
        return False, "请输入有效整数"


def v_int_nonneg(text):
    """允许为 0 的非负整数（用于经验门槛、经验数量等）"""
    try:
        n = int(text)
        if n >= 0:
            return True, ""
        return False, "必须是非负整数（0 或正整数）"
    except ValueError:
        return False, "请输入有效整数（0 表示无门槛/萌新）"


def v_float_pos(text):
    try:
        n = float(text)
        if n > 0:
            return True, ""
        return False, "必须是正数"
    except ValueError:
        return False, "请输入有效数字"


def v_datetime(text):
    formats = [
        "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M", "%m-%d %H:%M", "%m/%d %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if "%Y" not in fmt:
                dt = dt.replace(year=datetime.now().year)
                if dt < datetime.now():
                    dt = dt.replace(year=datetime.now().year + 1)
            return True, dt
        except ValueError:
            continue
    return False, "格式应为 YYYY-MM-DD HH:MM 或 MM-DD HH:MM"


def v_gender(text):
    if text in ("男", "女", "M", "F", "m", "f"):
        return True, ""
    return False, "请输入 男 / 女"


def exp_display(n: int) -> str:
    """经验数量的友好显示：0=萌新，其它=N硬核"""
    if n <= 0:
        return "萌新"
    return f"{n}硬核"


def tags_display(player: Player, max_len: int = 40) -> str:
    """标签友好显示，风险类红色、正面绿色、中性灰色"""
    if not player.tags:
        return ""
    parts = []
    for t in player.tags:
        if any(k in t for k in ("跳车", "天眼", "鸽子")):
            parts.append(color(f"⚠{t}", "red"))
        elif any(k in t for k in ("迟到", "挂机", "杠精", "剧透")):
            parts.append(color(f"△{t}", "yellow"))
        elif any(k in t for k in ("靠谱", "老炮", "大神", "推土机", "宝藏", "输出", "氛围")):
            parts.append(color(f"✓{t}", "green"))
        else:
            parts.append(color(f"·{t}", "dim"))
    s = " ".join(parts)
    return s[:max_len]


def parse_index_ranges(text: str) -> List[int]:
    """解析 '1,3,5-8,10' 这样的序号范围，返回去重排序的整数列表"""
    result = set()
    if not text:
        return []
    for part in re.split(r"[,，\s]+", text.strip()):
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-~—]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            lo, hi = min(a, b), max(a, b)
            for i in range(lo, hi + 1):
                result.add(i)
        else:
            try:
                result.add(int(part))
            except ValueError:
                continue
    return sorted(result)


def _prompt_select_group(db, default: Optional[str] = None,
                         prompt_msg: str = "选择目标群") -> Optional[Group]:
    """交互式选群：显示所有群，按编号或名称选择，可输入空跳过"""
    groups = list_groups(db)
    if not groups:
        return None
    def_grp = get_default_group(db)
    print(color(f"  可用群列表：", "dim"))
    for i, g in enumerate(groups, 1):
        mark = color("★", "yellow") if g.default_group else " "
        style_tag = ""
        if g.emphasize_barrier:
            style_tag += "🎯强调门槛"
        if g.emphasize_friendly:
            style_tag += "👶带新友好"
        if g.emphasize_venue:
            style_tag += "📍强调地点"
        line = f"    {i:>2}. {mark} {g.display_name()}"
        if g.default_city:
            line += f" [{g.default_city}·{g.default_shop}]"
        if style_tag:
            line += f" {style_tag}"
        print(line)

    while True:
        default_val = ""
        if default:
            default_val = default
        elif def_grp:
            default_val = def_grp.alias or def_grp.name or ""
        suffix = f" [默认:{default_val}]" if default_val else " [空=不指定]"
        val = input(f"  {prompt_msg}{suffix}: ").strip()
        if not val and default:
            val = default
        if not val:
            return None
        if val.isdigit():
            idx = int(val) - 1
            if 0 <= idx < len(groups):
                return groups[idx]
        # 按名称/简称找
        g = get_group(db, val)
        if g:
            return g
        print(color("  ! 无效编号/群名，重新输入或直接回车跳过", "red"))


# =====================================================
#  群管理命令
# =====================================================

def cmd_group(db, args):
    if not args:
        print(color("! 用法：group <save|list|del> ...", "red"))
        return
    sub = args[0].lower()
    if sub == "list":
        _cmd_group_list(db)
    elif sub == "save":
        _cmd_group_save(db, args[1:])
    elif sub in ("del", "rm", "delete", "remove"):
        _cmd_group_del(db, args[1:])
    else:
        print(color(f"! 未知子命令 group {sub}", "red"))


def _cmd_group_list(db):
    groups = list_groups(db)
    if not groups:
        print(color("! 暂无群配置，用 group save <群名> [简称] 创建", "yellow"))
        return
    print(color(f"\n{'★':<2} {'ID':<10} {'简称':<8} {'群名':24} {'默认城市':12} 文案偏好", "bold"))
    print("-" * 80)
    for g in groups:
        star = color("★", "yellow") if g.default_group else " "
        prefs = []
        if g.emphasize_barrier: prefs.append("🎯强调门槛")
        if g.emphasize_friendly: prefs.append("👶带新友好")
        if g.emphasize_venue: prefs.append("📍强调地点")
        style_map = {"formal": "正式", "casual": "轻松", "hardcore": "硬核", "friendly": "友好"}
        prefs.insert(0, f"口吻:{style_map.get(g.publish_style, g.publish_style)}")
        city = f"{g.default_city}·{g.default_shop}" if g.default_city else "-"
        print(f"{star:<2} {g.id:<10} {(g.alias or '-'):<8} {(g.name or '-')[:24]:24} {city[:12]:12} {'  '.join(prefs)}")
        if g.footer_note:
            print(f"     {color('📝 ' + g.footer_note, 'dim')}")
    print()


def _cmd_group_save(db, args):
    if not args:
        print(color("! 用法：group save <群名> [简称] [--default]", "red"))
        return
    name = args[0]
    alias = args[1] if len(args) >= 2 and not args[1].startswith("--") else ""
    is_default = "--default" in args or "-d" in args

    existing = get_group(db, name) or (get_group(db, alias) if alias else None)
    if existing:
        if not prompt_bool(f"群「{name}」已存在，覆盖？", False):
            return
        delete_group(db, existing.id)

    print(color(f"\n配置群「{name}」({alias or '无简称'})", "cyan"))
    city = prompt("默认城市（可空）", required=False, default="")
    shop = prompt("默认店铺（可空）", required=False, default="")
    style = prompt(
        "文案口吻（formal正式 / casual轻松 / hardcore硬核 / friendly友好）",
        default="formal",
        validator=lambda x: (x in ("formal", "casual", "hardcore", "friendly"),
                             "请选择: formal/casual/hardcore/friendly"),
    )
    emph_barrier = prompt_bool("文案是否强调门槛（老玩家群）", False)
    emph_friendly = prompt_bool("文案是否强调可带新（萌新群）", False)
    emph_venue = prompt_bool("文案是否强调时间地点（店铺群）", False)
    footer = prompt("群专属文末注（如'请先看群规再报名'，可空）", required=False, default="")

    if not is_default and get_default_group(db) is None:
        is_default = prompt_bool("设为默认群？（new/copy/draft 自动选用）", True)

    group = Group.create(
        name=name, alias=alias, default_group=is_default,
        publish_style=style, default_city=city, default_shop=shop,
        emphasize_barrier=emph_barrier, emphasize_friendly=emph_friendly,
        emphasize_venue=emph_venue, footer_note=footer,
    )
    add_group(db, group)
    print(color(f"✓ 群已保存: {group.display_name()}", "green"))
    if is_default:
        print(color("  （已设为默认群）", "yellow"))


def _cmd_group_del(db, args):
    if not args:
        print(color("! 用法：group del <群名/ID/简称>", "red"))
        return
    identifier = " ".join(args)
    g = get_group(db, identifier)
    if not g:
        print(color(f"! 未找到群: {identifier}", "red"))
        return
    if not prompt_bool(f"确认删除群「{g.display_name()}」？", False):
        return
    if delete_group(db, g.id):
        print(color(f"✓ 已删除: {g.display_name()}", "green"))


# =====================================================
#  模板命令
# =====================================================

def cmd_template(db, args):
    if not args:
        print(color("! 用法：template <save|list|del> ...", "red"))
        return
    sub = args[0].lower()
    if sub == "list":
        _cmd_template_list(db)
    elif sub == "save":
        _cmd_template_save(db, args[1:])
    elif sub in ("del", "rm", "delete", "remove"):
        _cmd_template_del(db, args[1:])
    else:
        print(color(f"! 未知子命令 template {sub}", "red"))


def _cmd_template_list(db):
    templates = list_templates(db)
    if not templates:
        print(color("! 暂无模板，用 template save <名称> [车ID] 创建", "yellow"))
        return
    print(color(f"\n{'ID':10} {'模板名':20} {'人数':>4} {'时长':>5} {'地点':16} {'门槛':8}", "bold"))
    print("-" * 72)
    for t in templates:
        loc = f"{t.city}·{t.shop}"
        exp = f"≥{t.min_experience}硬核" if t.min_experience > 0 else "无门槛"
        unread = "未读本✓" if t.require_unread else ""
        print(f"{t.id:10} {t.name[:20]:20} {t.total_players:>4} "
              f"{t.duration_hours:>4.1f}h {loc[:16]:16} {exp} {unread}")
        if t.role_constraints:
            print(f"           {color('🎭 ' + t.role_constraints, 'dim')}")
    print()


def _cmd_template_save(db, args):
    if not args:
        print(color("! 用法：template save <模板名> [车ID]", "red"))
        return
    name = args[0]
    car = None
    if len(args) >= 2:
        car = _get_car_or_error(db, args[1])
        if not car:
            return
    else:
        # 默认用最近创建的车
        cars = list_cars(db)
        if cars:
            car = cars[0]
            print(color(f"ℹ️  将使用最近创建的车：{car.name} ({car.id})", "dim"))
        else:
            print(color("! 暂无车辆可用来保存模板", "yellow"))
            return

    # 如果模板名已存在，提示是否覆盖
    existing = get_template(db, name)
    if existing:
        if not prompt_bool(f"模板「{name}」已存在，是否覆盖？", False):
            return
        delete_template(db, existing.id)

    template = CarTemplate.create(
        name=name,
        total_players=car.total_players,
        duration_hours=car.duration_hours,
        city=car.city,
        shop=car.shop,
        role_constraints=car.role_constraints,
        require_unread=car.require_unread,
        min_experience=car.min_experience,
    )
    add_template(db, template)
    print(color(f"✓ 模板「{name}」已保存（ID: {template.id}）", "green"))
    print(color("  下次可直接用：new -t " + name, "dim"))


def _cmd_template_del(db, args):
    if not args:
        print(color("! 用法：template del <模板名或ID>", "red"))
        return
    target = args[0]
    tpl = get_template(db, target)
    if not tpl:
        print(color(f"! 未找到模板：{target}", "red"))
        return
    if not prompt_bool(f"确认删除模板「{tpl.name}」？", False):
        return
    if delete_template(db, tpl.id):
        print(color(f"✓ 已删除模板：{tpl.name}", "green"))


# =====================================================
#  新车命令（支持模板套用）
# =====================================================

def cmd_new(db, args):
    template_id = None
    template = None
    target_group = None
    # 解析 -t / -g 参数
    i = 0
    while i < len(args):
        if args[i] in ("-t", "--template") and i + 1 < len(args):
            tpl_name = args[i + 1]
            template = get_template(db, tpl_name)
            if not template:
                print(color(f"! 未找到模板：{tpl_name}", "red"))
                print(color("  用 template list 查看所有可用模板", "dim"))
                return
            template_id = template.id
            print(color(f"✓ 套用模板：{template.name}", "green"))
            i += 2
        elif args[i] in ("-g", "--group") and i + 1 < len(args):
            grp_name = args[i + 1]
            target_group = get_group(db, grp_name)
            if not target_group:
                print(color(f"! 未找到群：{grp_name}", "red"))
                print(color("  用 group list 查看所有可用群", "dim"))
                return
            print(color(f"✓ 归属群：{target_group.display_name()}", "green"))
            i += 2
        else:
            i += 1

    print(color("\n=== 开新车 / 新建组局 ===", "bold", "cyan"))
    print("请依次填写以下信息（留空使用默认值 / 模板值）\n")

    defaults = template or type('X', (), {
        'total_players': 6, 'duration_hours': 5.0,
        'city': '', 'shop': '',
        'role_constraints': '', 'require_unread': True, 'min_experience': 0,
    })()

    name = prompt("本名 / 剧本名称", required=True)
    total_players = int(prompt(
        "玩家总人数", default=defaults.total_players, validator=v_int_pos,
    ))
    duration_hours = float(prompt(
        "预计时长（小时）", default=defaults.duration_hours, validator=v_float_pos,
    ))
    city = prompt("城市", default=defaults.city or None, required=True)
    shop = prompt("店铺名称", default=defaults.shop or None, required=True)

    start_dt = None
    while start_dt is None:
        default_time = datetime.now() + timedelta(days=1)
        default_time = default_time.replace(hour=19, minute=0, second=0, microsecond=0)
        raw = prompt("开车时间", default=default_time.strftime("%Y-%m-%d 19:00"))
        ok, result = v_datetime(raw)
        if ok:
            start_dt = result
        else:
            print(color(f"  ! {result}", "red"))

    role_constraints = prompt(
        "角色性别配置（如 3男3女，或「必男1不接受反串」，可留空）",
        default=defaults.role_constraints or "", required=False,
    )
    require_unread = prompt_bool(
        "是否要求所有人未读本（防天眼/剧透）",
        default=defaults.require_unread,
    )
    min_exp = int(prompt(
        "最低硬核本经验（0=无门槛/萌新可进）",
        default=defaults.min_experience, validator=v_int_nonneg,
    ))

    # 选群
    if target_group is None and (db.groups or True):  # 有配置过群时才问
        g = _prompt_select_group(db, default=target_group.name if target_group else None)
        if g:
            target_group = g

    target_group_id = target_group.id if target_group else None

    car = Car.create(
        name=name, total_players=total_players, duration_hours=duration_hours,
        city=city, shop=shop, start_time=start_dt,
        role_constraints=role_constraints, require_unread=require_unread,
        min_experience=min_exp, template_id=template_id,
        target_group=target_group_id,
    )
    add_car(db, car)

    print(color(f"\n✓ 车辆创建成功！", "green", "bold"))
    print(f"  车辆ID: {color(car.id, 'yellow', 'bold')}")
    print(f"  简称: {car.name} · {car.total_players}人 · {car.duration_hours}h")
    print(f"  时间: {car.start_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  地点: {car.city} · {car.shop}")
    if target_group:
        print(f"  归属群: {target_group.display_name()}")
    if car.role_constraints:
        print(f"  配置: {car.role_constraints}")
    if car.require_unread:
        print(f"  要求: 未读本 ✓")
    if car.min_experience > 0:
        print(f"  门槛: ≥{car.min_experience}个硬核本经验")
    else:
        print(f"  门槛: 无门槛（萌新也可进）")
    if template:
        print(color(f"  （来源模板: {template.name}）", "dim"))
    print(color(f"\n  添加玩家：add {car.id}", "dim"))

    if prompt_bool("\n  将此配置保存为模板，下次可直接套用？", False):
        tpl_name = prompt("模板名称（如 周末5h标配）", required=True)
        existing = get_template(db, tpl_name)
        if existing and not prompt_bool(f"模板「{tpl_name}」已存在，覆盖？", False):
            return car
        if existing:
            delete_template(db, existing.id)
        tpl = CarTemplate.create(
            name=tpl_name, total_players=car.total_players,
            duration_hours=car.duration_hours, city=car.city, shop=car.shop,
            role_constraints=car.role_constraints,
            require_unread=car.require_unread, min_experience=car.min_experience,
        )
        add_template(db, tpl)
        print(color(f"✓ 模板已保存：{tpl.name} (ID: {tpl.id})", "green"))
    return car


# =====================================================
#  工具函数
# =====================================================

def _get_car_or_error(db, car_id):
    car = get_car(db, car_id)
    if not car:
        matches = [c for c in db.cars if car_id.lower() in c.name.lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(color(f"! 按名称找到多辆车，请用精确ID：", "red"))
            for c in matches[:5]:
                print(f"    {c.id}  {c.name}")
            return None
        print(color(f"! 未找到车辆：{car_id}", "red"))
        print(color("  用 list 命令查看所有车辆ID", "dim"))
    return car


# =====================================================
#  添加报名（玩家资料与单次报名分离）
# =====================================================

def cmd_add(db, args):
    if not args:
        print(color("! 用法：add <车辆ID> [-g 来源群]", "red"))
        return
    # 解析 -g 参数和车ID
    source_group = None
    car_id = None
    i = 0
    while i < len(args):
        if args[i] in ("-g", "--group") and i + 1 < len(args):
            grp_name = args[i + 1]
            source_group = get_group(db, grp_name)
            if not source_group:
                print(color(f"! 未找到群：{grp_name}", "red"))
                print(color("  用 group list 查看所有可用群", "dim"))
                return
            print(color(f"✓ 来源群：{source_group.display_name()}", "green"))
            i += 2
        else:
            if not car_id:
                car_id = args[i]
            i += 1

    if not car_id:
        print(color("! 未指定车辆ID", "red"))
        return
    car = _get_car_or_error(db, car_id)
    if not car:
        return

    print(color(f"\n=== 添加报名 · {car.name} ({car.id}) ===", "bold", "cyan"))
    print("说明：玩家基础资料（昵称/性别/累计经验）长期复用；可到时间/是否已读本/备注按当次车录入，不影响别的车。\n")

    # 如果没通过 -g 指定，交互问来源群（默认用车的目标群）
    if source_group is None:
        default_grp = None
        if car.target_group:
            default_grp = get_group(db, car.target_group)
        g = _prompt_select_group(db,
            default=default_grp.alias if default_grp else None,
            prompt_msg="【本次】来源群（玩家从哪个群来的）")
        if g:
            source_group = g

    nickname = prompt("玩家昵称", required=True)
    gender_raw = prompt("性别（男/女）", required=True, validator=v_gender)
    gender = "男" if gender_raw in ("男", "M", "m") else "女"

    # ------- 当次车特有信息 -------
    avail_time = prompt(
        "【本次】可到时间（如 19:00前 / 18:30-23:00 / 随时）",
        default="随时", required=True,
    )
    has_read = False
    if car.require_unread:
        has_read = prompt_bool(
            f"【本次】玩家是否已读本《{car.name}》（是=不满足未读本要求）",
            default=False,
        )
    notes = prompt("【本次】备注雷点（迟到/跳车/天眼等；无则留空）", required=False)

    # ------- 玩家长期资料 -------
    past_books = prompt(
        "【长期】过往硬核本履历（逗号分隔，如 须臾,芥子；可留空）",
        required=False,
    )
    auto_exp = len([x for x in re.split(r"[,，、\s]+", past_books) if x])
    exp_count_raw = prompt(
        f"【长期】累计硬核本数（0=萌新；自动估算={auto_exp}）",
        default=auto_exp, validator=v_int_nonneg,
    )
    try:
        exp_count = int(exp_count_raw)
    except ValueError:
        exp_count = 0
    accept_cc_default = prompt_bool("【长期】通常是否接受反串", default=False)

    # ------- 【长期】标签 -------
    print(color("  【长期】标签预设(用数字选，可多个逗号分隔，也可手动输入；留空跳过)：", "dim"))
    preset_line = "  " + "  ".join(f"{i+1}.{t}" for i, t in enumerate(PRESET_TAGS[:10]))
    print(preset_line)
    print("  11-20: " + " ".join(PRESET_TAGS[10:]))
    tags_input = prompt(
        "【长期】玩家标签（如: 1,3,靠谱 或直接输入标签）",
        required=False,
    )
    initial_tags = []
    if tags_input:
        for piece in re.split(r"[,，\s]+", tags_input.strip()):
            if not piece:
                continue
            if piece.isdigit():
                idx = int(piece) - 1
                if 0 <= idx < len(PRESET_TAGS):
                    initial_tags.append(PRESET_TAGS[idx])
            else:
                initial_tags.append(piece)
    # 去重
    initial_tags = list(dict.fromkeys(initial_tags))

    # ------- 确定玩家实体 -------
    existing_player = find_player_by_nickname(db, nickname)
    reuse = False
    if existing_player:
        print(color(f"\n? 资料库已有同名玩家：{existing_player.nickname} "
                     f"({existing_player.gender} · {exp_display(existing_player.experience_count)})",
                     "yellow"))
        reuse = prompt_bool("  复用其基础资料？（当次可到时间/已读本/备注仍按本次录入）", True)

    if reuse and existing_player:
        player = existing_player
        # 如果本次填写了更多信息，更新长期资料
        changed = False
        if player.gender != gender:
            if prompt_bool(f"  性别由「{player.gender}」改为「{gender}」？", False):
                player.gender = gender
                changed = True
        if past_books and player.past_hardcore_books != past_books:
            if prompt_bool("  用本次履历更新玩家资料库？", True):
                player.past_hardcore_books = past_books
                changed = True
        if exp_count > player.experience_count:
            if prompt_bool(f"  累计经验由 {player.experience_count} 更新为 {exp_count}？", True):
                player.experience_count = exp_count
                changed = True
        if accept_cc_default != player.accept_crosscast:
            player.accept_crosscast = accept_cc_default
            changed = True
        # 标签合并
        if initial_tags:
            old_tags_set = set(player.tags or [])
            new_added = [t for t in initial_tags if t not in old_tags_set]
            if new_added:
                print(color(f"  ℹ️  本次将为玩家追加标签: {' '.join(new_added)}", "dim"))
                for t in new_added:
                    player.add_tag(t)
                changed = True
        if changed:
            save_db(db)
    else:
        player = Player.create(
            nickname=nickname, gender=gender,
            past_hardcore_books=past_books,
            accept_crosscast=accept_cc_default,
            experience_count=exp_count,
            tags=initial_tags,
        )
        add_player(db, player)

    # 问一下本次是否反串（默认跟随长期值）
    accept_cc_this_time = None
    if prompt_bool(f"  【本次】是否改变反串偏好？（默认：{'接受' if accept_cc_default else '不接受'}）", False):
        accept_cc_this_time = prompt_bool("    本次是否接受反串？", accept_cc_default)

    # ------- 创建/更新当次报名 -------
    source_group_id = source_group.id if source_group else None
    reg = Registration.create(
        car_id=car.id, player_id=player.id,
        available_time=avail_time, read_this_book=has_read,
        notes=notes, accept_crosscast_override=accept_cc_this_time,
        source_group=source_group_id,  # ✅ v1.3: 记录来源群
    )
    add_registration(db, reg)

    cc_str = "接受反串" if reg.effective_accept_crosscast(player) else "不反串"
    print(color(f"\n✓ 本次报名登记成功！", "green"))
    print(f"  玩家: {player.nickname} ({player.gender} · 累计{exp_display(player.experience_count)})")
    td = tags_display(player)
    if td:
        print(f"  标签: {td}")
    if source_group:
        print(f"  来源群: {source_group.display_name()}")
    print(f"  本次: 可到{reg.available_time} · "
          f"{'已读本⚠️' if reg.read_this_book else '未读本✓'} · "
          f"{cc_str}")
    if reg.notes:
        print(f"  备注: {reg.notes}")


# =====================================================
#  玩家资料库
# =====================================================

def cmd_players(db, args):
    players = db.players
    if not players:
        print(color("! 资料库暂无玩家", "yellow"))
        return
    # 按标签筛选
    if args:
        tag_filter = " ".join(args).strip()
        players = [p for p in players if tag_filter in (p.tags or []) or
                   any(tag_filter in t for t in (p.tags or []))]
        if not players:
            print(color(f"! 没有含标签「{tag_filter}」的玩家", "yellow"))
            return
        print(color(f"🔍 筛选标签「{tag_filter}」，共 {len(players)} 名玩家：", "cyan", "bold"))
    print(color(f"\n{'昵称':14} {'性别':<4} {'经验':<8} {'反串':<4} {'报名':<6} {'常用群':<10} 标签", "bold"))
    print("-" * 90)
    for p in sorted(players, key=lambda x: (len(x.risk_tags()) > 0, -x.experience_count)):
        regs = get_player_registrations(db, p.id)
        cc = "✓" if p.accept_crosscast else "✗"
        td = tags_display(p, max_len=50) or color("（无标签）", "dim")
        # 常用来源群
        group_counts = {}
        for r in regs:
            if r.source_group:
                grp = get_group(db, r.source_group)
                key = grp.alias or grp.name if grp else r.source_group
                group_counts[key] = group_counts.get(key, 0) + 1
        most_common = max(group_counts.items(), key=lambda x: x[1])[0] if group_counts else "-"
        print(f"{p.nickname[:14]:14} {p.gender:<4} {exp_display(p.experience_count):<8} "
              f"{cc:<4} {len(regs):<6} {most_common[:10]:<10} {td}")
    print(f"\n共 {len(players)} 名玩家")


def cmd_tag(db, args):
    """tag <玩家昵称> +/-<标签> ..."""
    if len(args) < 2:
        print(color("! 用法：tag <玩家昵称> +/-<标签> [+/-<标签>...]", "red"))
        print("  示例：tag 小明 +靠谱 -易迟到 +推土机")
        return
    nickname = args[0]
    player = find_player_by_nickname(db, nickname)
    if not player:
        # 尝试模糊匹配
        matches = [p for p in db.players if nickname.lower() in p.nickname.lower()]
        if len(matches) == 1:
            player = matches[0]
            print(color(f"ℹ️  匹配到玩家：{player.nickname}", "dim"))
        else:
            print(color(f"! 未找到玩家：{nickname}", "red"))
            return
    changed = False
    for tok in args[1:]:
        if not tok:
            continue
        if tok.startswith("+") or tok.startswith("＋"):
            tag = tok[1:].strip()
            if tag:
                player.add_tag(tag)
                print(color(f"  ✓ 已加标签：{tag}", "green"))
                changed = True
        elif tok.startswith("-") or tok.startswith("－"):
            tag = tok[1:].strip()
            if tag and player.has_tag(tag):
                player.remove_tag(tag)
                print(color(f"  ✓ 已去标签：{tag}", "yellow"))
                changed = True
        else:
            print(color(f"  ! 忽略：{tok}（请用 +标签 / -标签）", "yellow"))
    if changed:
        save_db(db)
        td = tags_display(player)
        print(f"  最新标签: {td or color('（无）', 'dim')}")


# =====================================================
#  view 命令（含筛选/排序参数与交互式菜单）
# =====================================================

def _parse_view_options(args) -> Tuple[str, str, str]:
    """从 args 中解析筛选、排序，并返回 (car_id, filter, sort)"""
    car_id = ""
    filter_status = "all"
    sort_by = "score"
    i = 0
    filters_map = {
        "--pending": "pending", "--未处理": "pending",
        "--eligible": "eligible", "--可进": "eligible", "--ok": "eligible",
        "--approved": "approved", "--已确认": "approved",
        "--bench": "bench", "--替补": "bench",
        "--conflict": "conflict", "--冲突": "conflict",
    }
    while i < len(args):
        a = args[i]
        if a in filters_map:
            filter_status = filters_map[a]
            i += 1
        elif a == "--sort" and i + 1 < len(args):
            sort_by = args[i + 1].lower()
            if sort_by not in ("score", "experience", "exp", "time", "created"):
                print(color(f"! 未知排序方式：{sort_by}，使用 score", "yellow"))
                sort_by = "score"
            if sort_by == "exp":
                sort_by = "experience"
            i += 2
        elif a.startswith("--sort="):
            sort_by = a.split("=", 1)[1].lower()
            if sort_by == "exp":
                sort_by = "experience"
            i += 1
        elif not car_id and not a.startswith("--"):
            car_id = a
            i += 1
        else:
            i += 1
    return car_id, filter_status, sort_by


def _interactive_view_options(filter_status: str, sort_by: str) -> Tuple[str, str]:
    """交互式选择筛选和排序"""
    print(color("\n  当前选项：", "dim"), end="")
    print(f"筛选={color(filter_status, 'yellow')}  排序={color(sort_by, 'yellow')}")
    print("  筛选: 1=全部  2=仅未处理  3=仅可进正车  4=仅已确认  5=仅替补  6=仅冲突")
    print("  排序: a=匹配分  b=经验(高→低)  c=可到时间(早→晚)  d=报名先后")
    print("  回车=使用当前选项，q=返回")
    try:
        sel = input(color("  请选择> ", "cyan")).strip().lower()
    except EOFError:
        return filter_status, sort_by
    if not sel or sel == "q":
        return filter_status, sort_by
    f_map = {"1": "all", "2": "pending", "3": "eligible", "4": "approved", "5": "bench", "6": "conflict"}
    s_map = {"a": "score", "b": "experience", "c": "time", "d": "created"}
    if sel in f_map:
        filter_status = f_map[sel]
    if sel in s_map:
        sort_by = s_map[sel]
    # 支持组合输入，如 "2b" = 未处理 + 按经验
    if len(sel) >= 2:
        if sel[0] in f_map:
            filter_status = f_map[sel[0]]
        if sel[1] in s_map:
            sort_by = s_map[sel[1]]
    return filter_status, sort_by


def _gather_indexed_players(db, car, regs, filter_status="all", sort_by="score"):
    triaged = triage_registrations(db, car, regs, filter_status=filter_status, sort_by=sort_by)
    sections = [
        ("conflict", "⛔ 条件冲突（严重问题，不建议入队）", triaged["conflict"]),
        ("warning", "⚠️ 时间不符 / 条件存疑（需人工确认）", triaged["warning"]),
        ("match", "✅ 条件匹配（可优先入队）", triaged["match"]),
    ]
    ordered = []
    idx = 0
    for _, _, lst in sections:
        for r in lst:
            idx += 1
            ordered.append((idx, r))
    return ordered, sections, triaged


def cmd_view(db, args):
    car_id, filter_status, sort_by = _parse_view_options(args)
    if not car_id:
        print(color("! 用法：view <车辆ID> [--筛选] [--sort 方式]", "red"))
        print(color("  筛选: --pending / --eligible / --approved / --bench / --conflict", "dim"))
        print(color("  排序: --sort score|experience|time|created", "dim"))
        return
    car = _get_car_or_error(db, car_id)
    if not car:
        return
    regs = get_registrations_by_car(db, car.id)
    if not regs:
        print(color(f"! 该车尚无报名，使用 add {car.id} 添加", "yellow"))
        return

    if not any(a.startswith("--") for a in args):
        filter_status, sort_by = _interactive_view_options(filter_status, sort_by)

    while True:
        regs = get_registrations_by_car(db, car.id)
        ordered, sections, triaged = _gather_indexed_players(db, car, regs, filter_status, sort_by)
        total = len(ordered)
        approved_count = len([r for r in regs if r.status == "approved"])
        benched_count = len([r for r in regs if r.status == "bench"])

        print(color(f"\n{'='*64}", "bold", "cyan"))
        print(color(f"🚗 {car.name}  报名分析  ({car.id})", "bold", "cyan"))
        print(color(f"{'='*64}", "bold", "cyan"))
        _print_car_header(car, db)
        filter_label = {
            "all": "全部", "pending": "仅未处理", "eligible": "仅可进正车(无严重冲突)",
            "approved": "仅已确认", "bench": "仅替补", "conflict": "仅严重冲突",
        }
        sort_label = {"score": "匹配分", "experience": "经验", "time": "可到时间", "created": "报名先后"}
        print(f"  报名: {total}/{len(regs)} 人（筛选:{filter_label.get(filter_status, filter_status)}"
              f" · 排序:{sort_label.get(sort_by, sort_by)}）"
              f"  已确认: {approved_count}/{car.total_players}  替补: {benched_count}")
        print()

        idx = 0
        shown = 0
        for key, title, lst in sections:
            if not lst:
                continue
            color_tag = "red" if key == "conflict" else ("yellow" if key == "warning" else "green")
            print(color(f"── {title} ({len(lst)}人) ──", color_tag, "bold"))
            for r in lst:
                idx += 1
                shown += 1
                status_tag = ""
                reg = r.registration
                player = r.player
                if reg.status == "approved":
                    status_tag = color(" [✔已确认]", "green")
                elif reg.status == "bench":
                    status_tag = color(" [⏸替补]", "blue")
                cc = reg.effective_accept_crosscast(player)
                line = f"{color(f'[{idx:>2}]', 'bold')} {player.nickname} "
                line += f"({player.gender}·{exp_display(player.experience_count)})"
                line += status_tag
                # 长期标签带出
                td = tags_display(player, max_len=30)
                if td:
                    line += f" {td}"
                print(line)
                extra_bits = []
                if cc:
                    extra_bits.append("反串OK")
                extra_bits.append(f"可到:{reg.available_time}")
                if reg.read_this_book:
                    extra_bits.append(color("已读本⚠️", "red"))
                # 来源群
                if reg.source_group:
                    grp = get_group(db, reg.source_group)
                    if grp:
                        extra_bits.append(color(f"群:{grp.alias or grp.name}", "cyan"))
                if extra_bits:
                    print(f"     {color(' | '.join(extra_bits), 'dim')}")
                if reg.notes:
                    print(f"     {color('📝 ' + reg.notes, 'dim')}")
                if r.issues:
                    for iss in r.issues:
                        ic = "red" if iss.severity == "critical" else "yellow"
                        print(f"     {color('·', ic)} {color(str(iss), ic)}")
            print()

        if shown == 0:
            print(color("  （当前筛选下无记录，试试切换筛选条件）", "dim"))

        print(color("批量审核：a1-3 approve  |  b4,5 bench  |  k6 kick  |  范围: a1-6", "dim"))
        print(color("切换条件：1-6筛选  a-d排序  |  r刷新  q退出", "dim"))
        try:
            sel = input(color("操作> ", "cyan")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not sel:
            continue
        if sel in ("q", "quit", "exit"):
            break
        if sel == "r":
            continue

        # 解析 a/b/k + 序号 的内联审核命令
        action = None
        idx_text = sel
        if sel[0] in ("a", "ａ"):
            action = "approve"
            idx_text = sel[1:]
        elif sel[0] in ("b", "ｂ"):
            action = "bench"
            idx_text = sel[1:]
        elif sel[0] in ("k", "ｋ"):
            action = "kick"
            idx_text = sel[1:]

        if action and idx_text:
            targets = parse_index_ranges(idx_text)
            if not targets:
                print(color("  ! 无有效序号", "red"))
                continue
            idx_map = {i: r for i, r in ordered}
            _apply_bulk_action(db, car, idx_map, targets, action)
            continue

        # 筛选/排序切换
        f_map = {"1": "all", "2": "pending", "3": "eligible", "4": "approved", "5": "bench", "6": "conflict"}
        s_map = {"a": "score", "b": "experience", "c": "time", "d": "created"}
        changed = False
        if sel in f_map:
            filter_status = f_map[sel]
            changed = True
        if sel in s_map:
            sort_by = s_map[sel]
            changed = True
        if len(sel) >= 2:
            if sel[0] in f_map:
                filter_status = f_map[sel[0]]
                changed = True
            if sel[1] in s_map:
                sort_by = s_map[sel[1]]
                changed = True
        if not changed:
            # 尝试当做交互式选项菜单
            filter_status, sort_by = _interactive_view_options(filter_status, sort_by)


def _apply_bulk_action(db, car, idx_map, targets, action):
    """在 view 内批量执行 approve/bench/kick"""
    approved_count = len([r for r in db.registrations
                          if r.car_id == car.id and r.status == "approved"])
    for idx in targets:
        if idx not in idx_map:
            print(color(f"  ! 序号 {idx} 不在当前列表", "red"))
            continue
        mr = idx_map[idx]
        reg = mr.registration
        player = mr.player
        if action == "kick":
            db.registrations = [r for r in db.registrations if r.id != reg.id]
            print(color(f"  ✗ 已移除: {player.nickname}", "red"))
        elif action == "bench":
            if reg.status == "approved":
                approved_count -= 1
            reg.status = "bench"
            print(color(f"  ⏸ 替补: {player.nickname}", "blue"))
        elif action == "approve":
            if approved_count >= car.total_players and reg.status != "approved":
                print(color(f"  ! {player.nickname} → 自动替补（已达满员{car.total_players}人）", "yellow"))
                reg.status = "bench"
            else:
                if reg.status != "approved":
                    approved_count += 1
                reg.status = "approved"
                print(color(f"  ✓ 确认: {player.nickname}", "green"))
    save_db(db)
    if approved_count >= car.total_players and car.status == "open":
        if prompt_bool(f"  已确认{approved_count}人达到上限，标记为「已满」？", True):
            update_car_status(db, car.id, "full")


def _print_car_header(car, db=None):
    time_str = car.start_time.strftime("%Y-%m-%d %H:%M")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][car.start_time.weekday()]
    status_map = {"open": "招集中", "full": "已满", "done": "已结束", "cancel": "已取消"}
    st_color = {"open": "green", "full": "yellow", "done": "blue", "cancel": "red"}
    st = status_map.get(car.status, car.status)
    stc = st_color.get(car.status, "white")
    exp_str = f"≥{car.min_experience}硬核本" if car.min_experience > 0 else "无门槛"
    print(f"  🕒 {time_str} (周{weekday}) · 约{car.duration_hours}小时")
    print(f"  📍 {car.city} · {car.shop}")
    if car.target_group and db:
        grp = get_group(db, car.target_group)
        if grp:
            print(f"  👥 归属群: {grp.display_name()}")
    print(f"  👥 {car.total_players}人  "
          f"| 状态: {color(st, stc, 'bold')}  "
          f"| 未读本: {'✓' if car.require_unread else '✗'}  "
          f"| 门槛: {exp_str}")
    if car.role_constraints:
        print(f"  🎭 角色配置: {car.role_constraints}")


def _parse_indices(args):
    idxs = []
    for a in args[1:]:
        for part in re.split(r"[,，\s]+", a):
            try:
                idxs.append(int(part))
            except ValueError:
                pass
    return idxs


def cmd_approve(db, args, bench=False, kick=False):
    if len(args) < 2:
        print(color(f"! 用法：{'bench' if bench else ('kick' if kick else 'approve')} <车辆ID> <序号...>", "red"))
        return
    car = _get_car_or_error(db, args[0])
    if not car:
        return
    regs = get_registrations_by_car(db, car.id)
    ordered, _, _ = _gather_indexed_players(db, car, regs)
    idx_map = {i: r for i, r in ordered}
    targets = _parse_indices(args)
    if not targets:
        print(color("! 没有有效的序号", "red"))
        return

    approved_count = len([r for r in regs if r.status == "approved"])

    for idx in targets:
        if idx not in idx_map:
            print(color(f"! 序号 {idx} 不存在", "red"))
            continue
        mr: MatchResult = idx_map[idx]
        reg = mr.registration
        if kick:
            db.registrations = [r for r in db.registrations if r.id != reg.id]
            print(color(f"✗ 已移除: {mr.player.nickname}", "red"))
        elif bench:
            if reg.status == "approved":
                approved_count -= 1
            reg.status = "bench"
            print(color(f"⏸ 设为替补: {mr.player.nickname}", "blue"))
        else:
            if approved_count >= car.total_players and reg.status != "approved":
                print(color(f"! 已达满员{car.total_players}人，{mr.player.nickname}自动设为替补", "yellow"))
                reg.status = "bench"
            else:
                if reg.status != "approved":
                    approved_count += 1
                reg.status = "approved"
                print(color(f"✓ 确认入队: {mr.player.nickname}", "green"))
    save_db(db)

    if approved_count >= car.total_players and car.status == "open" and not kick:
        if prompt_bool(f"  已确认{approved_count}人达到上限，是否将车辆标记为「已满」？", True):
            update_car_status(db, car.id, "full")
    elif approved_count < car.total_players and car.status == "full" and not kick and not bench:
        if prompt_bool(f"  已确认{approved_count}人少于上限，是否恢复为「招集中」？", False):
            update_car_status(db, car.id, "open")


def cmd_list(db, _):
    cars = list_cars(db)
    if not cars:
        print(color("! 暂无车辆，使用 new 命令开新车", "yellow"))
        return
    print(color(f"\n{'ID':10} {'本名':14} {'人数':>5} {'时间':18} {'地点':14} {'群':8} {'状态':8} 报名", "bold"))
    print("-" * 86)
    for c in cars:
        regs = get_registrations_by_car(db, c.id)
        approved = len([r for r in regs if r.status == "approved"])
        status_map = {"open": color("招集中", "green"), "full": color("已满", "yellow"),
                      "done": color("已结束", "blue"), "cancel": color("取消", "red")}
        st = status_map.get(c.status, c.status)
        time_str = c.start_time.strftime("%m-%d %H:%M")
        loc = f"{c.city}·{c.shop}"
        exp_tag = f"≥{c.min_experience}" if c.min_experience > 0 else "0门槛"
        # 归属群
        grp_str = "-"
        if c.target_group:
            grp = get_group(db, c.target_group)
            if grp:
                grp_str = grp.alias or grp.name
                if len(grp_str) > 8:
                    grp_str = grp_str[:7] + "…"
        print(f"{c.id:10} {c.name[:14]:14} {approved}/{c.total_players:>4} "
              f"{time_str:18} {loc[:14]:14} {grp_str:8} {st:10} {len(regs):>3}  {exp_tag}")
    print()


def cmd_status(db, args):
    if len(args) < 2:
        print(color("! 用法：status <车辆ID> <open|full|done|cancel>", "red"))
        return
    car = _get_car_or_error(db, args[0])
    if not car:
        return
    target = args[1].lower()
    if target not in ("open", "full", "done", "cancel"):
        print(color("! 状态只能是 open / full / done / cancel", "red"))
        return
    update_car_status(db, car.id, target)
    print(color(f"✓ 车辆状态已更新为「{target}」", "green"))


def cmd_info(db, args):
    if not args:
        print(color("! 用法：info <车辆ID>", "red"))
        return
    car = _get_car_or_error(db, args[0])
    if not car:
        return
    print(color(f"\n=== 车辆详情 ===", "bold", "cyan"))
    print(f"  ID: {color(car.id, 'yellow', 'bold')}")
    print(f"  本名: {car.name}")
    _print_car_header(car, db)
    print(f"  创建时间: {car.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if car.template_id:
        tpl = get_template(db, car.template_id)
        if tpl:
            print(f"  来源模板: {tpl.name}")
    regs = get_registrations_by_car(db, car.id)
    if regs:
        print(f"\n  报名列表 ({len(regs)}):")
        for i, reg in enumerate(regs, 1):
            p = get_player(db, reg.player_id)
            if not p:
                continue
            status_map = {"pending": color("待审核", "yellow"),
                          "approved": color("✔已确认", "green"),
                          "bench": color("⏸替补", "blue"),
                          "rejected": color("✗拒绝", "red")}
            st = status_map.get(reg.status, reg.status)
            cc = reg.effective_accept_crosscast(p)
            extra = []
            if reg.source_group:
                grp = get_group(db, reg.source_group)
                if grp:
                    extra.append(color(f"群:{grp.alias or grp.name}", "cyan"))
            print(f"    {i:>2}. {p.nickname} ({p.gender}·{exp_display(p.experience_count)}) "
                  f"· 可到:{reg.available_time} · {'已读本⚠️' if reg.read_this_book else ''} "
                  f"· {'反串OK' if cc else ''} · {st}"
                  + (f" · {' '.join(extra)}" if extra else ""))
            td = tags_display(p, max_len=50)
            if td:
                print(f"        🏷️ {td}")
            if reg.notes:
                print(f"        📝 {reg.notes}")
    else:
        print(color("  暂无报名", "dim"))
    print()


def cmd_del(db, args):
    if not args:
        print(color("! 用法：del <车辆ID>", "red"))
        return
    car = _get_car_or_error(db, args[0])
    if not car:
        return
    if not prompt_bool(f"确认删除车辆「{car.name}」及其所有报名记录？", False):
        return
    if delete_car(db, car.id):
        print(color(f"✓ 已删除", "green"))


# =====================================================
#  复制车命令（跨群发车）
# =====================================================

def cmd_copy(db, args):
    if not args:
        print(color("! 用法：copy <车辆ID> [-g 群名]", "red"))
        return
    # 解析 -g 参数和车ID
    target_group = None
    car_id = None
    i = 0
    while i < len(args):
        if args[i] in ("-g", "--group") and i + 1 < len(args):
            grp_name = args[i + 1]
            target_group = get_group(db, grp_name)
            if not target_group:
                print(color(f"! 未找到群：{grp_name}", "red"))
                print(color("  用 group list 查看所有可用群", "dim"))
                return
            print(color(f"✓ 目标群：{target_group.display_name()}", "green"))
            i += 2
        else:
            if not car_id:
                car_id = args[i]
            i += 1

    if not car_id:
        print(color("! 未指定车辆ID", "red"))
        return
    src = _get_car_or_error(db, car_id)
    if not src:
        return

    print(color(f"\n=== 复制车队 · 源: {src.name} ({src.id}) ===", "bold", "cyan"))
    print("将从已有车复制配置，可修改时间/店铺/群名，报名记录不复制。\n")

    name = prompt("本名（留空=与源车相同）", default=src.name, required=True)
    city = prompt("城市", default=src.city, required=True)
    shop = prompt("店铺（可换不同分店）", default=src.shop, required=True)

    # 选群（覆盖 -g 或交互选择）
    src_grp = None
    if src.target_group:
        src_grp = get_group(db, src.target_group)
    if target_group is None:
        default_val = target_group.name if target_group else (src_grp.alias if src_grp else None)
        g = _prompt_select_group(db, default=default_val, prompt_msg="选择目标群（归属群）")
        if g:
            target_group = g

    start_dt = None
    while start_dt is None:
        default_time = datetime.now() + timedelta(days=1)
        default_time = default_time.replace(hour=19, minute=0, second=0, microsecond=0)
        raw = prompt("开车时间", default=default_time.strftime("%Y-%m-%d 19:00"))
        ok, result = v_datetime(raw)
        if ok:
            start_dt = result
        else:
            print(color(f"  ! {result}", "red"))

    total_players = int(prompt("玩家总人数", default=src.total_players, validator=v_int_pos))
    duration_hours = float(prompt("预计时长（小时）", default=src.duration_hours, validator=v_float_pos))
    role_constraints = prompt("角色配置", default=src.role_constraints or "", required=False)
    require_unread = prompt_bool("要求未读本", default=src.require_unread)
    min_exp = int(prompt("最低经验（0=无门槛）", default=src.min_experience, validator=v_int_nonneg))

    target_group_id = target_group.id if target_group else None

    new_car = src.copy(
        name=name, start_time=start_dt, city=city, shop=shop,
        total_players=total_players, duration_hours=duration_hours,
        role_constraints=role_constraints,
        require_unread=require_unread, min_experience=min_exp,
        target_group=target_group_id,  # ✅ v1.3: 持久化归属群
    )
    add_car(db, new_car)

    print(color(f"\n✓ 新车已创建！", "green", "bold"))
    print(f"  车辆ID: {color(new_car.id, 'yellow', 'bold')}")
    print(f"  {new_car.name} · {new_car.total_players}人 · {new_car.duration_hours}h")
    print(f"  时间: {new_car.start_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  地点: {new_car.city} · {new_car.shop}")
    if target_group:
        print(f"  归属群: {target_group.display_name()}")
    if min_exp > 0:
        print(f"  门槛: ≥{min_exp}硬核本")
    else:
        print(f"  门槛: 无门槛（萌新友好）")
    print(color(f"\n  添加玩家：add {new_car.id}", "dim"))
    print(color(f"  生成文案：draft {new_car.id}", "dim"))

    if prompt_bool("\n  保存为模板？", False):
        tpl_name = prompt("模板名称", required=True)
        existing = get_template(db, tpl_name)
        if existing and not prompt_bool(f"模板「{tpl_name}」已存在，覆盖？", False):
            return new_car
        if existing:
            delete_template(db, existing.id)
        tpl = CarTemplate.create(
            name=tpl_name, total_players=new_car.total_players,
            duration_hours=new_car.duration_hours, city=new_car.city, shop=new_car.shop,
            role_constraints=new_car.role_constraints,
            require_unread=new_car.require_unread, min_experience=new_car.min_experience,
        )
        add_template(db, tpl)
        print(color(f"✓ 模板已保存：{tpl.name}", "green"))

    return new_car


# =====================================================
#  草稿/文案命令（多群发布）
# =====================================================

def _generate_draft_for_group(car, group, db):
    """根据群的强调偏好生成专属版本文案"""
    weekday = ["一", "二", "三", "四", "五", "六", "日"][car.start_time.weekday()]
    time_str = car.start_time.strftime(f"%m月%d日 周{weekday} %H:%M")
    end_time = car.start_time + timedelta(hours=car.duration_hours)
    end_str = end_time.strftime("%H:%M")
    exp_str = f"≥{car.min_experience}个硬核本经验" if car.min_experience > 0 else "无门槛（萌新友好）"
    loc_str = f"{car.city}·{car.shop}" if car.city else car.shop

    regs = get_registrations_by_car(db, car.id)
    approved_count = len([r for r in regs if r.status == "approved"])
    pending_count = len([r for r in regs if r.status == "pending"])
    remaining = max(0, car.total_players - approved_count)

    group_name = group.name if group else ""
    group_alias = group.alias if group else ""
    display_name = group_alias or group_name

    draft_lines = []
    group_tag = f"【{display_name}】" if display_name else ""

    style = group.publish_style if group else "formal"
    style_emoji = {"formal": "🔥", "casual": "🎉", "hardcore": "💀", "friendly": "💖"}
    style_title = {"formal": "硬核发车", "casual": "开车啦", "hardcore": "硬核组局", "friendly": "萌新友好"}
    emoji = style_emoji.get(style, "🔥")
    title = style_title.get(style, "硬核发车")

    draft_lines.append(f"{group_tag}{emoji}{title}{emoji}")
    draft_lines.append(f"📖《{car.name}》")

    emphasized = []

    if group and group.emphasize_venue:
        emphasized.extend([
            f"📍 {loc_str}（{car.shop}）",
            f"⏰ {time_str}～{end_str}（约{car.duration_hours:.0f}h）",
            f"👥 {car.total_players}人",
        ])
    elif group and group.emphasize_barrier:
        emphasized.extend([
            f"⏰ {time_str}～{end_str}（约{car.duration_hours:.0f}h）",
            f"💪 门槛：{exp_str}",
            f"📍 {loc_str}",
        ])
    elif group and group.emphasize_friendly:
        emphasized.extend([
            f"⏰ {time_str}～{end_str}（约{car.duration_hours:.0f}h）",
            f"📍 {loc_str}",
            f"👥 {car.total_players}人 · 新人友好，老玩家带新",
        ])
    else:
        emphasized.extend([
            f"⏰ {time_str}～{end_str}（约{car.duration_hours:.0f}h）",
            f"📍 {loc_str}",
            f"👥 {car.total_players}人 | {exp_str}",
        ])

    draft_lines.extend(emphasized)

    if group and group.emphasize_barrier and car.min_experience > 0:
        draft_lines.append("⚠️ 硬核本不扶车，请确保有足够经验")

    if group and group.emphasize_friendly and car.min_experience == 0:
        draft_lines.append("💖 萌新可上车，老玩家耐心带新，放心报名")

    if group and group.emphasize_venue:
        draft_lines.append("🏠 店铺环境好，有免费零食饮料，车位紧张请准时")

    if car.role_constraints:
        draft_lines.append(f"🎭 {car.role_constraints}")
    if car.require_unread:
        draft_lines.append("📜 要求全员未读本，严禁天眼/剧透")

    draft_lines.append("")

    if remaining > 0:
        draft_lines.append(f"✅ 已确认 {approved_count}/{car.total_players}  🔓 还剩 {remaining} 席")
    else:
        draft_lines.append(f"✅ 已满员 {approved_count}/{car.total_players}")
    if pending_count > 0:
        draft_lines.append(f"⏳ 审核中 {pending_count} 人")
    draft_lines.append("")

    if group and group.emphasize_barrier:
        draft_lines.append("👇 有意私车头报名，请提供：")
        draft_lines.append("  昵称 / 性别 / 可到时间 / 硬核本数 / 是否反串 / 最近玩过的3个硬核本")
    elif group and group.emphasize_friendly:
        draft_lines.append("👇 萌新小伙伴私车头报名就行啦：")
        draft_lines.append("  昵称 / 性别 / 可到时间 / 有没有玩过本（没有也没关系）")
    else:
        draft_lines.append("👇 有意私车头报名，格式：")
        draft_lines.append("  昵称 / 性别 / 可到时间 / 硬核本数 / 是否反串")

    if group and group.footer_note:
        draft_lines.append("")
        draft_lines.append(f"📝 {group.footer_note}")

    return draft_lines


def cmd_draft(db, args):
    if not args:
        print(color("! 用法：draft <车辆ID> [-g 群名1,群名2,...]", "red"))
        print(color("  示例: draft ab12 -g 老玩家群,萌新群", "dim"))
        return

    car_id = args[0]
    car = _get_car_or_error(db, car_id)
    if not car:
        return

    selected_groups = []
    group_names = []
    i = 1
    while i < len(args):
        if args[i] == "-g" and i + 1 < len(args):
            group_names = [x.strip() for x in args[i+1].replace("，", ",").split(",") if x.strip()]
            i += 2
        else:
            i += 1

    for gn in group_names:
        grp = get_group(db, gn)
        if grp:
            selected_groups.append(grp)
        else:
            print(color(f"! 未找到群「{gn}」，已跳过", "yellow"))

    if not selected_groups and car.target_group:
        grp = get_group(db, car.target_group)
        if grp:
            selected_groups.append(grp)

    if not selected_groups and list_groups(db):
        print(color("\n请选择目标群（可多选，用逗号分隔序号，如 1,3,4；a=全选；回车=不指定群）", "cyan"))
        all_groups = list_groups(db)
        for j, g in enumerate(all_groups, 1):
            flags = []
            if g.default_group:
                flags.append("默认")
            if g.emphasize_barrier:
                flags.append("重门槛")
            if g.emphasize_friendly:
                flags.append("重带新")
            if g.emphasize_venue:
                flags.append("重地点")
            flag_str = f" [{','.join(flags)}]" if flags else ""
            print(f"  {j}. {g.alias or g.name}（{g.name}）{flag_str}")

        sel = prompt("选择群", required=False) or ""
        if sel.lower() in ("a", "all", "全部"):
            selected_groups = all_groups
        elif sel:
            for idx in parse_index_ranges(sel):
                if 1 <= idx <= len(all_groups):
                    selected_groups.append(all_groups[idx-1])

    if not selected_groups:
        selected_groups = [None]

    all_drafts = []

    for idx, grp in enumerate(selected_groups, 1):
        grp_label = grp.alias or grp.name if grp else "通用版"
        draft_lines = _generate_draft_for_group(car, grp, db)
        all_drafts.append((grp_label, grp, draft_lines))

        print(color("\n" + "═" * 60, "bold", "cyan"))
        print(color(f"  {idx}. 📝 {grp_label} 版本文案", "bold", "cyan"))
        print(color("═" * 60, "bold", "cyan"))
        for line in draft_lines:
            print(line)
        print()

        if grp:
            full_text = "\n".join(draft_lines)
            if prompt_bool(f"  📋 将「{grp_label}」文案复制到剪贴板？", True):
                try:
                    if os.name == "nt":
                        import subprocess
                        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
                        p.communicate(full_text.encode("utf-16-le"))
                        print(color(f"    ✓ 已复制「{grp_label}」文案", "green"))
                except Exception:
                    pass

    if len(all_drafts) > 1:
        if prompt_bool("\n  📤 将所有群的文案合并导出到文件？", True):
            from datetime import datetime as dt
            out_lines = []
            for label, grp, lines in all_drafts:
                out_lines.append(f"{'='*60}")
                out_lines.append(f"【{label}】")
                out_lines.append(f"{'='*60}")
                out_lines.extend(lines)
                out_lines.append("")

            out_path = f"draft_{car.id}_{dt.now().strftime('%Y%m%d_%H%M')}.txt"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(out_lines))
            print(color(f"  ✓ 已导出到: {out_path}", "green"))

            if prompt_bool("  📋 同时复制所有文案到剪贴板？", False):
                try:
                    if os.name == "nt":
                        import subprocess
                        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
                        p.communicate(("\n".join(out_lines)).encode("utf-16-le"))
                        print(color("    ✓ 全部文案已复制", "green"))
                except Exception:
                    pass

    print(color("\n" + "─" * 60, "dim"))
    print(color("  🗂️ 车头私聊登记提示", "bold", "yellow"))
    print(color("─" * 60, "dim"))

    weekday = ["一", "二", "三", "四", "五", "六", "日"][car.start_time.weekday()]
    time_str = car.start_time.strftime(f"%m月%d日 周{weekday} %H:%M")
    end_time = car.start_time + timedelta(hours=car.duration_hours)
    end_str = end_time.strftime("%H:%M")
    exp_str = f"≥{car.min_experience}个硬核本经验" if car.min_experience > 0 else "无门槛（萌新友好）"
    loc_str = f"{car.city}·{car.shop}" if car.city else car.shop
    regs = get_registrations_by_car(db, car.id)
    approved_count = len([r for r in regs if r.status == "approved"])
    pending_count = len([r for r in regs if r.status == "pending"])

    grp_display = "-"
    if car.target_group:
        grp = get_group(db, car.target_group)
        if grp:
            grp_display = grp.alias or grp.name

    print(f"\n车: {car.name}  ID: {car.id}  群: {grp_display}")
    print(f"时: {time_str}～{end_str}  地: {loc_str}")
    print(f"配: {car.total_players}人 {car.role_constraints or ''}  门: {exp_str}")
    if car.require_unread:
        print("要: 未读本")
    print()
    print("报名登记模板：")
    print(f"  add {car.id} -g <来源群>")
    print(f"  → 昵称 / 性别 / 可到 / 已读本? / 备注 / 经验 / 反串")
    if approved_count > 0:
        print(f"\n当前状态: {approved_count}已确认 / {pending_count}待审 / {car.total_players - approved_count}空位")
    print()


def cmd_export(db, args):
    if not args:
        print(color("! 用法：export <车辆ID> [格式] [范围]", "red"))
        print(color("  格式: all(默认) / notice(群公告) / check(审核表) / shop(店铺表)", "dim"))
        print(color("  范围: approved(仅已确认) / bench(已确认+替补)", "dim"))
        print(color("  示例: export ab12 notice approved", "dim"))
        return

    car_id = args[0]
    fmt = "all"
    scope = "bench"  # 默认已确认+替补

    for a in args[1:]:
        al = a.lower()
        if al in ("notice", "check", "shop", "all"):
            fmt = al
        elif al == "approved":
            scope = "approved"
        elif al in ("bench", "all"):
            scope = "bench"

    car = _get_car_or_error(db, car_id)
    if not car:
        return

    regs = get_registrations_by_car(db, car.id)
    approved_regs = [r for r in regs if r.status == "approved"]
    benched_regs = [r for r in regs if r.status == "bench"]
    pending_regs = [r for r in regs if r.status == "pending"]

    approved_pairs = [(r, get_player(db, r.player_id)) for r in approved_regs]
    approved_pairs = [(r, p) for r, p in approved_pairs if p]
    benched_pairs = [(r, get_player(db, r.player_id)) for r in benched_regs]
    benched_pairs = [(r, p) for r, p in benched_pairs if p]

    # 根据 scope 决定包含范围
    if scope == "approved":
        included_pairs = approved_pairs
        included_bench = []
    else:
        included_pairs = approved_pairs
        included_bench = benched_pairs

    weekday = ["一", "二", "三", "四", "五", "六", "日"][car.start_time.weekday()]
    time_str = car.start_time.strftime(f"%Y年%m月%d日 周{weekday} %H:%M")
    end_time = car.start_time + timedelta(hours=car.duration_hours)
    end_str = end_time.strftime("%H:%M")
    loc_str = f"{car.city}·{car.shop}"
    exp_str = f"≥{car.min_experience}个硬核本经验" if car.min_experience > 0 else "无门槛（萌新友好）"

    all_text_parts = []

    # ============ 格式1: 群公告 (notice) ============
    if fmt in ("all", "notice"):
        print(color("\n" + "═" * 62, "bold", "cyan"))
        print(color("  📢 微信群公告", "bold", "cyan"))
        print(color("═" * 62, "bold", "cyan"))

        announcement = []
        announcement.append(f"【硬核组局公告】《{car.name}》")
        announcement.append("")
        announcement.append(f"📅 时间：{time_str} ～ 约{end_str}")
        announcement.append(f"📍 地点：{loc_str}")
        announcement.append(f"🎭 人数：{car.total_players}人（硬核推理）")
        if car.role_constraints:
            announcement.append(f"🎲 配置：{car.role_constraints}")
        if car.require_unread:
            announcement.append(f"📜 要求：全员未读本，严禁天眼 / 剧透")
        announcement.append(f"💪 门槛：{exp_str}")
        announcement.append("")

        if approved_pairs:
            announcement.append("✅ 已确认名单：")
            for i, (r, p) in enumerate(approved_pairs, 1):
                tag = ""
                cc = r.effective_accept_crosscast(p)
                if cc and (
                    (car.role_constraints and "男" in car.role_constraints and p.gender == "女") or
                    (car.role_constraints and "女" in car.role_constraints and p.gender == "男")
                ):
                    tag = "（反串）"
                gender_icon = "♂" if p.gender == "男" else "♀"
                exp_tag = f"[萌新]" if p.experience_count <= 0 else ""
                announcement.append(f"  {i}. {gender_icon} {p.nickname}{tag}{exp_tag}")
        else:
            announcement.append("⚠️ 尚未确认任何玩家入队！请先用 approve 确认。")

        if scope == "bench" and benched_pairs:
            announcement.append("")
            announcement.append("⏳ 替补名单：")
            for i, (r, p) in enumerate(benched_pairs, 1):
                announcement.append(f"  {i}. {p.nickname} ({p.gender}·{exp_display(p.experience_count)})  可到:{r.available_time}")

        if pending_regs:
            announcement.append("")
            announcement.append(f"🔍 待审核：{len(pending_regs)}人（车头私聊中）")

        announcement.append("")
        announcement.append("━" * 42)
        announcement.append("📌 【重要提醒】")
        announcement.append(f"  1. 💰 付款截止：请于 {car.start_time.strftime('%m月%d日 12:00')} 前付定金锁位")
        announcement.append("     （定金不退，可自行找人顶位）")
        announcement.append("  2. ⏰ 迟到处理：迟到15分钟以上请主动给大家买奶茶/小吃")
        announcement.append("     迟到超30分钟定金扣除，座位顺延给替补")
        announcement.append("  3. 🤫 禁剧透：结束前禁止在群内外透露任何剧情、手法、凶手")
        announcement.append("     违者永久拉黑！")
        announcement.append("  4. 🚫 跳车处理：开场前24小时内跳车，定金不退+群内公示")
        announcement.append("━" * 42)
        announcement.append("")
        announcement.append("📣 收到请回复【确认】，有事随时私车头！")
        announcement.append("祝大家盘得开心，凶手自投！🔥🎯")

        for line in announcement:
            print(line)
        all_text_parts.extend(announcement)

    # ============ 格式2: 车头审核表 (check) ============
    if fmt in ("all", "check"):
        print(color("\n" + "─" * 62, "dim"))
        print(color("  📋 车头审核表（内部用）", "bold", "yellow"))
        print(color("─" * 62, "dim"))

        print(color(f"\n{'#':<3}{'昵称':<12}{'性别':<4}{'经验':<8}{'反串':<4}{'可到':<12}{'来源群':<8}{'定金':<4}{'备注'}", "bold"))
        print("-" * 90)
        for i, (r, p) in enumerate(approved_pairs, 1):
            exp_s = exp_display(p.experience_count)
            cc_s = "✓" if r.effective_accept_crosscast(p) else "✗"
            note = r.notes[:15] if r.notes else ""
            if r.read_this_book:
                note = ("⚠已读本 " + note)[:15]
            # 长期标签中的风险信息
            risk = p.risk_tags()
            if risk:
                note = (note + " " + "⚠".join(risk))[:15]
            # 来源群
            grp_str = ""
            if r.source_group:
                grp = get_group(db, r.source_group)
                if grp:
                    grp_str = (grp.alias or grp.name)[:6]
            print(f"{i:<3}{p.nickname[:10]:<12}{p.gender:<4}{exp_s:<8}{cc_s:<4}"
                  f"{r.available_time[:10]:<12}{grp_str:<8}{'□':<4}{note}")

        if scope == "bench" and benched_pairs:
            print(color(f"\n── 替补席 ──", "blue", "bold"))
            for i, (r, p) in enumerate(benched_pairs, 1):
                risk_note = ""
                rt = p.risk_tags()
                if rt:
                    risk_note = f" ⚠{'⚠'.join(rt)}"
                print(f"  B{i}. {p.nickname} ({p.gender}·{exp_display(p.experience_count)})  "
                      f"可到:{r.available_time}  {r.notes or ''}{risk_note}")

        if pending_regs:
            print(color(f"\n── 待审核: {len(pending_regs)}人 ──", "yellow", "bold"))
            pending_pairs = [(r, get_player(db, r.player_id)) for r in pending_regs]
            for r, p in pending_pairs:
                if p:
                    risk_note = ""
                    rt = p.risk_tags()
                    if rt:
                        risk_note = f" ⚠{'/⚠'.join(rt)}"
                    print(f"  ? {p.nickname} ({p.gender}·{exp_display(p.experience_count)})  "
                          f"可到:{r.available_time}{risk_note}")

        check_lines = []
        all_text_parts.append("")
        all_text_parts.extend(check_lines)

    # ============ 格式3: 店铺交接表 (shop) ============
    if fmt in ("all", "shop"):
        print(color("\n" + "─" * 62, "dim"))
        print(color("  🏪 店铺交接表（给店家看）", "bold", "green"))
        print(color("─" * 62, "dim"))

        print(f"\n  本名: 《{car.name}》")
        print(f"  时间: {time_str} ～ {end_str}")
        print(f"  地点: {loc_str}")
        print(f"  人数: {len(included_pairs)}人（满员{car.total_players}人）")
        print(f"  时长: 约{car.duration_hours:.0f}小时")
        if car.min_experience > 0:
            print(f"  门槛: ≥{car.min_experience}硬核本经验")
        else:
            print(f"  门槛: 无门槛（含萌新）")
        if car.require_unread:
            print(f"  要求: 全员未读本")
        print()
        print(color(f"  {'#':<3}{'昵称':<12}{'性别':<4}{'经验':<8}{'可到时间':<14}{'来源群':<8}{'备注'}", "bold"))
        print("  " + "-" * 64)
        for i, (r, p) in enumerate(included_pairs, 1):
            exp_s = exp_display(p.experience_count)
            note_parts = []
            if r.read_this_book:
                note_parts.append("已读本")
            if r.notes:
                note_parts.append(r.notes[:8])
            rt = p.risk_tags()
            if rt:
                note_parts.append("⚠" + "/".join(rt))
            note_str = " ".join(note_parts) if note_parts else ""
            # 来源群
            grp_str = ""
            if r.source_group:
                grp = get_group(db, r.source_group)
                if grp:
                    grp_str = (grp.alias or grp.name)[:6]
            print(f"  {i:<3}{p.nickname[:10]:<12}{p.gender:<4}{exp_s:<8}"
                  f"{r.available_time[:12]:<14}{grp_str:<8}{note_str}")

        if scope == "bench" and benched_pairs:
            print(f"\n  替补: {len(benched_pairs)}人")
            for i, (r, p) in enumerate(benched_pairs, 1):
                print(f"    B{i}. {p.nickname} ({p.gender}) 可到:{r.available_time}")

        print(f"\n  合计到场: {len(included_pairs)}人" +
              (f" + 替补: {len(included_bench)}人" if included_bench else ""))
        print(f"  预计散场: 约{end_str}")

    print()

    # 自动复制（仅群公告部分）
    if fmt in ("all", "notice") and all_text_parts:
        try:
            full_text = "\n".join(all_text_parts)
            if os.name == "nt":
                import subprocess
                p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
                p.communicate(full_text.encode("utf-16-le"))
                print(color("ℹ️ 群公告已复制到剪贴板，Ctrl+V 粘到群里即可！", "green"))
        except Exception:
            pass


def cmd_help(db, args):
    print(HELP)


COMMANDS = {
    "new": cmd_new, "create": cmd_new,
    "copy": cmd_copy, "cp": cmd_copy,
    "add": cmd_add, "join": cmd_add,
    "view": cmd_view, "show": cmd_view,
    "export": cmd_export,
    "list": cmd_list, "ls": cmd_list,
    "draft": cmd_draft,
    "status": cmd_status,
    "approve": lambda db, args: cmd_approve(db, args),
    "confirm": lambda db, args: cmd_approve(db, args),
    "bench": lambda db, args: cmd_approve(db, args, bench=True),
    "sub": lambda db, args: cmd_approve(db, args, bench=True),
    "kick": lambda db, args: cmd_approve(db, args, kick=True),
    "remove": lambda db, args: cmd_approve(db, args, kick=True),
    "info": cmd_info, "detail": cmd_info,
    "del": cmd_del, "delete": cmd_del, "rm": cmd_del,
    "players": cmd_players,
    "tag": cmd_tag,
    "template": cmd_template, "tpl": cmd_template,
    "group": cmd_group, "grp": cmd_group,
    "help": cmd_help, "?": cmd_help, "h": cmd_help,
}


def repl():
    print(BANNER)
    print(color("输入 help 或 ? 查看命令列表，quit 退出", "dim"))
    db = load_db()

    while True:
        try:
            raw = input(color("\nHardcoreCar> ", "bold", "cyan")).strip()
        except (EOFError, KeyboardInterrupt):
            print(color("\n\n👋 下次组局见，祝盘得开心！", "bold"))
            break
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("quit", "exit", "q", "bye"):
            print(color("👋 保存完毕，下次组局见！", "bold"))
            break
        handler = COMMANDS.get(cmd)
        if not handler:
            print(color(f"! 未知命令：{cmd}，输入 help 查看命令列表", "red"))
            continue
        try:
            handler(db, args)
        except KeyboardInterrupt:
            print(color("\n⌨️ 已中断当前操作", "yellow"))
        except Exception as e:
            print(color(f"! 执行出错: {e}", "red"))
            import traceback
            traceback.print_exc()


def main():
    if len(sys.argv) > 1:
        db = load_db()
        cmd = sys.argv[1].lower()
        args = sys.argv[2:]
        if cmd in ("quit", "exit", "q"):
            return
        handler = COMMANDS.get(cmd)
        if handler:
            handler(db, args)
            return
        print(color(f"未知命令：{cmd}", "red"))
        print("不带参数启动以进入交互模式")
    else:
        repl()


if __name__ == "__main__":
    main()
