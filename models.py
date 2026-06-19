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

    @classmethod
    def create(cls, name, total_players, duration_hours, city, shop,
               start_time, role_constraints="", require_unread=False,
               min_experience=0):
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
        )


@dataclass
class Player:
    id: str
    nickname: str
    gender: str
    available_time: str
    past_hardcore_books: str
    accept_crosscast: bool = False
    notes: str = ""
    read_this_book: bool = False
    experience_count: int = 0
    registered_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(cls, nickname, gender, available_time, past_hardcore_books,
               accept_crosscast=False, notes="", read_this_book=False,
               experience_count=0):
        return cls(
            id=str(uuid.uuid4())[:8],
            nickname=nickname,
            gender=gender,
            available_time=available_time,
            past_hardcore_books=past_hardcore_books,
            accept_crosscast=bool(accept_crosscast),
            notes=notes,
            read_this_book=bool(read_this_book),
            experience_count=int(experience_count),
        )


@dataclass
class Registration:
    id: str
    car_id: str
    player_id: str
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(cls, car_id, player_id):
        return cls(
            id=str(uuid.uuid4())[:8],
            car_id=car_id,
            player_id=player_id,
        )


@dataclass
class Database:
    cars: List[Car] = field(default_factory=list)
    players: List[Player] = field(default_factory=list)
    registrations: List[Registration] = field(default_factory=list)
