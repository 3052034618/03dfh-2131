import json
import os
from typing import Optional, List
from datetime import datetime

from models import (
    Database, Car, Player, Registration, CarTemplate, Group,
    EnhancedJSONEncoder, decode_datetime
)

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hardcore_cars.json")


def _ensure_data_dir():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)


def _migrate_old_data(data: dict) -> Database:
    """将旧版数据迁移到新版结构（拆分玩家/报名属性 + 增加模板 + 群管理）"""
    cars_raw = data.get("cars", [])
    players_raw = data.get("players", [])
    regs_raw = data.get("registrations", [])
    templates_raw = data.get("templates", [])
    groups_raw = data.get("groups", [])  # ✅ v1.3: 群

    # --- 迁移 Player：去掉旧报名级字段 ---
    # 旧版 Player 含 available_time, notes, read_this_book
    # 新版 Player 只保留长期属性
    migrated_players: List[Player] = []
    old_player_extra = {}  # player_id -> {available_time, notes, read_this_book}

    for p in players_raw:
        pid = p.get("id")
        extra = {
            "available_time": p.pop("available_time", "随时"),
            "notes": p.pop("notes", ""),
            "read_this_book": p.pop("read_this_book", False),
        }
        if pid:
            old_player_extra[pid] = extra
        # 兼容：无 past_hardcore_books 字段时用空串
        p.setdefault("past_hardcore_books", "")
        p.setdefault("accept_crosscast", False)
        p.setdefault("experience_count", 0)
        p.setdefault("tags", [])  # ✅ v1.2：tags 默认空列表
        try:
            migrated_players.append(Player(**p))
        except TypeError as e:
            print(f"[警告] 跳过损坏的玩家记录 {p.get('nickname', '?')}: {e}")

    # --- 迁移 Registration：补充当次报名字段 + 来源群 ---
    # 旧版 Registration 只有 car_id/player_id/status
    # 新版增加 available_time, read_this_book, notes, accept_crosscast_override, source_group
    migrated_regs: List[Registration] = []
    player_ids = {p.id for p in migrated_players}
    for r in regs_raw:
        pid = r.get("player_id")
        extra = old_player_extra.get(pid, {}) if pid else {}
        r.setdefault("available_time", extra.get("available_time", "随时"))
        r.setdefault("read_this_book", extra.get("read_this_book", False))
        r.setdefault("notes", extra.get("notes", ""))
        r.setdefault("accept_crosscast_override", None)
        r.setdefault("status", "pending")
        r.setdefault("source_group", None)  # ✅ v1.3: 来源群
        try:
            if pid and pid in player_ids:
                migrated_regs.append(Registration(**r))
        except TypeError as e:
            print(f"[警告] 跳过损坏的报名记录: {e}")

    # --- 迁移 Car ---
    migrated_cars: List[Car] = []
    for c in cars_raw:
        c.setdefault("role_constraints", "")
        c.setdefault("require_unread", False)
        c.setdefault("min_experience", 0)
        c.setdefault("status", "open")
        c.setdefault("template_id", None)
        c.setdefault("target_group", None)  # ✅ v1.3: 归属群
        try:
            migrated_cars.append(Car(**c))
        except TypeError as e:
            print(f"[警告] 跳过损坏的车辆记录 {c.get('name', '?')}: {e}")

    # --- 模板 ---
    migrated_templates: List[CarTemplate] = []
    for t in templates_raw:
        t.setdefault("role_constraints", "")
        t.setdefault("require_unread", True)
        t.setdefault("min_experience", 0)
        try:
            migrated_templates.append(CarTemplate(**t))
        except TypeError as e:
            print(f"[警告] 跳过损坏的模板 {t.get('name', '?')}: {e}")

    # --- 群 ---
    migrated_groups: List[Group] = []
    for g in groups_raw:
        g.setdefault("alias", "")
        g.setdefault("default_group", False)
        g.setdefault("publish_style", "formal")
        g.setdefault("default_city", "")
        g.setdefault("default_shop", "")
        g.setdefault("emphasize_barrier", False)
        g.setdefault("emphasize_friendly", False)
        g.setdefault("emphasize_venue", False)
        g.setdefault("footer_note", "")
        try:
            migrated_groups.append(Group(**g))
        except TypeError as e:
            print(f"[警告] 跳过损坏的群记录 {g.get('name', '?')}: {e}")

    db = Database(
        cars=migrated_cars,
        players=migrated_players,
        registrations=migrated_regs,
        templates=migrated_templates,
        groups=migrated_groups,  # ✅ v1.3
    )

    # 有迁移发生就自动保存一次
    if templates_raw or old_player_extra or groups_raw:
        try:
            save_db(db)
            if old_player_extra:
                print("[信息] 已完成数据迁移：玩家资料与单次报名已分离")
            if groups_raw:
                print("[信息] 已完成群管理数据迁移")
        except Exception:
            pass
    return db


