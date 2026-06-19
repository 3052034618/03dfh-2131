#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬核推理车队招募助手 - Hardcore Car Manager
面向资深车头的极简命令行工具
"""

import sys
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from models import Car, Player, Registration
from storage import (
    load_db, save_db,
    add_car, get_car, list_cars, update_car_status, delete_car,
    add_player, get_player, find_player_by_nickname,
    add_registration, remove_registration, get_registrations_by_car,
    update_registration_status,
)
from matcher import triage_registrations, MatchResult


BANNER = r"""
╔══════════════════════════════════════════╗
║  🔥 硬核推理车队招募助手 v1.0 🔥         ║
║  Hardcore Detective Car Manager         ║
║  为资深车头 · 极简高效组局              ║
╚══════════════════════════════════════════╝
"""

HELP = """
命令列表：
  new [car_id]        开新车 / 创建新剧本杀局（交互式输入）
  add <car_id>        为指定车添加报名玩家（交互式录入）
  view <car_id>       查看该车报名三段式分析（冲突 / 不符 / 匹配）
  export <car_id>     导出微信群公告 + 确认名单（剪贴板格式）
  list                列出所有车辆
  status <car_id> <open|full|done|cancel>
                      修改车辆状态
  approve <car_id> <index> [more...]
                      将 view 显示的序号标记为确认入队
  bench <car_id> <index> [more...]
                      将序号标记为替补
  kick <car_id> <index> [more...]
                      从报名中移除指定玩家
  info <car_id>       查看车辆详细信息
  del <car_id>        删除车辆（连同其报名记录）
  help / ?            显示此帮助
  quit / exit / q     退出程序

使用示例：
  > new
  （按提示填写本名、人数等信息）
  > add ab12cd34
  （按提示填写玩家昵称、性别等）
  > view ab12cd34
  （看到三段列表，根据序号做 approve/bench/kick）
  > export ab12cd34
  （直接复制输出的群公告内容即可）
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
            ok, err = validator(val)
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


def v_int(text):
    try:
        n = int(text)
        if n > 0:
            return True, ""
        return False, "必须是正整数"
    except ValueError:
        return False, "请输入有效整数"


def v_float(text):
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


def cmd_new(db, _):
    print(color("\n=== 开新车 / 新建组局 ===", "bold", "cyan"))
    print("请依次填写以下信息（留空使用默认值）\n")
    name = prompt("本名 / 剧本名称", required=True)
    total_players = int(prompt("玩家总人数", default=6, validator=v_int))
    duration_hours = float(prompt("预计时长（小时）", default=5.0, validator=v_float))
    city = prompt("城市", required=True)
    shop = prompt("店铺名称", required=True)

    start_dt = None
    while start_dt is None:
        raw = prompt("开车时间", default=datetime.now().strftime("%Y-%m-%d 19:00"))
        ok, result = v_datetime(raw)
        if ok:
            start_dt = result
        else:
            print(color(f"  ! {result}", "red"))

    role_constraints = prompt(
        "角色性别配置（如 3男3女/4男3女，或「必男1不接受反串」等详细描述）",
        default="", required=False
    )
    require_unread = prompt_bool("是否要求所有人未读本（防天眼/剧透）", default=True)
    min_exp = int(prompt("最低硬核本经验数量（0=无门槛）", default=0, validator=v_int))

    car = Car.create(
        name=name, total_players=total_players, duration_hours=duration_hours,
        city=city, shop=shop, start_time=start_dt,
        role_constraints=role_constraints, require_unread=require_unread,
        min_experience=min_exp,
    )
    add_car(db, car)

    print(color(f"\n✓ 车辆创建成功！", "green", "bold"))
    print(f"  车辆ID: {color(car.id, 'yellow', 'bold')}")
    print(f"  简称: {car.name} · {car.total_players}人 · {car.duration_hours}h")
    print(f"  时间: {car.start_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  地点: {car.city} · {car.shop}")
    if car.role_constraints:
        print(f"  配置: {car.role_constraints}")
    if car.require_unread:
        print(f"  要求: 未读本 ✓")
    if car.min_experience:
        print(f"  门槛: ≥{car.min_experience}个硬核本经验")
    print(color(f"\n  请牢记车辆ID，后续添加玩家用：add {car.id}", "dim"))
    return car


def _get_car_or_error(db, car_id):
    car = get_car(db, car_id)
    if not car:
        # 尝试按名称模糊匹配
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


