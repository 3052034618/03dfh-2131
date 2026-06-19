from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime
import uuid
import json


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, '__dataclass_fields__'):
            return asdict(o)
        return super().default(o)


def decode_datetime(dct):
    for key, val in dct.items():
        if isinstance(val, str) and ('time' in key or 'date' in key or 'deadline' in key):
            try:
                dct[key] = datetime.fromisoformat(val)
            except (ValueError, TypeError):
                pass
    return dct


@dataclass
class CarTemplate:
    """车队模板：保存常用配置以便快速套用"""
    id: str
    name: str  # 模板名称，如 "周末5h硬核标配"
    total_players: int
    duration_hours: float
    city: str
    shop: str
    role_constraints: str = ""
    require_unread: bool = True
    min_experience: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(cls, name, total_players, duration_hours, city, shop,
               role_constraints="", require_unread=True, min_experience=0):
        return cls(
            id=str(uuid.uuid4())[:8],
            name=name,
            total_players=int(total_players),
            duration_hours=float(duration_hours),
            city=city,
            shop=shop,
            role_constraints=role_constraints,
            require_unread=bool(require_unread),
            min_experience=int(min_experience),
        )


@dataclass
class Car:
    id: str
    name: str
    total_players: int
    duration_hours: float
    city: str
    shop: str
    start_time: datetime
    role_constraints: str = ""
    require_unread: bool = False
    min_experience: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "open"
    template_id: Optional[str] = None

    @classmethod
    def create(cls, name, total_players, duration_hours, city, shop,
               start_time, role_constraints="", require_unread=False,
               min_experience=0, template_id=None):
        return cls(
            id=str(uuid.uuid4())[:8],
            name=name,
            total_players=int(total_players),
            duration_hours=float(duration_hours),
            city=city,
            shop=shop,
            start_time=start_time,
            role_constraints=role_constraints,
            require_unread=bool(require_unread),
            min_experience=int(min_experience),
            template_id=template_id,
        )


@dataclass
class Player:
    """玩家基础资料（长期不变的属性）"""
    id: str
    nickname: str
    gender: str
    past_hardcore_books: str  # 玩过的硬核本，履历用
    accept_crosscast: bool = False  # 一般是否接受反串（报名时可覆盖）
    experience_count: int = 0  # 累计硬核本数（长期）
    registered_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(cls, nickname, gender, past_hardcore_books="",
               accept_crosscast=False, experience_count=0):
        return cls(
            id=str(uuid.uuid4())[:8],
            nickname=nickname,
            gender=gender,
            past_hardcore_books=past_hardcore_books,
            accept_crosscast=bool(accept_crosscast),
            experience_count=int(experience_count),
        )


@dataclass
class Registration:
    """单次报名（当次车的特有属性，与其他车次互不影响）"""
    id: str
    car_id: str
    player_id: str
    available_time: str = "随时"  # 本次可到时间
    read_this_book: bool = False  # 本次是否已读本
    notes: str = ""  # 本次备注雷点
    accept_crosscast_override: Optional[bool] = None  # None=使用玩家默认值
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(cls, car_id, player_id, available_time="随时",
               read_this_book=False, notes="", accept_crosscast_override=None):
        return cls(
            id=str(uuid.uuid4())[:8],
            car_id=car_id,
            player_id=player_id,
            available_time=available_time,
            read_this_book=bool(read_this_book),
            notes=notes,
            accept_crosscast_override=accept_crosscast_override,
        )

    def effective_accept_crosscast(self, player: Player) -> bool:
        if self.accept_crosscast_override is not None:
            return self.accept_crosscast_override
        return player.accept_crosscast


@dataclass
class Database:
    cars: List[Car] = field(default_factory=list)
    players: List[Player] = field(default_factory=list)
    registrations: List[Registration] = field(default_factory=list)
    templates: List[CarTemplate] = field(default_factory=list)