def load_db() -> Database:
    _ensure_data_dir()
    if not os.path.exists(DB_FILE):
        return Database()
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f, object_hook=decode_datetime)
        return _migrate_old_data(data)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        print(f"[警告] 数据文件损坏，已创建新数据库: {e}")
        return Database()


def save_db(db: Database) -> None:
    _ensure_data_dir()
    data = {
        "cars": [c.__dict__ for c in db.cars],
        "players": [p.__dict__ for p in db.players],
        "registrations": [r.__dict__ for r in db.registrations],
        "templates": [t.__dict__ for t in db.templates],
        "groups": [g.__dict__ for g in db.groups],  # ✅ v1.3
    }
    tmp_file = DB_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, cls=EnhancedJSONEncoder)
    os.replace(tmp_file, DB_FILE)


# ---------- Car ----------

def add_car(db: Database, car: Car) -> Car:
    db.cars.append(car)
    save_db(db)
    return car


def get_car(db: Database, car_id: str) -> Optional[Car]:
    for c in db.cars:
        if c.id == car_id:
            return c
    return None


def list_cars(db: Database, status: Optional[str] = None) -> List[Car]:
    cars = sorted(db.cars, key=lambda c: c.start_time, reverse=True)
    if status:
        return [c for c in cars if c.status == status]
    return cars


def update_car_status(db: Database, car_id: str, status: str) -> bool:
    car = get_car(db, car_id)
    if car:
        car.status = status
        save_db(db)
        return True
    return False


def delete_car(db: Database, car_id: str) -> bool:
    car = get_car(db, car_id)
    if car:
        db.cars = [c for c in db.cars if c.id != car_id]
        db.registrations = [r for r in db.registrations if r.car_id != car_id]
        save_db(db)
        return True
    return False


# ---------- Player ----------

def add_player(db: Database, player: Player) -> Player:
    db.players.append(player)
    save_db(db)
    return player


def get_player(db: Database, player_id: str) -> Optional[Player]:
    for p in db.players:
        if p.id == player_id:
            return p
    return None


def find_player_by_nickname(db: Database, nickname: str) -> Optional[Player]:
    for p in db.players:
        if p.nickname == nickname:
            return p
    return None


def update_player(db: Database, player_id: str, **fields) -> bool:
    p = get_player(db, player_id)
    if not p:
        return False
    for k, v in fields.items():
        if hasattr(p, k):
            setattr(p, k, v)
    save_db(db)
    return True


# ---------- Registration ----------

def add_registration(db: Database, registration: Registration) -> Registration:
    existing = [
        r for r in db.registrations
        if r.car_id == registration.car_id and r.player_id == registration.player_id
    ]
    if existing:
        # 同名玩家再次报名同一车：更新当次信息
        old = existing[0]
        old.available_time = registration.available_time
        old.read_this_book = registration.read_this_book
        old.notes = registration.notes
        old.accept_crosscast_override = registration.accept_crosscast_override
        save_db(db)
        return old
    db.registrations.append(registration)
    save_db(db)
    return registration


def remove_registration(db: Database, reg_id: str) -> bool:
    before = len(db.registrations)
    db.registrations = [r for r in db.registrations if r.id != reg_id]
    save_db(db)
    return len(db.registrations) < before