def cmd_add(db, args):
    if not args:
        print(color("! 用法：add <车辆ID>", "red"))
        return
    car = _get_car_or_error(db, args[0])
    if not car:
        return
    print(color(f"\n=== 添加报名 · {car.name} ({car.id}) ===", "bold", "cyan"))
    print("按群友私聊信息录入，可随时 Ctrl+C 中止\n")

    nickname = prompt("玩家昵称", required=True)
    gender_raw = prompt("性别需求（男/女）", required=True, validator=v_gender)
    gender = "男" if gender_raw in ("男", "M", "m") else "女"
    avail_time = prompt(
        "可到时间（如 19:00前 / 18:30-23:00 / 全天 等）",
        default="随时", required=True
    )
    past_books = prompt(
        "过往玩过的硬核本（逗号分隔，如 须臾,芥子,持斧奥夫）",
        required=False
    )
    try:
        exp_count = int(prompt(
            "硬核本总数（根据上一项自动估算或手填）",
            default=len([x for x in re.split(r"[,，、\s]+", past_books) if x]) or 0,
            validator=v_int,
        ))
    except ValueError:
        exp_count = 0
    accept_cc = prompt_bool("是否接受反串", default=False)
    has_read = False
    if car.require_unread:
        has_read = prompt_bool(f"玩家是否已读本《{car.name}》（是则不满足未读本要求）", default=False)
    notes = prompt("备注雷点（迟到/跳车/挂机/杠精/天眼等，无则留空）", required=False)

    existing = find_player_by_nickname(db, nickname)
    if existing:
        print(color(f"\n? 已存在同名玩家：{existing.id} {existing.nickname}", "yellow"))
        if prompt_bool("  沿用已有资料？（否则新建）", default=True):
            player = existing
        else:
            player = Player.create(
                nickname=nickname, gender=gender, available_time=avail_time,
                past_hardcore_books=past_books, accept_crosscast=accept_cc,
                notes=notes, read_this_book=has_read, experience_count=exp_count,
            )
            add_player(db, player)
    else:
        player = Player.create(
            nickname=nickname, gender=gender, available_time=avail_time,
            past_hardcore_books=past_books, accept_crosscast=accept_cc,
            notes=notes, read_this_book=has_read, experience_count=exp_count,
        )
        add_player(db, player)

    reg = Registration.create(car.id, player.id)
    reg = add_registration(db, reg)
    print(color(f"\n✓ 报名登记成功！玩家ID: {player.id}", "green"))
    print(f"  {player.nickname} | {player.gender} | {player.available_time} "
          f"| 经验{player.experience_count} | {'接受反串' if player.accept_crosscast else '不反串'}")


def _gather_indexed_players(db, car, regs):
    """返回 (index_map, ordered_list)，其中 index_map[编号] = MatchResult"""
    triaged = triage_registrations(db, car, regs)
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
    if not args:
        print(color("! 用法：view <车辆ID>", "red"))
        return
    car = _get_car_or_error(db, args[0])
    if not car:
        return
    regs = get_registrations_by_car(db, car.id)
    if not regs:
        print(color(f"! 该车尚无报名记录，使用 add {car.id} 添加", "yellow"))
        return

    ordered, sections, triaged = _gather_indexed_players(db, car, regs)
    total = len(ordered)
    approved = [r for r in regs if r.status == "approved"]
    benched = [r for r in regs if r.status == "bench"]

    print(color(f"\n{'='*60}", "bold", "cyan"))
    print(color(f"🚗 {car.name}  报名分析报告  ({car.id})", "bold", "cyan"))
    print(color(f"{'='*60}", "bold", "cyan"))
    _print_car_header(car)
    print(f"  报名总数: {total}  |  已确认: {len(approved)}/{car.total_players}  |  替补: {len(benched)}")
    print()

    idx = 0
    for key, title, lst in sections:
        if not lst:
            continue
        color_tag = "red" if key == "conflict" else ("yellow" if key == "warning" else "green")
        print(color(f"── {title} ({len(lst)}人) ──", color_tag, "bold"))
        for r in lst:
            idx += 1
            status_tag = ""
            reg = r.registration
            if reg.status == "approved":
                status_tag = color(" [✔已确认]", "green")
            elif reg.status == "bench":
                status_tag = color(" [板凳]", "blue")
            print(f"{color(f'[{idx:>2}]', 'bold')} {r.player.nickname} "
                  f"({r.player.gender}·{r.player.experience_count}硬核)"
                  f"{status_tag}")
            extra_bits = []
            if r.player.accept_crosscast:
                extra_bits.append("反串OK")
            if r.player.available_time:
                extra_bits.append(f"可到:{r.player.available_time}")
            if extra_bits:
                print(f"     {color(' | '.join(extra_bits), 'dim')}")
            if r.issues:
                for iss in r.issues:
                    ic = "red" if iss.severity == "critical" else "yellow"
                    print(f"     {color('·', ic)} {color(str(iss), ic)}")
        print()

    print(color(f"提示：用 approve/bench/kick {car.id} 加上方编号处理报名", "dim"))
    print(color(f"      如：approve {car.id} 8 9 10 11   或   bench {car.id} 3", "dim"))


