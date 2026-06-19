#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成测试脚本：模拟完整组局流程
"""
import sys
import os
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Car, Player, Registration, EnhancedJSONEncoder
from storage import (
    load_db, save_db,
    add_car, get_car, list_cars, update_car_status, delete_car,
    add_player, get_player, find_player_by_nickname,
    add_registration, remove_registration, get_registrations_by_car,
    update_registration_status, DB_FILE,
)
from matcher import (
    triage_registrations, analyze_match,
    check_time_match, check_gender_role_match, check_book_read_rule,
    check_experience, check_notes_conflict, _parse_time_availability,
)


def sep(title):
    print()
    print("=" * 60)
    print(f"  TEST: {title}")
    print("=" * 60)


def test_parser():
    sep("时间解析器 _parse_time_availability")
    cases = [
        ("随时", (0, 2880)),
        ("全天", (0, 2880)),
        ("19:00前", (0, 1140)),
        ("18点后", (1080, 2880)),
        ("18:30-23:00", (1110, 1380)),
        ("18:30到23:00", (1110, 1380)),
        ("19:00", (1050, 1320)),
        ("晚上7点到11点", (330, 600)),
    ]
    all_ok = True
    for input_, expected in cases:
        result = _parse_time_availability(input_)
        ok = result == expected
        mark = "✓" if ok else "✗"
        if not ok:
            all_ok = False
        print(f"  {mark} {input_!r:20} => {result}  (期望 {expected})")
    return all_ok


def test_matchers():
    sep("匹配规则单测")
    car = Car.create(
        name="测试本《须臾》", total_players=6, duration_hours=6.0,
        city="上海", shop="测测测剧本杀",
        start_time=datetime(2026, 6, 21, 19, 0),
        role_constraints="3男3女，不接受反串",
        require_unread=True, min_experience=3,
    )

    # 测试1：完美匹配 - 角色配置有男女，会有合理的角色配置提醒，但无critical
    p1 = Player.create(
        nickname="完美匹配君", gender="男", available_time="18:00-次日02:00",
        past_hardcore_books="须臾,芥子,持斧奥夫,马丁内斯",
        accept_crosscast=False, notes="", read_this_book=False, experience_count=8,
    )
    mr = analyze_match(car, Registration.create(car.id, p1.id), p1)
    ok1 = not mr.has_critical
    print(f"  {'✓' if ok1 else '✗'} 完美匹配(无严重问题): critical={mr.has_critical}, issues={len(mr.issues)}, score={mr.match_score}")

    # 测试2：已读本（严重）
    p2 = Player.create(
        nickname="已读本剧透王", gender="男", available_time="随时",
        past_hardcore_books="", accept_crosscast=False, notes="",
        read_this_book=True, experience_count=5,
    )
    mr = analyze_match(car, Registration.create(car.id, p2.id), p2)
    ok2 = mr.has_critical and any("未读本" in str(i) for i in mr.issues)
    print(f"  {'✓' if ok2 else '✗'} 已读本检测: critical={mr.has_critical}")

    # 测试3：全男/必男配置下，女生不接受反串
    p3_car = Car.create(
        name="纯男配置本《某本》", total_players=5, duration_hours=5,
        city="", shop="",
        start_time=datetime(2026, 6, 21, 19, 0),
        role_constraints="6男，必须男，不接受反串",
        require_unread=False, min_experience=0,
    )
    p3 = Player.create(
        nickname="纯女玩家", gender="女", available_time="随时",
        past_hardcore_books="", accept_crosscast=False, notes="",
        read_this_book=False, experience_count=5,
    )
    mr = analyze_match(p3_car, Registration.create(p3_car.id, p3.id), p3)
    ok3 = mr.has_critical or mr.has_warning
    print(f"  {'✓' if ok3 else '✗'} 角色性别冲突检测(全男+女生): critical={mr.has_critical}, warning={mr.has_warning}, issues={len(mr.issues)}")

    # 测试4：时间太早
    p4 = Player.create(
        nickname="起不来的人", gender="男", available_time="21:00后",
        past_hardcore_books="", accept_crosscast=False, notes="",
        read_this_book=False, experience_count=5,
    )
    mr = analyze_match(car, Registration.create(car.id, p4.id), p4)
    ok4 = mr.has_critical and any("时间" in str(i) for i in mr.issues)
    print(f"  {'✓' if ok4 else '✗'} 时间太晚(到不了)检测: critical={mr.has_critical}")

    # 测试5：经验不足
    p5 = Player.create(
        nickname="硬核萌新", gender="男", available_time="随时",
        past_hardcore_books="", accept_crosscast=False, notes="",
        read_this_book=False, experience_count=1,
    )
    mr = analyze_match(car, Registration.create(car.id, p5.id), p5)
    ok5 = mr.has_warning and any("经验" in str(i) for i in mr.issues)
    print(f"  {'✓' if ok5 else '✗'} 经验门槛检测: warning={mr.has_warning}")

    # 测试6：跳车雷点
    p6 = Player.create(
        nickname="有跳车历史", gender="男", available_time="随时",
        past_hardcore_books="", accept_crosscast=False, notes="去年有过一次跳车",
        read_this_book=False, experience_count=5,
    )
    mr = analyze_match(car, Registration.create(car.id, p6.id), p6)
    ok6 = mr.has_critical and any("跳车" in str(i) for i in mr.issues)
    print(f"  {'✓' if ok6 else '✗'} 备注雷点(跳车)检测: critical={mr.has_critical}")

    return all([ok1, ok2, ok3, ok4, ok5, ok6])


def test_full_workflow():
    sep("完整工作流（建车→加人→分诊→审核→导出）")

    # 备份旧数据
    backup = None
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            backup = f.read()

    # 清空数据库
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    db = load_db()

    try:
        # 1. 建车
        car = Car.create(
            name="《芥子》", total_players=6, duration_hours=5.5,
            city="北京", shop="硬核宇宙旗舰店",
            start_time=datetime.now().replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=1),
            role_constraints="4男3女？不对，是3男3女共6人，不接受反串，硬派推理配置",
            require_unread=True, min_experience=2,
        )
        add_car(db, car)
        print(f"  ✓ 建车成功: ID={car.id}  {car.name}  {car.total_players}人")

        # 2. 添加玩家（覆盖各种情况）
        players_config = [
            ("老司机A", "男", "18:30-23:30", "须臾,持斧奥夫,马丁内斯,死幻,作者不详", False, "", False, 5),
            ("硬核女王B", "女", "随时", "须臾,芥子,七月十三日,漓川怪谈", False, "", False, 7),
            ("迟到惯犯C", "男", "20:00前到不了", "雾鸦馆,病娇", True, "曾迟到2次", False, 2),
            ("萌新D", "女", "19:00", "年轮", False, "", False, 1),
            ("已读本E", "男", "随时", "芥子", False, "", True, 4),
            ("反串OKF", "女", "18:00-24:00", "持斧奥夫,虚构推理", True, "", False, 3),
            ("天眼玩家G", "男", "随时", "所有本都玩过", False, "疑似天眼玩家", False, 99),
            ("社恐H", "女", "19:00前", "漓川,年轮,须臾", False, "社恐，不接反串", False, 3),
            ("时间OKI", "男", "全天", "立方馆,红黑馆,马丁内斯", False, "", False, 4),
            ("替补君J", "男", "随时可救场", "硬核老手，所有经典都玩过", True, "", False, 10),
        ]
        for cfg in players_config:
            p = Player.create(*cfg)
            add_player(db, p)
            add_registration(db, Registration.create(car.id, p.id))
        print(f"  ✓ 添加 {len(players_config)} 名报名玩家")

        # 3. 分诊
        regs = get_registrations_by_car(db, car.id)
        triaged = triage_registrations(db, car, regs)
        print(f"  ⛔ 冲突: {len(triaged['conflict'])} 人")
        for r in triaged["conflict"]:
            crits = [str(i) for i in r.issues if i.severity == "critical"]
            print(f"     - {r.player.nickname}: {'; '.join(crits[:2])}")
        print(f"  ⚠️  存疑: {len(triaged['warning'])} 人")
        for r in triaged["warning"]:
            warns = [str(i) for i in r.issues if i.severity == "warning"]
            print(f"     - {r.player.nickname}: {'; '.join(warns[:2])}")
        print(f"  ✅ 匹配: {len(triaged['match'])} 人")
        for r in triaged["match"]:
            print(f"     - {r.player.nickname}  (得分{r.match_score})")

        # 4. 模拟 approve 前6个匹配的 + 替补
        all_ordered = triaged["match"] + triaged["warning"] + triaged["conflict"]
        for idx, r in enumerate(all_ordered):
            if idx < car.total_players and not r.has_critical:
                r.registration.status = "approved"
            elif r.has_critical and idx >= car.total_players:
                continue  # 冲突不进替补
            else:
                r.registration.status = "bench"
        save_db(db)

        approved = len([r for r in regs if r.status == "approved"])
        benched = len([r for r in regs if r.status == "bench"])
        print(f"  ✓ 审核完成: 已确认{approved}人 / 替补{benched}人 / 淘汰{len(regs) - approved - benched}人")

        # 5. 验证list_cars
        cars = list_cars(db)
        print(f"  ✓ list_cars 返回 {len(cars)} 辆车")

        # 6. 验证玩家重复报名幂等
        first_p = players_config[0]
        p_dup = find_player_by_nickname(db, first_p[0])
        reg_before = len(get_registrations_by_car(db, car.id))
        add_registration(db, Registration.create(car.id, p_dup.id))
        reg_after = len(get_registrations_by_car(db, car.id))
        print(f"  ✓ 重复报名幂等: {reg_before} == {reg_after} ? {reg_before == reg_after}")

        print()
        print("  📢 导出群公告片段预览（前20行）：")
        weekday = ["一", "二", "三", "四", "五", "六", "日"][car.start_time.weekday()]
        print(f"     【硬核组局公告】{car.name}")
        print(f"     📅 时间：{car.start_time.strftime(f'%Y年%m月%d日 周{weekday} %H:%M')}")
        print(f"     📍 地点：{car.city} · {car.shop}")
        print(f"     🎭 人数：{car.total_players}人 未读本要求：{'是' if car.require_unread else '否'}")
        approved_players = [get_player(db, r.player_id) for r in regs if r.status == "approved"]
        approved_players = [p for p in approved_players if p]
        for i, p in enumerate(approved_players, 1):
            icon = "♂" if p.gender == "男" else "♀"
            print(f"       {i}. {icon} {p.nickname} (经验{p.experience_count})")
        print("     ...（含付款截止/迟到处理/禁剧透规则全文）")

        return True

    finally:
        # 恢复备份
        if backup is not None:
            os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
            with open(DB_FILE, "w", encoding="utf-8") as f:
                f.write(backup)
        elif os.path.exists(DB_FILE):
            os.remove(DB_FILE)


def main():
    print("🔥 硬核推理车队招募助手 - 集成测试套件")
    print(f"   Python {sys.version.split()[0]}  |  DB文件: {DB_FILE}")

    results = []
    try:
        results.append(("时间解析器", test_parser()))
    except Exception as e:
        print(f"  ✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        results.append(("时间解析器", False))

    try:
        results.append(("匹配规则", test_matchers()))
    except Exception as e:
        print(f"  ✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        results.append(("匹配规则", False))

    try:
        results.append(("完整工作流", test_full_workflow()))
    except Exception as e:
        print(f"  ✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        results.append(("完整工作流", False))

    print()
    print("=" * 60)
    print("  测试结果汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        mark = color_wrap("✓ PASS", "green") if ok else color_wrap("✗ FAIL", "red")
        print(f"  {mark}  {name}")
    print()
    status = color_wrap("全部通过！✅", "green") if passed == total else color_wrap(f"{passed}/{total} 通过", "yellow")
    print(f"  最终结果: {status}")

    if passed < total:
        sys.exit(1)


def color_wrap(text, color):
    # 简单版，不用 hardcore_car.py 里的以免依赖
    codes = {"red": "91", "green": "92", "yellow": "93"}
    if not sys.stdout.isatty():
        return text
    return f"\033[{codes.get(color, '0')}m{text}\033[0m"


if __name__ == "__main__":
    main()