def get_registrations_by_car(db: Database, car_id: str) -> List[Registration]:
    return [r for r in db.registrations if r.car_id == car_id]


def get_player_registrations(db: Database, player_id: str) -> List[Registration]:
    return [r for r in db.registrations if r.player_id == player_id]


def update_registration_status(db: Database, reg_id: str, status: str) -> bool:
    for r in db.registrations:
        if r.id == reg_id:
            r.status = status
            save_db(db)
            return True
    return False


def update_registration(db: Database, reg_id: str, **fields) -> bool:
    for r in db.registrations:
        if r.id == reg_id:
            for k, v in fields.items():
                if hasattr(r, k):
                    setattr(r, k, v)
            save_db(db)
            return True
    return False


# ---------- CarTemplate ----------

def add_template(db: Database, template: CarTemplate) -> CarTemplate:
    db.templates.append(template)
    save_db(db)
    return template


def get_template(db: Database, template_id_or_name: str) -> Optional[CarTemplate]:
    for t in db.templates:
        if t.id == template_id_or_name or t.name == template_id_or_name:
            return t
    return None


def list_templates(db: Database) -> List[CarTemplate]:
    return sorted(db.templates, key=lambda t: t.created_at, reverse=True)


def delete_template(db: Database, template_id: str) -> bool:
    before = len(db.templates)
    db.templates = [t for t in db.templates if t.id != template_id and t.name != template_id]
    save_db(db)
    return len(db.templates) < before


# ---------- Player Tags（长期标签） ----------

PRESET_TAGS = [
    # 正面标签
    "靠谱", "老炮", "大神", "推土机", "宝藏玩家", "输出担当", "氛围组",
    # 风险标签
    "易迟到", "常迟到", "跳车", "鸽子", "天眼风险", "剧透", "挂机", "杠精",
    # 中性
    "萌新友好", "社恐", "社牛", "情感偏好", "硬核偏好",
]


def add_player_tag(db: Database, player_id: str, tag: str) -> bool:
    p = get_player(db, player_id)
    if not p:
        return False
    p.add_tag(tag)
    save_db(db)
    return True


def remove_player_tag(db: Database, player_id: str, tag: str) -> bool:
    p = get_player(db, player_id)
    if not p:
        return False
    p.remove_tag(tag)
    save_db(db)
    return True


def list_players_by_tag(db: Database, tag: str) -> List[Player]:
    return [p for p in db.players if p.has_tag(tag)]


# ---------- Groups（群管理） ----------

def add_group(db: Database, group: Group) -> Group:
    # 先去重：如果已存在同ID，先删除
    db.groups = [g for g in db.groups if g.id != group.id]
    # 如果是默认群，取消其他群的默认
    if group.default_group:
        for g in db.groups:
            g.default_group = False
    db.groups.append(group)
    save_db(db)
    return group


def get_group(db: Database, identifier: str) -> Optional[Group]:
    """按ID/简称/群名智能查找群"""
    if not identifier:
        # 返回默认群
        for g in db.groups:
            if g.default_group:
                return g
        return db.groups[0] if db.groups else None
    for g in db.groups:
        if g.id == identifier:
            return g
        if g.alias and g.alias.lower() == identifier.lower():
            return g
        if g.name.lower() == identifier.lower():
            return g
    # 模糊匹配
    for g in db.groups:
        alias_lower = g.alias.lower() if g.alias else ""
        if identifier.lower() in g.name.lower() or identifier.lower() in alias_lower:
            return g
    return None


def get_default_group(db: Database) -> Optional[Group]:
    for g in db.groups:
        if g.default_group:
            return g
    return db.groups[0] if db.groups else None


def list_groups(db: Database) -> List[Group]:
    return sorted(db.groups, key=lambda g: (not g.default_group, g.created_at))


def delete_group(db: Database, identifier: str) -> bool:
    before = len(db.groups)
    target = get_group(db, identifier)
    if target:
        db.groups = [g for g in db.groups if g.id != target.id]
        save_db(db)
    return len(db.groups) < before