def _print_car_header(car):
    time_str = car.start_time.strftime("%Y-%m-%d %H:%M")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][car.start_time.weekday()]
    status_map = {"open": "招集中", "full": "已满", "done": "已结束", "cancel": "已取消"}
    st_color = {"open": "green", "full": "yellow", "done": "blue", "cancel": "red"}
    st = status_map.get(car.status, car.status)
    stc = st_color.get(car.status, "white")
    print(f"  🕒 {time_str} (周{weekday}) · 约{car.duration_hours}小时")
    print(f"  📍 {car.city} · {car.shop}")
    print(f"  👥 {car.total_players}人  "
          f"| 状态: {color(st, stc, 'bold')}  "
          f"| 未读本: {'✓' if car.require_unread else '✗'}  "
          f"| 门槛: ≥{car.min_experience}硬核本")
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
            reg.status = "bench"
            if reg in db.registrations:
                pass
            print(color(f"⏸ 设为替补: {mr.player.nickname}", "blue"))
        else:
            if approved_count >= car.total_players and reg.status != "approved":
                print(color(f"! 已达满员{car.total_players}人，{mr.player.nickname}自动设为替补", "yellow"))
                reg.status = "bench"
            else:
                reg.status = "approved"
                if reg.status == "approved":
                    approved_count += 1
                print(color(f"✓ 确认入队: {mr.player.nickname}", "green"))
    save_db(db)

    if approved_count >= car.total_players and car.status == "open" and not kick:
        if prompt_bool(f"  已确认{approved_count}人达到上限，是否将车辆标记为「已满」？", True):
            update_car_status(db, car.id, "full")


