#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成测试套件 v1.3 - 适配：
  - 0经验允许
  - 模板功能
  - 玩家/报名字段拆分
  - view筛选/排序
  - 玩家长期标签
  - 车队复制
  - 序号范围解析
  - 三种导出格式
  - 群管理（v1.3）
  - 来源群记录（v1.3）
  - 跨群重复报名检测（v1.3）
  - 多群 draft 生成（v1.3）
"""
import sys
import os
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Car, Player, Registration, CarTemplate, Group
from storage import (
    load_db, save_db,
    add_car, get_car, list_cars, update_car_status, delete_car,
    add_player, get_player, find_player_by_nickname,
    add_registration, remove_registration, get_registrations_by_car,
    add_template, get_template, list_templates, delete_template,
    add_player_tag, remove_player_tag, list_players_by_tag,
    add_group, get_group, list_groups, delete_group, get_default_group,
    DB_FILE,
)
from matcher import (
    triage_registrations, analyze_match,
    check_time_match, check_gender_role_match, check_book_read_rule,
    check_experience, check_notes_conflict, check_player_tags,
    check_double_booking,
    _parse_time_availability,
)


def sep(title):
    print()
    print("=" * 60)
    print(f"  TEST: {title}")
    print("=" * 60)


def _clean_db():
    backup = None
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            backup = f.read()
        os.remove(DB_FILE)
    return backup


def _restore_db(backup):
    if backup is not None:
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        with open(DB_FILE, "w", encoding="utf-8") as f:
            f.write(backup)
    elif os.path.exists(DB_FILE):
        os.remove(DB_FILE)


def test_v_int_nonneg():
    sep("0经验验证器 v_int_nonneg")
    from hardcore_car import v_int_pos, v_int_nonneg, exp_display

    cases_pos = [("6", True), ("1", True), ("0", False), ("-1", False), ("abc", False)]
    for val, expected in cases_pos:
        ok, _ = v_int_pos(val)
        mark = "✓" if ok == expected else "✗"
        print(f"  {mark} v_int_pos({val!r}) = {ok}  (期望 {expected})")

    cases_nonneg = [("0", True), ("5", True), ("100", True), ("-1", False), ("abc", False)]
    all_ok = True
    for val, expected in cases_nonneg:
        ok, _ = v_int_nonneg(val)
        mark = "✓" if ok == expected else "✗"
        if ok != expected:
            all_ok = False
        print(f"  {mark} v_int_nonneg({val!r}) = {ok}  (期望 {expected})")

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
    sep("玩家/报名字段分离测试")
    backup = _clean_db()
    db = load_db()
    try:
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

        player = Player.create(
            nickname="小明", gender="男",
            past_hardcore_books="年轮,漓川",
            accept_crosscast=False, experience_count=2,
        )
        add_player(db, player)

        reg1 = Registration.create(
            car_id=car1.id, player_id=player.id,
            available_time="19:00前", read_this_book=True,
            notes="有迟到前科", accept_crosscast_override=None,
        )
        add_registration(db, reg1)

        reg2 = Registration.create(
            car_id=car2.id, player_id=player.id,
            available_time="全天", read_this_book=False,
            notes="", accept_crosscast_override=True,
        )
        add_registration(db, reg2)

        regs1 = get_registrations_by_car(db, car1.id)
        regs2 = get_registrations_by_car(db, car2.id)
        r1, r2 = regs1[0], regs2[0]

        ok1 = r1.available_time == "19:00前" and r1.read_this_book is True and "迟到" in r1.notes
        ok2 = r2.available_time == "全天" and r2.read_this_book is False and r2.notes == ""
        ok3 = r2.effective_accept_crosscast(player) is True
        ok4 = r1.effective_accept_crosscast(player) is False

        print(f"  {'✓' if ok1 else '✗'} 车1报名信息独立保存")
        print(f"  {'✓' if ok2 else '✗'} 车2报名信息独立保存")
        print(f"  {'✓' if ok3 else '✗'} 车2本次反串覆盖玩家默认")
        print(f"  {'✓' if ok4 else '✗'} 车1使用玩家默认值")

        mr1 = analyze_match(db, car1, r1, player)
        mr2 = analyze_match(db, car2, r2, player)
        book_issue_1 = any("未读本" in str(i) for i in mr1.issues)
        book_issue_2 = any("未读本" in str(i) for i in mr2.issues)
        ok5 = book_issue_1 and not book_issue_2
        print(f"  {'✓' if ok5 else '✗'} 匹配引擎使用当次报名字段")

        return all([ok1, ok2, ok3, ok4, ok5])
    finally:
        _restore_db(backup)


def test_templates():
    sep("车队模板功能")
    backup = _clean_db()
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

        found = get_template(db, "周末硬核标配")
        ok1 = found is not None and found.min_experience == 3
        print(f"  {'✓' if ok1 else '✗'} 按名称查询模板")

        found2 = get_template(db, tpl.id)
        ok2 = found2 is not None
        print(f"  {'✓' if ok2 else '✗'} 按ID查询模板")

        tpls = list_templates(db)
        ok3 = len(tpls) == 1
        print(f"  {'✓' if ok3 else '✗'} list_templates 数量: {len(tpls)}")

        tpl2 = CarTemplate.create(
            name="萌新友好本", total_players=5, duration_hours=4.0,
            city="北京", shop="新店",
            role_constraints="",
            require_unread=False, min_experience=0,
        )
        add_template(db, tpl2)
        ok4 = tpl2.min_experience == 0
        print(f"  {'✓' if ok4 else '✗'} 支持0门槛模板")

        delete_template(db, tpl2.id)
        ok5 = get_template(db, tpl2.id) is None
        print(f"  {'✓' if ok5 else '✗'} 删除模板成功")

        return all([ok1, ok2, ok3, ok4, ok5])
    finally:
        _restore_db(backup)


def test_view_filter_sort():
    sep("view 筛选与排序")
    backup = _clean_db()
    db = load_db()
    try:
        car = Car.create(
            name="测试筛选车", total_players=6, duration_hours=5,
            city="", shop="",
            start_time=datetime.now().replace(hour=19, minute=0) + timedelta(days=1),
            require_unread=True, min_experience=0,
        )
        add_car(db, car)

        configs = [
            ("萌新", "男", 0, "随时", False, "", "pending"),
            ("老司机", "男", 10, "18:30-23:00", False, "", "approved"),
            ("迟到王", "男", 3, "随时", False, "经常迟到", "pending"),
            ("剧透鬼", "男", 5, "随时", True, "", "pending"),
            ("替补A", "女", 2, "随时", False, "", "bench"),
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

        tri = triage_registrations(db, car, regs, filter_status="pending")
        pending_count = len(tri["conflict"]) + len(tri["warning"]) + len(tri["match"])
        ok1 = pending_count == 3
        print(f"  {'✓' if ok1 else '✗'} --pending: 期望3，实际{pending_count}")

        tri = triage_registrations(db, car, regs, filter_status="eligible")
        eligible_count = len(tri["conflict"]) + len(tri["warning"]) + len(tri["match"])
        ok2 = eligible_count == 4
        print(f"  {'✓' if ok2 else '✗'} --eligible: 期望4，实际{eligible_count}")

        tri = triage_registrations(db, car, regs, filter_status="approved")
        approved_count = len(tri["conflict"]) + len(tri["warning"]) + len(tri["match"])
        ok3 = approved_count == 1
        print(f"  {'✓' if ok3 else '✗'} --approved: 期望1，实际{approved_count}")

        tri = triage_registrations(db, car, regs, filter_status="all", sort_by="experience")
        all_sorted = tri["all"]
        exps = [r.player.experience_count for r in all_sorted]
        ok4 = exps == sorted(exps, reverse=True)
        print(f"  {'✓' if ok4 else '✗'} --sort experience 降序: {exps}")

        return all([ok1, ok2, ok3, ok4])
    finally:
        _restore_db(backup)


def test_player_tags():
    """v1.2: 玩家长期标签功能"""
    sep("玩家长期标签")
    backup = _clean_db()
    db = load_db()
    try:
        p = Player.create(
            nickname="标签哥", gender="男",
            past_hardcore_books="", accept_crosscast=False,
            experience_count=5, tags=["靠谱", "易迟到"],
        )
        add_player(db, p)

        ok1 = p.has_tag("靠谱") and p.has_tag("易迟到") and not p.has_tag("跳车")
        print(f"  {'✓' if ok1 else '✗'} has_tag: 靠谱={p.has_tag('靠谱')} 易迟到={p.has_tag('易迟到')} 跳车={p.has_tag('跳车')}")

        risk = p.risk_tags()
        good = p.good_tags()
        ok2 = "易迟到" in risk and "靠谱" in good
        print(f"  {'✓' if ok2 else '✗'} risk_tags={risk} good_tags={good}")

        p.add_tag("天眼风险")
        p.add_tag("靠谱")  # 重复加不报错
        ok3 = p.has_tag("天眼风险") and p.tags.count("靠谱") == 1
        print(f"  {'✓' if ok3 else '✗'} add_tag: 天眼风险={p.has_tag('天眼风险')} 靠谱不重复={p.tags.count('靠谱') == 1}")

        p.remove_tag("易迟到")
        ok4 = not p.has_tag("易迟到")
        print(f"  {'✓' if ok4 else '✗'} remove_tag: 易迟到={p.has_tag('易迟到')}")

        # storage层 add_player_tag / remove_player_tag
        add_player_tag(db, p.id, "跳车")
        ok5 = p.has_tag("跳车")
        print(f"  {'✓' if ok5 else '✗'} storage.add_player_tag: 跳车={p.has_tag('跳车')}")

        remove_player_tag(db, p.id, "跳车")
        ok6 = not p.has_tag("跳车")
        print(f"  {'✓' if ok6 else '✗'} storage.remove_player_tag: 跳车={p.has_tag('跳车')}")

        # list_players_by_tag
        p2 = Player.create(nickname="也靠谱", gender="女", tags=["靠谱", "推土机"])
        add_player(db, p2)
        by_tag = list_players_by_tag(db, "靠谱")
        ok7 = len(by_tag) == 2
        print(f"  {'✓' if ok7 else '✗'} list_players_by_tag('靠谱'): {len(by_tag)}人")

        # matcher check_player_tags: 天眼风险应该产生critical
        car = Car.create(
            name="标签测试车", total_players=6, duration_hours=5,
            city="", shop="",
            start_time=datetime.now() + timedelta(days=1),
            require_unread=True, min_experience=0,
        )
        add_car(db, car)
        p3 = Player.create(nickname="天眼哥", gender="男", tags=["天眼风险", "靠谱"])
        add_player(db, p3)
        reg3 = Registration.create(car.id, p3.id, available_time="随时", read_this_book=False)
        add_registration(db, reg3)
        tag_issues = check_player_tags(car, reg3, p3)
        has_critical = any(i.severity == "critical" for i in tag_issues)
        ok8 = has_critical
        print(f"  {'✓' if ok8 else '✗'} check_player_tags: 天眼风险→critical={has_critical}")

        # analyze_match 里正面标签应降低 severity_score
        mr = analyze_match(db, car, reg3, p3)
        has_good_bonus = any("靠谱" in str(i) for i in mr.issues) is False  # 正面标签不产生issue，但加分
        print(f"  {'✓' if has_good_bonus else '✗'} 正面标签不产生issue（加分通过severity_score）")

        return all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8])
    finally:
        _restore_db(backup)


def test_car_copy():
    """v1.2+v1.3: 车队复制功能 + 群名持久化"""
    sep("车队复制（含群名持久化）")
    backup = _clean_db()
    db = load_db()
    try:
        # v1.3: 先建一个群
        grp = Group.create(
            name="硬核老玩家交流群", alias="老玩家群",
            emphasize_barrier=True, publish_style="hardcore",
        )
        add_group(db, grp)

        original = Car.create(
            name="《立方馆谋杀始末》", total_players=6, duration_hours=5.0,
            city="上海", shop="硬核旗舰店",
            start_time=datetime.now() + timedelta(days=1),
            role_constraints="3男3女", require_unread=True, min_experience=3,
            target_group=grp.id,  # v1.3: 原车归属群
        )
        add_car(db, original)

        # 添加几个报名到原车
        p1 = Player.create(nickname="玩家A", gender="男", experience_count=5)
        add_player(db, p1)
        reg1 = Registration.create(original.id, p1.id, available_time="随时")
        add_registration(db, reg1)

        # 复制车，改时间、店铺、并指定新群
        new_time = datetime.now() + timedelta(days=8)
        grp2 = Group.create(
            name="萌新推理社", alias="萌新群",
            emphasize_friendly=True, publish_style="friendly",
        )
        add_group(db, grp2)
        new_car = original.copy(
            start_time=new_time,
            shop="硬核分店",
            target_group=grp2.id,  # v1.3: 新车归属新群
        )
        add_car(db, new_car)

        # 验证复制结果
        ok1 = new_car.id != original.id
        ok2 = new_car.name == original.name
        ok3 = new_car.total_players == original.total_players
        ok4 = new_car.duration_hours == original.duration_hours
        ok5 = new_car.city == original.city
        ok6 = new_car.shop == "硬核分店"  # 被覆盖
        ok7 = new_car.start_time == new_time  # 被覆盖
        ok8 = new_car.role_constraints == original.role_constraints
        ok9 = new_car.require_unread == original.require_unread
        ok10 = new_car.min_experience == original.min_experience

        # v1.3: 验证群名持久化
        ok13 = original.target_group == grp.id
        ok14 = new_car.target_group == grp2.id
        ok15 = new_car.target_group != original.target_group

        # 新车不应有报名
        new_regs = get_registrations_by_car(db, new_car.id)
        ok11 = len(new_regs) == 0

        # 原车报名不受影响
        orig_regs = get_registrations_by_car(db, original.id)
        ok12 = len(orig_regs) == 1

        checks = [ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9, ok10, ok11, ok12, ok13, ok14, ok15]
        labels = ["新ID", "同名", "同人数", "同时长", "同城市", "新店铺", "新时间",
                  "同角色配置", "同未读本要求", "同经验门槛", "新车无报名", "原车报名不变",
                  "原车群名持久化", "新车群名独立", "群名不互相影响"]
        for label, ok in zip(labels, checks):
            print(f"  {'✓' if ok else '✗'} {label}")

        return all(checks)
    finally:
        _restore_db(backup)


def test_parse_index_ranges():
    """v1.2: 序号范围解析（用于view内批量审核）"""
    sep("序号范围解析 parse_index_ranges")
    from hardcore_car import parse_index_ranges

    cases = [
        ("1", [1]),
        ("1,3,5", [1, 3, 5]),
        ("1-3", [1, 2, 3]),
        ("1-3,7", [1, 2, 3, 7]),
        ("5-3", [3, 4, 5]),  # 反向范围
        ("1,2,3-5,8", [1, 2, 3, 4, 5, 8]),
        ("", []),
        ("1,3-5,10,12-14", [1, 3, 4, 5, 10, 12, 13, 14]),
        ("1，3，5", [1, 3, 5]),  # 中文逗号
    ]
    all_ok = True
    for input_, expected in cases:
        result = parse_index_ranges(input_)
        ok = result == expected
        mark = "✓" if ok else "✗"
        if not ok:
            all_ok = False
        print(f"  {mark} {input_!r:25} => {result}  (期望 {expected})")
    return all_ok


def test_export_formats():
    """v1.2: 三种导出格式 × 两种范围"""
    sep("导出格式 notice/check/shop × approved/bench")
    backup = _clean_db()
    db = load_db()
    try:
        car = Car.create(
            name="导出测试车", total_players=4, duration_hours=5,
            city="上海", shop="测试店",
            start_time=datetime.now().replace(hour=19, minute=0) + timedelta(days=1),
            require_unread=True, min_experience=0,
        )
        add_car(db, car)

        # 创建玩家并标记状态
        configs = [
            ("萌新甲", "男", 0, "随时", False, "", "approved", []),
            ("老手乙", "女", 5, "随时", False, "", "approved", ["靠谱"]),
            ("替补丙", "男", 3, "随时", False, "", "bench", ["易迟到"]),
            ("待审丁", "女", 1, "随时", True, "可能天眼", "pending", ["天眼风险"]),
        ]
        for nick, gender, exp, avail, has_read, notes, status, tags in configs:
            p = Player.create(nickname=nick, gender=gender, experience_count=exp, tags=tags)
            add_player(db, p)
            reg = Registration.create(car.id, p.id, available_time=avail,
                                      read_this_book=has_read, notes=notes)
            reg.status = status
            add_registration(db, reg)

        from hardcore_car import cmd_export
        import io
        from unittest.mock import patch

        # 测试1: export <id> notice approved（仅群公告+仅已确认）
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            cmd_export(db, [car.id, "notice", "approved"])
            output = mock_out.getvalue()
        ok1 = "萌新甲" in output and "老手乙" in output
        ok1b = "替补丙" not in output  # approved scope 不含替补
        ok1c = "萌新" in output or "[萌新]" in output  # 0经验显示
        print(f"  {'✓' if ok1 else '✗'} notice approved: 含已确认={ok1} 不含替补={ok1b}")
        print(f"  {'✓' if ok1c else '✗'} notice 0经验显示: 萌新标记={'ok' if ok1c else 'missing'}")

        # 测试2: export <id> check bench（审核表+已确认+替补）
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            cmd_export(db, [car.id, "check", "bench"])
            output = mock_out.getvalue()
        ok2 = "替补丙" in output
        ok2b = "易迟到" in output or "天眼" in output  # 风险标签带出
        print(f"  {'✓' if ok2 else '✗'} check bench: 含替补={ok2} 风险标签带出={ok2b}")

        # 测试3: export <id> shop approved（店铺表+仅已确认）
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            cmd_export(db, [car.id, "shop", "approved"])
            output = mock_out.getvalue()
        ok3 = "导出测试车" in output and "测试店" in output
        ok3b = "无门槛" in output or "含萌新" in output  # 0门槛信息
        ok3c = "萌新" in output  # 0经验显示
        ok3d = "替补" not in output  # approved scope 不含替补（合计行也不出现替补字样）
        print(f"  {'✓' if ok3b else '✗'} shop 0门槛信息: {ok3b}")
        print(f"  {'✓' if ok3c else '✗'} shop 0经验显示: {ok3c}")
        print(f"  {'✓' if ok3d else '✗'} shop approved不含替补: {ok3d}")

        # 测试4: export <id> all bench（全格式+已确认+替补）
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            cmd_export(db, [car.id, "all", "bench"])
            output = mock_out.getvalue()
        ok4 = "群公告" in output and "审核表" in output and "店铺交接" in output
        print(f"  {'✓' if ok4 else '✗'} all bench: 包含三种格式={ok4}")

        return all([ok1, ok1b, ok1c, ok2, ok2b, ok3, ok3b, ok3c, ok3d, ok4])
    finally:
        _restore_db(backup)


def test_full_workflow_v12():
    sep("完整工作流 v1.2（0经验+模板+分离+标签+复制+筛选+导出）")
    backup = _clean_db()
    db = load_db()
    try:
        # 1. 建模板
        tpl = CarTemplate.create(
            name="周末5h萌新友好", total_players=6, duration_hours=5,
            city="上海", shop="硬核旗舰店",
            role_constraints="3男3女", require_unread=True, min_experience=0,
        )
        add_template(db, tpl)
        print(f"  ✓ 建模板: {tpl.name} (0门槛)")

        # 2. 建车
        car = Car.create(
            name="《立方馆谋杀始末》", total_players=tpl.total_players,
            duration_hours=tpl.duration_hours,
            city=tpl.city, shop=tpl.shop,
            start_time=datetime.now().replace(hour=19, minute=0) + timedelta(days=1),
            role_constraints=tpl.role_constraints,
            require_unread=tpl.require_unread,
            min_experience=tpl.min_experience,
            template_id=tpl.id,
        )
        add_car(db, car)
        print(f"  ✓ 建车: {car.name} 门槛={car.min_experience}")

        # 3. 添加玩家（含标签）
        players_data = [
            ("萌新A", "女", 0, "随时", False, "", True, ["萌新友好"]),
            ("老炮C", "男", 8, "随时", False, "", False, ["靠谱", "推土机"]),
            ("天眼E", "男", 99, "随时", True, "疑似天眼", False, ["天眼风险"]),
            ("跳车F", "女", 2, "随时", False, "去年跳过车", False, ["跳车"]),
            ("迟到G", "男", 3, "随时", False, "经常迟到", False, ["易迟到"]),
            ("靠谱H", "男", 6, "18:30后", False, "", True, ["靠谱"]),
        ]
        for nick, gender, exp, avail, has_read, notes, cc, tags in players_data:
            p = Player.create(nickname=nick, gender=gender,
                              past_hardcore_books="", accept_crosscast=cc,
                              experience_count=exp, tags=tags)
            add_player(db, p)
            reg = Registration.create(car.id, p.id, available_time=avail,
                                      read_this_book=has_read, notes=notes)
            add_registration(db, reg)
        print(f"  ✓ 添加 {len(players_data)} 名玩家 (含标签)")

        # 4. 分诊
        regs = get_registrations_by_car(db, car.id)
        triaged = triage_registrations(db, car, regs)
        match_nicks = {r.player.nickname for r in triaged["match"]}
        ok1 = "萌新A" in match_nicks
        print(f"  {'✓' if ok1 else '✗'} 0经验萌新出现在匹配列表")

        # 5. 天眼风险标签应产生 critical
        conflict_nicks = {r.player.nickname for r in triaged["conflict"]}
        ok2 = "天眼E" in conflict_nicks
        print(f"  {'✓' if ok2 else '✗'} 天眼风险标签→冲突段")

        # 6. 复制车
        new_time = datetime.now() + timedelta(days=8)
        car2 = car.copy(start_time=new_time, shop="硬核分店")
        add_car(db, car2)
        ok3 = car2.shop == "硬核分店" and car2.min_experience == 0
        print(f"  {'✓' if ok3 else '✗'} 复制车: 新店={car2.shop} 门槛={car2.min_experience}")

        # 7. 筛选+排序
        tri = triage_registrations(db, car, regs, filter_status="eligible", sort_by="experience")
        eligible = tri["all"]
        exps = [r.player.experience_count for r in eligible]
        ok4 = exps == sorted(exps, reverse=True) and 99 not in exps
        print(f"  {'✓' if ok4 else '✗'} eligible+experience排序: {exps}")

        # 8. 审核一些玩家
        for r in triaged["match"]:
            r.registration.status = "approved"
        save_db(db)

        approved = [r for r in regs if r.status == "approved"]
        print(f"  ✓ 审核完成: 已确认{len(approved)}人")

        # 9. 0经验在导出中显示
        from hardcore_car import exp_display
        ok5 = True
        for r in approved:
            p = get_player(db, r.player_id)
            if p.experience_count == 0:
                disp = exp_display(p.experience_count)
                if disp != "萌新":
                    ok5 = False
                print(f"  ✓ 0经验导出显示: {p.nickname} → {disp}")

        return all([ok1, ok2, ok3, ok4, ok5])
    finally:
        _restore_db(backup)


def test_group_management():
    """v1.3: 群管理 CRUD"""
    sep("群管理 CRUD")
    backup = _clean_db()
    db = load_db()
    try:
        # 1. 建群
        grp1 = Group.create(
            name="硬核老玩家交流群", alias="老玩家群",
            emphasize_barrier=True, publish_style="hardcore",
            default_group=True, footer_note="跳车请提前24小时告知",
        )
        add_group(db, grp1)

        grp2 = Group.create(
            name="萌新推理社", alias="萌新群",
            emphasize_friendly=True, publish_style="friendly",
        )
        add_group(db, grp2)
        grp3 = Group.create(
            name="剧本杀店铺会员群", alias="店铺群",
            emphasize_venue=True, default_city="上海", default_shop="硬核旗舰店",
        )
        add_group(db, grp3)

        ok1 = len(list_groups(db)) == 3
        print(f"  {'✓' if ok1 else '✗'} 创建3个群")

        # 2. 智能查找：按ID/简称/群名
        g_by_id = get_group(db, grp1.id)
        g_by_alias = get_group(db, "老玩家群")
        g_by_name = get_group(db, "萌新推理社")
        g_by_partial = get_group(db, "店铺")  # 模糊匹配
        ok2 = g_by_id and g_by_id.alias == "老玩家群"
        ok3 = g_by_alias and g_by_alias.id == grp1.id
        ok4 = g_by_name and g_by_name.alias == "萌新群"
        ok5 = g_by_partial and g_by_partial.alias == "店铺群"
        print(f"  {'✓' if ok2 else '✗'} 按ID查找")
        print(f"  {'✓' if ok3 else '✗'} 按简称查找")
        print(f"  {'✓' if ok4 else '✗'} 按群名查找")
        print(f"  {'✓' if ok5 else '✗'} 模糊查找")

        # 3. 默认群
        default_g = get_default_group(db)
        ok6 = default_g and default_g.id == grp1.id
        print(f"  {'✓' if ok6 else '✗'} 默认群: {default_g.name if default_g else 'None'}")

        # 4. 设置新默认群，自动取消其他
        grp2.default_group = True
        add_group(db, grp2)  # 保存时应自动取消其他默认
        default_g2 = get_default_group(db)
        ok7 = default_g2 and default_g2.id == grp2.id
        g1_refresh = get_group(db, grp1.id)
        ok8 = g1_refresh.default_group is False
        print(f"  {'✓' if ok7 else '✗'} 设新默认群")
        print(f"  {'✓' if ok8 else '✗'} 旧默认群自动取消")

        # 5. 删除群
        delete_group(db, grp3.id)
        ok9 = len(list_groups(db)) == 2
        print(f"  {'✓' if ok9 else '✗'} 删除群")

        # 6. 群排序：display_name
        dn = grp1.display_name()
        ok10 = "老玩家群" in dn and "硬核老玩家交流群" in dn
        print(f"  {'✓' if ok10 else '✗'} display_name: {dn}")

        return all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9, ok10])
    finally:
        _restore_db(backup)


def test_source_group():
    """v1.3: 来源群记录与显示"""
    sep("来源群记录")
    backup = _clean_db()
    db = load_db()
    try:
        grp = Group.create(name="测试群", alias="测群")
        add_group(db, grp)

        car = Car.create(
            name="《测试本》", total_players=6, duration_hours=5,
            city="上海", shop="A店",
            start_time=datetime.now() + timedelta(days=1),
            target_group=grp.id,
        )
        add_car(db, car)

        p = Player.create(nickname="测试玩家", gender="男", experience_count=3)
        add_player(db, p)

        # 报名时记录来源群
        reg = Registration.create(
            car.id, p.id, available_time="随时",
            source_group=grp.id,
        )
        add_registration(db, reg)

        # 验证持久化
        regs = get_registrations_by_car(db, car.id)
        ok1 = regs[0].source_group == grp.id
        print(f"  {'✓' if ok1 else '✗'} 报名记录来源群")

        # 车归属群
        ok2 = car.target_group == grp.id
        print(f"  {'✓' if ok2 else '✗'} 车记录归属群")

        # 保存重载测试持久化
        save_db(db)
        db2 = load_db()
        car2 = get_car(db2, car.id)
        reg2 = get_registrations_by_car(db2, car.id)[0]
        ok3 = car2.target_group == grp.id
        ok4 = reg2.source_group == grp.id
        print(f"  {'✓' if ok3 else '✗'} 保存后车归属群持久化")
        print(f"  {'✓' if ok4 else '✗'} 保存后来源群持久化")

        return all([ok1, ok2, ok3, ok4])
    finally:
        _restore_db(backup)


def test_double_booking():
    """v1.3: 跨群重复报名检测"""
    sep("跨群重复报名检测")
    backup = _clean_db()
    db = load_db()
    try:
        grp1 = Group.create(name="群A", alias="A")
        grp2 = Group.create(name="群B", alias="B")
        add_group(db, grp1)
        add_group(db, grp2)

        now = datetime.now()
        # 两车时间接近（3小时间隔，小于6小时阈值）
        car1 = Car.create(
            name="《车1》", total_players=6, duration_hours=5,
            city="上海", shop="A店",
            start_time=now + timedelta(days=1, hours=19),
            target_group=grp1.id,
        )
        car2 = Car.create(
            name="《车2》", total_players=6, duration_hours=5,
            city="上海", shop="B店",
            start_time=now + timedelta(days=1, hours=21),  # 与车1间隔2小时
            target_group=grp2.id,
        )
        add_car(db, car1)
        add_car(db, car2)

        p = Player.create(nickname="时间管理大师", gender="男", experience_count=5)
        add_player(db, p)

        reg1 = Registration.create(car1.id, p.id, available_time="随时", source_group=grp1.id)
        reg2 = Registration.create(car2.id, p.id, available_time="随时", source_group=grp2.id)
        add_registration(db, reg1)
        add_registration(db, reg2)

        # 检测跨群重复报名
        issues = check_double_booking(db, car2, reg2, p)
        has_double = any("double_booking" in str(i) for i in issues)
        ok1 = has_double
        issue_str = str([str(i) for i in issues])
        print(f"  {'✓' if ok1 else '✗'} 检测到跨群重复报名：{issue_str}")

        # analyze_match 应该包含该问题
        mr = analyze_match(db, car2, reg2, p)
        ok2 = any("double_booking" in str(i) for i in mr.issues)
        print(f"  {'✓' if ok2 else '✗'} analyze_match包含跨群检测")

        # 两车时间间隔大（>6小时）不应触发
        car3 = Car.create(
            name="《车3》", total_players=6, duration_hours=5,
            city="上海", shop="C店",
            start_time=now + timedelta(days=3),
            target_group=grp1.id,
        )
        add_car(db, car3)
        reg3 = Registration.create(car3.id, p.id, available_time="随时", source_group=grp1.id)
        add_registration(db, reg3)
        issues2 = check_double_booking(db, car3, reg3, p)
        ok3 = len(issues2) == 0
        print(f"  {'✓' if ok3 else '✗'} 时间间隔足够时无警告")

        return all([ok1, ok2, ok3])
    finally:
        _restore_db(backup)


def test_multi_group_draft():
    """v1.3: 多群 draft 生成不同版本文案"""
    sep("多群 draft 生成")
    backup = _clean_db()
    db = load_db()
    try:
        from hardcore_car import _generate_draft_for_group

        # 创建3个群
        grp_hard = Group.create(
            name="硬核老玩家群", alias="老玩家",
            emphasize_barrier=True, publish_style="hardcore",
        )
        grp_new = Group.create(
            name="萌新群", alias="萌新",
            emphasize_friendly=True, publish_style="friendly",
        )
        grp_shop = Group.create(
            name="店铺会员群", alias="店铺",
            emphasize_venue=True, publish_style="casual",
        )
        add_group(db, grp_hard)
        add_group(db, grp_new)
        add_group(db, grp_shop)

        car = Car.create(
            name="《测试本》", total_players=6, duration_hours=5,
            city="上海", shop="硬核旗舰店",
            start_time=datetime.now() + timedelta(days=1),
            min_experience=3,  # 有门槛
        )
        add_car(db, car)

        # 为每个群生成文案
        draft_hard = _generate_draft_for_group(car, grp_hard, db)
        draft_new = _generate_draft_for_group(car, grp_new, db)
        draft_shop = _generate_draft_for_group(car, grp_shop, db)
        draft_generic = _generate_draft_for_group(car, None, db)

        text_hard = "\n".join(draft_hard)
        text_new = "\n".join(draft_new)
        text_shop = "\n".join(draft_shop)

        # 老玩家群应有门槛提示
        ok1 = "门槛" in text_hard and ("不扶车" in text_hard or "硬核组局" in text_hard)
        print(f"  {'✓' if ok1 else '✗'} 老玩家群强调门槛")

        # 萌新群应有带新提示
        ok2 = "萌新" in text_new and "带新" in text_new
        print(f"  {'✓' if ok2 else '✗'} 萌新群强调带新")

        # 店铺群应有地点强调
        ok3 = "（硬核旗舰店）" in text_shop and "零食饮料" in text_shop
        print(f"  {'✓' if ok3 else '✗'} 店铺群强调地点")

        # 每个文案都包含基本信息
        ok4 = all("《测试本》" in t for t in [text_hard, text_new, text_shop])
        ok5 = all("上海" in t for t in [text_hard, text_new, text_shop])
        print(f"  {'✓' if ok4 else '✗'} 所有文案包含本名")
        print(f"  {'✓' if ok5 else '✗'} 所有文案包含地点")

        # 不同群有不同抬头
        ok6 = "老玩家" in text_hard and "萌新" in text_new and "店铺" in text_shop
        print(f"  {'✓' if ok6 else '✗'} 各群文案抬头不同")

        return all([ok1, ok2, ok3, ok4, ok5, ok6])
    finally:
        _restore_db(backup)


def test_car_target_group_persistence():
    """v1.3: 车归属群跨程序重启持久化"""
    sep("车归属群重启持久化")
    backup = _clean_db()
    db = load_db()
    try:
        grp = Group.create(name="测试持久化群", alias="持久群")
        add_group(db, grp)

        car = Car.create(
            name="《持久化测试》", total_players=6, duration_hours=5,
            city="上海", shop="A店",
            start_time=datetime.now() + timedelta(days=1),
            target_group=grp.id,
        )
        add_car(db, car)

        # 模拟退出程序：保存 -> 重新加载
        save_db(db)

        db2 = load_db()
        car_reloaded = get_car(db2, car.id)
        ok1 = car_reloaded.target_group == grp.id
        print(f"  {'✓' if ok1 else '✗'} 车归属群重启后仍在")

        grp_reloaded = get_group(db2, car_reloaded.target_group)
        ok2 = grp_reloaded and grp_reloaded.alias == "持久群"
        print(f"  {'✓' if ok2 else '✗'} 可通过归属群ID查到群")

        return all([ok1, ok2])
    finally:
        _restore_db(backup)


def main():
    print("🔥 硬核推理车队招募助手 v1.3 - 集成测试套件")
    print(f"   Python {sys.version.split()[0]}  |  DB: {DB_FILE}")

    results = []
    tests = [
        ("0经验验证器+显示", test_v_int_nonneg),
        ("时间解析器", test_time_parser),
        ("玩家/报名字段分离", test_player_registration_split),
        ("车队模板功能", test_templates),
        ("view筛选/排序", test_view_filter_sort),
        ("玩家长期标签", test_player_tags),
        ("车队复制（含群名持久化）", test_car_copy),
        ("序号范围解析", test_parse_index_ranges),
        ("导出格式×范围", test_export_formats),
        ("完整工作流v1.2", test_full_workflow_v12),
        ("群管理 CRUD", test_group_management),
        ("来源群记录", test_source_group),
        ("跨群重复报名检测", test_double_booking),
        ("多群 draft 生成", test_multi_group_draft),
        ("车归属群重启持久化", test_car_target_group_persistence),
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
