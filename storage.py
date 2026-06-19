import json
import os
from typing import Optional, List
from datetime import datetime

from models import (
    Database, Car, Player, Registration,
    EnhancedJSONEncoder, decode_datetime
)

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hardcore_cars.json")


def _ensure_data_dir():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)


def load_db() -> Database:
    _ensure_data_dir()
    if not os.path.exists(DB_FILE):
        return Database()
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f, object_hook=decode_datetime)
        cars = [Car(**c) for c in data.get("cars", [])]
        players = [Player(**p) for p in data.get("players", [])]
        registrations = [Registration(**r) for r in data.get("registrations", [])]
        return Database(cars=cars, players=players, registrations=registrations)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        print(f"[警告] 数据文件损坏，已创建新数据库: {e}")
        return Database()


def save_db(db: Database) -> None:
    _ensure_data_dir()
    data = {
        "cars": [c.__dict__ for c in db.cars],
        "players": [p.__dict__ for p in db.players],
        "registrations": [r.__dict__ for r in db.registrations],
    }
    tmp_file = DB_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, cls=EnhancedJSONEncoder)
    os.replace(tmp_file, DB_FILE)


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


def add_registration(db: Database, registration: Registration) -> Registration:
    existing = [
        r for r in db.registrations
        if r.car_id == registration.car_id and r.player_id == registration.player_id
    ]
    if existing:
        return existing[0]
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
