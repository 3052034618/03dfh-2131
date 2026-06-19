from typing import List, Tuple, Dict, Any
from datetime import datetime
import re

from models import Car, Player, Registration
from storage import get_player


class MatchIssue:
    def __init__(self, category: str, message: str, severity: str = "warning"):
        self.category = category
        self.message = message
        self.severity = severity

    def __str__(self):
        return f"[{self.category}] {self.message}"


class MatchResult:
    def __init__(self, registration: Registration, player: Player):
        self.registration = registration
        self.player = player
        self.issues: List[MatchIssue] = []
        self.severity_score: int = 0

    def add_issue(self, category: str, message: str, severity: str = "warning"):
        self.issues.append(MatchIssue(category, message, severity))
        if severity == "critical":
            self.severity_score += 100
        elif severity == "warning":
            self.severity_score += 10
        else:
            self.severity_score += 1

    @property
    def has_critical(self) -> bool:
        return any(i.severity == "critical" for i in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    @property
    def match_score(self) -> int:
        base = 1000
        if self.player.experience_count >= 5:
            base += 20
        elif self.player.experience_count >= 3:
            base += 10
        if self.player.accept_crosscast:
            base += 5
        return base - self.severity_score


def _parse_time_availability(avail_str: str) -> Tuple[int, int]:
    """解析玩家的可到时间描述，返回 (最早分钟, 最晚分钟)，失败返回 (-1, -1)"""
    if not avail_str:
        return (0, 48 * 60)
    s = avail_str.strip()
    if any(k in s for k in ("随时", "都可", "都可以", "任意", "全天", "不限", "任何时候", "救场")):
        return (0, 48 * 60)

    def _hm(h: str, m: str) -> int:
        return int(h or 0) * 60 + int(m or 0)

    text = avail_str.strip()

    m = re.search(
        r"(\d{1,2})(?:[:：点](\d{1,2}))?\s*(?:~|～|-|—|到|至|\-)\s*(\d{1,2})(?:[:：点](\d{1,2}))?",
        text,
    )
    if m:
        try:
            start = _hm(m.group(1), m.group(2))
            end = _hm(m.group(3), m.group(4))
            if end <= start:
                end += 24 * 60
            return (start, max(end, start + 60))
        except (ValueError, TypeError):
            pass

    m = re.search(r"(\d{1,2})(?:[:：点](\d{0,2}))?(?:之|以)?后", text)
    if m:
        try:
            return (_hm(m.group(1), m.group(2)), 48 * 60)
        except (ValueError, TypeError):
            pass

    m = re.search(r"(?:之|以)?前.*?(\d{1,2})(?:[:：点](\d{0,2}))?", text)
    if m:
        try:
            return (0, _hm(m.group(1), m.group(2)))
        except (ValueError, TypeError):
            pass

    m = re.search(r"(\d{1,2})(?:[:：点](\d{0,2}))?(?:之|以)?前", text)
    if m:
        try:
            return (0, _hm(m.group(1), m.group(2)))
        except (ValueError, TypeError):
            pass

    m = re.search(r"(\d{1,2})(?:[:：点](\d{0,2}))?", text)
    if m:
        try:
            t = _hm(m.group(1), m.group(2))
            return (max(0, t - 90), t + 180)
        except (ValueError, TypeError):
            pass
    return (-1, -1)


def check_time_match(car: Car, player: Player) -> List[MatchIssue]:
    issues = []
    avail_min, avail_max = _parse_time_availability(player.available_time)
    if avail_min < 0:
        issues.append(MatchIssue(
            "time",
            f"可到时间「{player.available_time}」无法自动解析，请人工核对",
            "warning"
        ))
        return issues

    car_min = car.start_time.hour * 60 + car.start_time.minute
    duration_min = int(car.duration_hours * 60)
    car_end = car_min + duration_min

    if avail_min > 0 and car_min < avail_min:
        gap = max(1, (avail_min - car_min + 30) // 60)
        issues.append(MatchIssue(
            "time",
            f"开场时间早于玩家可到时间约{gap}小时",
            "critical"
        ))
    if avail_max < 36 * 60 and car_end > avail_max + 60:
        gap = max(1, (car_end - avail_max + 30) // 60)
        issues.append(MatchIssue(
            "time",
            f"散场时间晚于玩家可到晚点约{gap}小时",
            "warning"
        ))
    return issues


def check_gender_role_match(car: Car, player: Player) -> List[MatchIssue]:
    issues = []
    constraints = (car.role_constraints or "").strip()
    if not constraints:
        return issues

    const_lower = constraints
    gender = (player.gender or "").strip()

    has_male_role = "男" in const_lower or "♂" in const_lower
    has_female_role = "女" in const_lower or "♀" in const_lower

    require_no_crosscast = any(k in const_lower for k in ["不接受反串", "禁止反串", "不可反串", "严禁反串"])
    strict_male_only = any(k in const_lower for k in ["必须男", "必男", "硬性要求男", "需男"])
    strict_female_only = any(k in const_lower for k in ["必须女", "必女", "硬性要求女", "需女"])
    only_male_roles = has_male_role and not has_female_role
    only_female_roles = has_female_role and not has_male_role

    if (strict_male_only or only_male_roles) and gender != "男" and not player.accept_crosscast:
        sev = "critical" if strict_male_only else "warning"
        issues.append(MatchIssue(
            "role",
            f"本车配置「{constraints}」需男性，玩家{player.nickname}性别{gender}且不接受反串",
            sev
        ))
    elif (strict_female_only or only_female_roles) and gender != "女" and not player.accept_crosscast:
        sev = "critical" if strict_female_only else "warning"
        issues.append(MatchIssue(
            "role",
            f"本车配置「{constraints}」需女性，玩家{player.nickname}性别{gender}且不接受反串",
            sev
        ))
    elif require_no_crosscast:
        other_gender_roles = has_female_role if gender == "男" else has_male_role
        if not player.accept_crosscast and other_gender_roles:
            pass
    return issues


def check_book_read_rule(car: Car, player: Player) -> List[MatchIssue]:
    issues = []
    if car.require_unread and player.read_this_book:
        issues.append(MatchIssue(
            "book",
            f"本车要求未读本，玩家{player.nickname}已读本《{car.name}》",
            "critical"
        ))
    return issues


def check_experience(car: Car, player: Player) -> List[MatchIssue]:
    issues = []
    if car.min_experience > 0 and player.experience_count < car.min_experience:
        issues.append(MatchIssue(
            "experience",
            f"本车要求≥{car.min_experience}个硬核本经验，玩家仅{player.experience_count}个",
            "warning"
        ))
    return issues


def check_notes_conflict(car: Car, player: Player) -> List[MatchIssue]:
    issues = []
    if not player.notes:
        return issues

    trigger_words = [
        ("迟到", "有迟到前科需留意"),
        ("跳车", "有跳车记录，高风险"),
        ("天眼", "天眼玩家，严重警告"),
        ("挂机", "容易挂机，可能影响体验"),
        ("杠精", "有抬杠倾向"),
        ("社交", "社恐/社牛描述需确认气氛匹配"),
        ("情感", "偏好情感本，硬核对其可能较吃力"),
    ]
    for keyword, desc in trigger_words:
        if keyword in player.notes:
            sev = "critical" if keyword in ("跳车", "天眼") else "warning"
            issues.append(MatchIssue("notes", f"备注雷点「{keyword}」：{desc}", sev))
    return issues


def analyze_match(car: Car, registration: Registration, player: Player) -> MatchResult:
    result = MatchResult(registration, player)
    for issue in check_book_read_rule(car, player):
        result.issues.append(issue)
        if issue.severity == "critical":
            result.severity_score += 100
        elif issue.severity == "warning":
            result.severity_score += 10
    for issue in check_gender_role_match(car, player):
        result.issues.append(issue)
        if issue.severity == "critical":
            result.severity_score += 100
        elif issue.severity == "warning":
            result.severity_score += 10
    for issue in check_time_match(car, player):
        result.issues.append(issue)
        if issue.severity == "critical":
            result.severity_score += 100
        elif issue.severity == "warning":
            result.severity_score += 10
    for issue in check_experience(car, player):
        result.issues.append(issue)
        if issue.severity == "critical":
            result.severity_score += 100
        elif issue.severity == "warning":
            result.severity_score += 10
    for issue in check_notes_conflict(car, player):
        result.issues.append(issue)
        if issue.severity == "critical":
            result.severity_score += 100
        elif issue.severity == "warning":
            result.severity_score += 10
    return result


def triage_registrations(db, car: Car, registrations: List[Registration]) -> Dict[str, List[MatchResult]]:
    results = []
    for reg in registrations:
        player = get_player(db, reg.player_id)
        if player:
            results.append(analyze_match(car, reg, player))

    conflict = [r for r in results if r.has_critical]
    conflict.sort(key=lambda x: x.severity_score, reverse=True)

    warning = [r for r in results if not r.has_critical and r.has_warning]
    warning.sort(key=lambda x: x.severity_score, reverse=True)

    match = [r for r in results if not r.has_critical and not r.has_warning]
    match.sort(key=lambda x: x.match_score, reverse=True)

    return {"conflict": conflict, "warning": warning, "match": match}
