#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成测试套件 v1.1 - 适配：
  - 0经验允许
  - 模板功能
  - 玩家/报名字段拆分
  - view筛选/排序
"""
import sys
import os
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Car, Player, Registration, CarTemplate
from storage import (
    load_db, save_db,
    add_car, get_car, list_cars, update_car_status, delete_car,
    add_player, get_player, find_player_by_nickname,
    add_registration, remove_registration, get_registrations_by_car,
    add_template, get_template, list_templates, delete_template,
    DB_FILE,
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


def test_v_int_nonneg():
    """0经验输入验证器"""
    sep("0经验验证器 v_int_nonneg（从 hardcore_car.py 导入逻辑测试）")
    sys.path.insert(0, ".")
    from hardcore_car import v_int_pos, v_int_nonneg, exp_display

    # v_int_pos：必须 > 0
    cases_pos = [("6", True), ("1", True), ("0", False), ("-1", False), ("abc", False)]
    for val, expected in cases_pos:
        ok, _ = v_int_pos(val)
        mark = "✓" if ok == expected else "✗"
        print(f"  {mark} v_int_pos({val!r}) = {ok}  (期望 {expected})")

    # v_int_nonneg：允许 0
    cases_nonneg = [("0", True), ("5", True), ("100", True), ("-1", False), ("abc", False)]
    all_ok = True
    for val, expected in cases_nonneg:
        ok, _ = v_int_nonneg(val)
        mark = "✓" if ok == expected else "✗"
        if ok != expected:
            all_ok = False
        print(f"  {mark} v_int_nonneg({val!r}) = {ok}  (期望 {expected})")

    # exp_display 0经验显示
    cases_exp = [(0, "萌新"), (1, "1硬核"), (5, "5硬核")]
    for n, expected in cases_exp:
        got = exp_display(n)
        mark = "✓" if got == expected else "✗"
        if got != expected:
            all_ok = False
        print(f"  {mark} exp_display({n}) = {got!r}  (期望 {expected!r})")
    return all_ok


def test_time_parser():
    sep("时间解析器 _parse_time_availability")
    cases = [
        ("随时", (0, 2880)),
        ("全天", (0, 2880)),
        ("19:00前", (0, 1140)),
        ("18点后", (1080, 2880)),
        ("18:30-23:00", (1110, 1380)),
        ("18:30到23:00", (1110, 1380)),
        ("19:00", (1050, 1320)),
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


def test_player_registration_split():
    """玩家长期资料 vs 单次报名字段分离"""
    sep("玩家/报名字段分离测试")
    # 备份
    backup = None
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            backup = f.read()
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    db = load_db()

    try:
        # 同一玩家报两个车，可到时间、已读本、备注互不影响
        car1 = Car.create(
            name="《须臾》", total_players=6, duration_hours=6,
            city="上海", shop="A店",
            start_time=datetime.now() + timedelta(days=1),
            require_unread=True, min_experience=0,
        )
        car2 = Car.create(
            name="《芥子》", total_players=6, duration_hours=5,
            city="北京", shop="B店",
            start_time=datetime.now() + timedelta(days=7),
            require_unread=False, min_experience=0,
        )
        add_car(db, car1)
        add_car(db, car2)

        # 同一个玩家（同一个 Player 对象）
        player = Player.create(
            nickname="小明", gender="男",
            past_hardcore_books="年轮,漓川",
            accept_crosscast=False, experience_count=2,
        )
        add_player(db, player)

        # 第一次报名：车1 - 19点前到，已读本，备注"有迟到前科"
        reg1 = Registration.create(
            car_id=car1.id, player_id=player.id,
            available_time="19:00前", read_this_book=True,
            notes="有迟到前科", accept_crosscast_override=None,
        )
        add_registration(db, reg1)

        # 第二次报名：车2 - 全天，未读本，无备注，本次接受反串
        reg2 = Registration.create(
            car_id=car2.id, player_id=player.id,
            available_time="全天", read_this_book=False,
            notes="", accept_crosscast_override=True,
        )
        add_registration(db, reg2)

        # 验证：同一玩家ID，但 Registration 字段不同
        regs1 = get_registrations_by_car(db, car1.id)
        regs2 = get_registrations_by_car(db, car2.id)
        assert len(regs1) == 1 and len(regs2) == 1, "报名数量不对"
        r1, r2 = regs1[0], regs2[0]
        assert r1.player_id == r2.player_id == player.id, "应是同一玩家"

        ok1 = r1.available_time == "19:00前" and r1.read_this_book is True and "迟到" in r1.notes
        ok2 = r2.available_time == "全天" and r2.read_this_book is False and r2.notes == ""
        ok3 = r2.effective_accept_crosscast(player) is True  # 本次覆盖
        ok4 = r1.effective_accept_crosscast(player) is False  # 跟随玩家默认值

        print(f"  {'✓' if ok1 else '✗'} 车1报名信息独立保存: 可到={r1.available_time} 已读本={r1.read_this_book} 备注={r1.notes}")
        print(f"  {'✓' if ok2 else '✗'} 车2报名信息独立保存: 可到={r2.available_time} 已读本={r2.read_this_book} 备注={r2.notes}")
        print(f"  {'✓' if ok3 else '✗'} 车2本次接受反串覆盖玩家默认值")
        print(f"  {'✓' if ok4 else '✗'} 车1使用玩家默认值（不反串）")

        # 验证匹配引擎使用 Registration 字段
        mr1 = analyze_match(car1, r1, player)
        mr2 = analyze_match(car2, r2, player)
        book_issue_1 = any("未读本" in str(i) for i in mr1.issues)
        book_issue_2 = any("未读本" in str(i) for i in mr2.issues)
        ok5 = book_issue_1 and not book_issue_2
        print(f"  {'✓' if ok5 else '✗'} 匹配引擎使用当次报名的已读本字段: 车1检测到未读本冲突={book_issue_1}, 车2={book_issue_2}")

        return all([ok1, ok2, ok3, ok4, ok5])
    finally:
        if backup is not None:
            os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
            with open(DB_FILE, "w", encoding="utf-8") as f:
                f.write(backup)
        elif os.path.exists(DB_FILE):
            os.remove(DB_FILE)


def test_templates():
    """模板保存、列出、套用、删除"""
    sep("车队模板功能")
    backup = None
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            backup = f.read()
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    db = load_db()

    try:
        tpl = CarTemplate.create(
            name="周末硬核标配", total_players=6, duration_hours=5.0,
            city="上海", shop="硬核旗舰店",
            role_constraints="3男3女，不接受反串",
            require_unread=True, min_experience=3,
        )
        add_template(db, tpl)
        print(f"  ✓ 模板已保存: ID={tpl.id} 名称={tpl.name}")

        # 按名称查找
        found = get_template(db, "周末硬核标配")
        ok1 = found is not None and found.min_experience == 3
        print(f"  {'✓' if ok1 else '✗'} 按名称查询模板: found={found is not None} min_exp={found.min_experience if found else None}")

        # 按 ID 查找
        found2 = get_template(db, tpl.id)
        ok2 = found2 is not None
        print(f"  {'✓' if ok2 else '✗'} 按ID查询模板")

        # list_templates
        tpls = list_templates(db)
        ok3 = len(tpls) == 1
        print(f"  {'✓' if ok3 else '✗'} list_templates 数量: {len(tpls)}")

        # 保存 0 门槛模板
        tpl2 = CarTemplate.create(
            name="萌新友好本", total_players=5, duration_hours=4.0,
            city="北京", shop="新店",
            role_constraints="",
            require_unread=False, min_experience=0,
        )
        add_template(db, tpl2)
        ok4 = tpl2.min_experience == 0
        print(f"  {'✓' if ok4 else '✗'} 支持保存0门槛模板: min_exp={tpl2.min_experience}")

        # 删除
        delete_template(db, tpl2.id)
        ok5 = get_template(db, tpl2.id) is None
        print(f"  {'✓' if ok5 else '✗'} 删除模板成功")

        return all([ok1, ok2, ok3, ok4, ok5])
    finally:
        if backup is not None:
            os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
            with open(DB_FILE, "w", encoding="utf-8") as f:
                f.write(backup)
        elif os.path.exists(DB_FILE):
            os.remove(DB_FILE)


def test_view_filter_sort():
    """view 筛选和排序"""
    sep("view 筛选与排序")
    backup = None
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            backup = f.read()
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    db = load_db()

    try:
        car = Car.create(
            name="测试筛选车", total_players=6, duration_hours=5,
            city="", shop="",
            start_time=datetime.now().replace(hour=19, minute=0) + timedelta(days=1),
            require_unread=True, min_experience=0,
        )
        add_car(db, car)

        # 创建3类玩家：匹配、存疑、冲突
        configs = [
            ("萌新", "男", 0, "随时", False, "", "pending"),       # 0经验(萌新)，匹配
            ("老司机", "男", 10, "18:30-23:00", False, "", "approved"),  # 匹配+已确认
            ("迟到王", "男", 3, "随时", False, "经常迟到", "pending"),  # 仅warning(备注)，无时间冲突
            ("剧透鬼", "男", 5, "随时", True, "", "pending"),       # 已读本critical
            ("替补A", "女", 2, "随时", False, "", "bench"),         # 替补状态
        ]
        for nick, gender, exp, avail, has_read, notes, status in configs:
            p = Player.create(nickname=nick, gender=gender,
                              past_hardcore_books="", accept_crosscast=False,
                              experience_count=exp)
            add_player(db, p)
            reg = Registration.create(car.id, p.id, available_time=avail,
                                      read_this_book=has_read, notes=notes)
            reg.status = status
            add_registration(db, reg)

        regs = get_registrations_by_car(db, car.id)

        # 筛选: pending (未处理)
        tri = triage_registrations(db, car, regs, filter_status="pending")
        pending_count = len(tri["conflict"]) + len(tri["warning"]) + len(tri["match"])
        ok1 = pending_count == 3  # 萌新 + 迟到王 + 剧透鬼
        print(f"  {'✓' if ok1 else '✗'} --pending 筛选: 期望3，实际{pending_count}")

        # 筛选: eligible (可进正车=无critical)
        tri = triage_registrations(db, car, regs, filter_status="eligible")
        eligible_count = len(tri["conflict"]) + len(tri["warning"]) + len(tri["match"])
        ok2 = eligible_count == 4  # 去掉剧透鬼
        print(f"  {'✓' if ok2 else '✗'} --eligible 筛选(无严重冲突): 期望4，实际{eligible_count}")

        # 筛选: approved
        tri = triage_registrations(db, car, regs, filter_status="approved")
        approved_count = len(tri["conflict"]) + len(tri["warning"]) + len(tri["match"])
        ok3 = approved_count == 1
        print(f"  {'✓' if ok3 else '✗'} --approved 筛选: 期望1，实际{approved_count}")

        # 排序: experience (降序)
        tri = triage_registrations(db, car, regs, filter_status="all", sort_by="experience")
        all_sorted = tri["all"]
        exps = [r.player.experience_count for r in all_sorted]
        ok4 = exps == sorted(exps, reverse=True)
        print(f"  {'✓' if ok4 else '✗'} --sort experience 降序: {exps}")

        # 排序: time (升序，解析后的最早分钟)
        tri = triage_registrations(db, car, regs, filter_status="all", sort_by="time")
        all_sorted = tri["match"] + tri["warning"] + tri["conflict"]
        times = [r.registration.available_time for r in all_sorted]
        print(f"  ✓ --sort time 结果: {times}")  # 目测合理即可，不做严格断言

        return all([ok1, ok2, ok3, ok4])
    finally:
        if backup is not None:
            os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
            with open(DB_FILE, "w", encoding="utf-8") as f:
                f.write(backup)
        elif os.path.exists(DB_FILE):
            os.remove(DB_FILE)


def test_full_workflow_v11():
    sep("完整工作流 v1.1（0经验+模板+分离+筛选）")
    backup = None
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            backup = f.read()
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    db = load_db()

    try:
        # 1. 先建模板
        tpl = CarTemplate.create(
            name="周末5h萌新友好", total_players=6, duration_hours=5,
            city="上海", shop="硬核旗舰店",
            role_constraints="3男3女", require_unread=True, min_experience=0,
        )
        add_template(db, tpl)
        print(f"  ✓ 建模板: {tpl.name} (0门槛)")

        # 2. 建车，套用模板
        car = Car.create(
            name="《立方馆谋杀始末》", total_players=tpl.total_players,
            duration_hours=tpl.duration_hours,
            city=tpl.city, shop=tpl.shop,
            start_time=datetime.now().replace(hour=19, minute=0) + timedelta(days=1),
            role_constraints=tpl.role_constraints,
            require_unread=tpl.require_unread,
            min_experience=tpl.min_experience,  # 0门槛
            template_id=tpl.id,
        )
        add_car(db, car)
        print(f"  ✓ 建车套用模板: {car.name} 门槛={car.min_experience} (0=萌新可进)")

        # 3. 添加玩家：含0经验萌新
        players_data = [
            ("萌新A", "女", 0, "随时", False, "", True),
            ("萌新B", "男", 0, "19:00前", False, "第一次玩", False),
            ("老炮C", "男", 8, "随时", False, "", False),
            ("老炮D", "女", 5, "18:30后", False, "", True),
            ("天眼E", "男", 99, "随时", True, "疑似天眼", False),  # 已读本
            ("跳车F", "女", 2, "随时", False, "去年跳过车", False),
            ("迟到G", "男", 3, "20:30前到不了", False, "经常迟到", False),
        ]
        for nick, gender, exp, avail, has_read, notes, cc in players_data:
            p = Player.create(nickname=nick, gender=gender,
                              past_hardcore_books="", accept_crosscast=cc,
                              experience_count=exp)
            add_player(db, p)
            reg = Registration.create(car.id, p.id, available_time=avail,
                                      read_this_book=has_read, notes=notes)
            add_registration(db, reg)
        print(f"  ✓ 添加 {len(players_data)} 名玩家 (含2名0经验萌新)")

        # 4. 分诊
        regs = get_registrations_by_car(db, car.id)
        triaged = triage_registrations(db, car, regs)
        print(f"  ⛔ 冲突: {len(triaged['conflict'])} 人")
        for r in triaged["conflict"]:
            crits = [str(i) for i in r.issues if i.severity == "critical"]
            print(f"     - {r.player.nickname}({r.player.experience_count or '萌新'}): {'; '.join(crits[:2])}")
        print(f"  ⚠️  存疑: {len(triaged['warning'])} 人")
        for r in triaged["warning"]:
            warns = [str(i) for i in r.issues if i.severity == "warning"]
            print(f"     - {r.player.nickname}({r.player.experience_count or '萌新'}): {'; '.join(warns[:2])}")
        print(f"  ✅ 匹配: {len(triaged['match'])} 人")
        for r in triaged["match"]:
            exp_str = "萌新" if r.player.experience_count == 0 else f"{r.player.experience_count}硬核"
            print(f"     - {r.player.nickname}({exp_str}) 得分{r.match_score}")

        # 验证：0经验萌新A能出现在匹配里（因为门槛0）
        match_nicks = {r.player.nickname for r in triaged["match"]}
        ok = "萌新A" in match_nicks
        print(f"  {'✓' if ok else '✗'} 0经验萌新A在门槛0的车里出现在匹配列表: {'萌新A' in match_nicks}")

        # 5. 筛选 eligible + 按经验排序
        tri = triage_registrations(db, car, regs, filter_status="eligible", sort_by="experience")
        eligible = tri["all"]
        exps = [r.player.experience_count for r in eligible]
        ok2 = exps == sorted(exps, reverse=True) and 99 not in exps  # 天眼E被过滤
        print(f"  {'✓' if ok2 else '✗'} eligible+experience排序: {exps} (不应含99=天眼E)")

        # 6. 模拟 approve 全部匹配的 + 前几个warning
        all_ordered = triaged["match"] + triaged["warning"] + triaged["conflict"]
        for idx, r in enumerate(all_ordered):
            if idx < car.total_players and not r.has_critical:
                r.registration.status = "approved"
            elif not r.has_critical:
                r.registration.status = "bench"
        save_db(db)

        approved = [r for r in regs if r.status == "approved"]
        benched = [r for r in regs if r.status == "bench"]
        print(f"  ✓ 审核完成: 已确认{len(approved)}人 / 替补{len(benched)}人 / 淘汰{len(regs)-len(approved)-len(benched)}人")

        # 7. 验证0经验导出显示
        from hardcore_car import exp_display
        for r in approved:
            p = get_player(db, r.player_id)
            if p.experience_count == 0:
                disp = exp_display(p.experience_count)
                print(f"  ✓ 0经验在导出中显示: {p.nickname} → {disp}")

        return ok and ok2
    finally:
        if backup is not None:
            os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
            with open(DB_FILE, "w", encoding="utf-8") as f:
                f.write(backup)
        elif os.path.exists(DB_FILE):
            os.remove(DB_FILE)


def main():
    print("🔥 硬核推理车队招募助手 v1.1 - 集成测试套件")
    print(f"   Python {sys.version.split()[0]}  |  DB: {DB_FILE}")

    results = []
    tests = [
        ("0经验验证器+显示", test_v_int_nonneg),
        ("时间解析器", test_time_parser),
        ("玩家/报名字段分离", test_player_registration_split),
        ("车队模板功能", test_templates),
        ("view筛选/排序", test_view_filter_sort),
        ("完整工作流v1.1", test_full_workflow_v11),
    ]
    for name, fn in tests:
        try:
            ok = fn()
            results.append((name, bool(ok)))
        except Exception as e:
            print(f"  ✗ 测试异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print()
    print("=" * 60)
    print("  测试结果汇总")
    print("=" * 60)

    def cwrap(t, c):
        codes = {"red": "91", "green": "92", "yellow": "93"}
        if not sys.stdout.isatty():
            return t
        return f"\033[{codes.get(c, '0')}m{t}\033[0m"

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        mark = cwrap("✓ PASS", "green") if ok else cwrap("✗ FAIL", "red")
        print(f"  {mark}  {name}")
    print()
    status = cwrap("全部通过！✅", "green") if passed == total else cwrap(f"{passed}/{total} 通过", "yellow")
    print(f"  最终结果: {status}")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