def cmd_list(db, _):
    cars = list_cars(db)
    if not cars:
        print(color("! 暂无车辆，使用 new 命令开新车", "yellow"))
        return
    print(color(f"\n{'ID':10} {'本名':12} {'人数':>4} {'时间':18} {'地点':10} {'状态':6} {'报名':>5}", "bold"))
    print("-" * 70)
    for c in cars:
        regs = get_registrations_by_car(db, c.id)
        approved = len([r for r in regs if r.status == "approved"])
        status_map = {"open": color("招集中", "green"), "full": color("已满", "yellow"),
                      "done": color("已结束", "blue"), "cancel": color("取消", "red")}
        st = status_map.get(c.status, c.status)
        time_str = c.start_time.strftime("%m-%d %H:%M")
        print(f"{c.id:10} {c.name[:12]:12} {approved}/{c.total_players:>3} "
              f"{time_str:18} {(c.city+'.'+c.shop)[:10]:10} {st:10} {len(regs):>3}")
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
    _print_car_header(car)
    print(f"  创建时间: {car.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    regs = get_registrations_by_car(db, car.id)
    if regs:
        print(f"\n  报名列表 ({len(regs)}):")
        for i, reg in enumerate(regs, 1):
            p = get_player(db, reg.player_id)
            if not p:
                continue
            status_map = {"pending": "待审核", "approved": color("✔已确认", "green"),
                          "bench": color("⏸替补", "blue"), "rejected": color("✗拒绝", "red")}
            st = status_map.get(reg.status, reg.status)
            print(f"    {i:>2}. {p.nickname} ({p.gender}·经验{p.experience_count}) · {st}")
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


def cmd_export(db, args):
    if not args:
        print(color("! 用法：export <车辆ID>", "red"))
        return
    car = _get_car_or_error(db, args[0])
    if not car:
        return
    regs = get_registrations_by_car(db, car.id)
    approved = [r for r in regs if r.status == "approved"]
    benched = [r for r in regs if r.status == "bench"]
    pending = [r for r in regs if r.status == "pending"]

    weekday = ["一", "二", "三", "四", "五", "六", "日"][car.start_time.weekday()]
    time_str = car.start_time.strftime(f"%Y年%m月%d日 周{weekday} %H:%M")

    end_time = car.start_time + timedelta(hours=car.duration_hours)
    end_str = end_time.strftime("%H:%M")

    players_approved = []
    for r in approved:
        p = get_player(db, r.player_id)
        if p:
            players_approved.append(p)

    players_benched = []
    for r in benched:
        p = get_player(db, r.player_id)
        if p:
            players_benched.append(p)

    # --- 群公告 ---
    print(color("\n" + "═" * 62, "bold", "cyan"))
    print(color("  📢 微信群公告（直接复制发送）", "bold", "cyan"))
    print(color("═" * 62, "bold", "cyan"))

    announcement = []
    announcement.append(f"【硬核组局公告】《{car.name}》")
    announcement.append("")
    announcement.append(f"📅 时间：{time_str} ～ 约{end_str}")
    announcement.append(f"📍 地点：{car.city} · {car.shop}")
    announcement.append(f"🎭 人数：{car.total_players}人（硬核推理）")
    if car.role_constraints:
        announcement.append(f"🎲 配置：{car.role_constraints}")
    if car.require_unread:
        announcement.append(f"📜 要求：全员未读本，严禁天眼 / 剧透")
    if car.min_experience:
        announcement.append(f"💪 门槛：需≥{car.min_experience}个硬核本经验")
    announcement.append("")

    if players_approved:
        announcement.append("✅ 已确认名单（按到场先后排序）：")
        for i, p in enumerate(players_approved, 1):
            tag = ""
            if p.accept_crosscast and (
                (car.role_constraints and "男" in car.role_constraints and p.gender == "女") or
                (car.role_constraints and "女" in car.role_constraints and p.gender == "男")
            ):
                tag = "（反串）"
            gender_icon = "♂" if p.gender == "男" else "♀"
            announcement.append(f"  {i}. {gender_icon} {p.nickname}{tag}")
    else:
        announcement.append(color("⚠️ 尚未确认任何玩家入队！请先用 approve 确认。", "yellow"))

    if players_benched:
        announcement.append("")
        announcement.append("⏳ 替补名单：")
        for i, p in enumerate(players_benched, 1):
            announcement.append(f"  {i}. {p.nickname} ({p.gender})")

    if pending:
        announcement.append("")
        announcement.append(f"🔍 待审核：{len(pending)}人（车头私聊中）")

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

    # --- 确认名单（表格，方便车头自己记录） ---
    print(color("\n" + "─" * 62, "dim"))
    print(color("  📋 车头确认清单（内部用）", "bold", "yellow"))
    print(color("─" * 62, "dim"))

    print(color(f"\n{'序号':<4}{'昵称':<14}{'性别':<4}{'经验':<6}{'反串':<4}{'定金':<4}{'备注'}", "bold"))
    print("-" * 60)
    for i, p in enumerate(players_approved, 1):
        exp_str = f"{p.experience_count}硬核"
        cc_str = "✓" if p.accept_crosscast else "✗"
        note = p.notes[:12] if p.notes else ""
        print(f"{i:<4}{p.nickname[:12]:<14}{p.gender:<4}{exp_str:<8}{cc_str:<4}{'□':<4}{note}")
    if players_benched:
        print(color(f"\n── 替补席 ──", "blue", "bold"))
        for i, p in enumerate(players_benched, 1):
            exp_str = f"{p.experience_count}硬核"
            print(f"  B{i}. {p.nickname} ({p.gender}·{exp_str}) 可到:{p.available_time}")

    print()
    # 导出到剪贴板（如果可用）
    try:
        full_text = "\n".join(announcement)
        if os.name == "nt":
            try:
                import subprocess
                p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
                p.communicate(full_text.encode("utf-16-le"))
                print(color("ℹ️ 公告已自动复制到系统剪贴板，直接 Ctrl+V 粘到群里即可！", "green"))
            except Exception as e:
                print(color(f"ℹ️ 自动复制失败（{e}），请手动选中上方公告复制", "dim"))
    except Exception:
        pass


def cmd_help(db, args):
    print(HELP)


COMMANDS = {
    "new": cmd_new, "create": cmd_new,
    "add": cmd_add, "join": cmd_add,
    "view": cmd_view, "show": cmd_view,
    "export": cmd_export,
    "list": cmd_list, "ls": cmd_list,
    "status": cmd_status,
    "approve": lambda db, args: cmd_approve(db, args),
    "confirm": lambda db, args: cmd_approve(db, args),
    "bench": lambda db, args: cmd_approve(db, args, bench=True),
    "sub": lambda db, args: cmd_approve(db, args, bench=True),
    "kick": lambda db, args: cmd_approve(db, args, kick=True),
    "remove": lambda db, args: cmd_approve(db, args, kick=True),
    "info": cmd_info, "detail": cmd_info,
    "del": cmd_del, "delete": cmd_del, "rm": cmd_del,
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
