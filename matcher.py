from typing import List, Tuple, Dict, Any
from datetime import datetime
import re

from models import Car, Player, Registration


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
        if self.registration.effective_accept_crosscast(self.player):
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
        r"(\d{1,2})(?:[:：点](\d{0,2}))?\s*(?:~|～|-|—|到|至|\-)\s*(\d{1,2})(?:[:：点](\d{0,2}))?",
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


def check_time_match(car: Car, registration: Registration, player: Player) -> List[MatchIssue]:
    issues = []
    avail_min, avail_max = _parse_time_availability(registration.available_time)
    if avail_min < 0:
        issues.append(MatchIssue(
            "time",
            f"可到时间「{registration.available_time}」无法自动解析，请人工核对",
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


def check_gender_role_match(car: Car, registration: Registration, player: Player) -> List[MatchIssue]:
    issues = []
    constraints = (car.role_constraints or "").strip()
    if not constraints:
        return issues

    const_lower = constraints
    gender = (player.gender or "").strip()
    accept_cc = registration.effective_accept_crosscast(player)

    has_male_role = "男" in const_lower or "♂" in const_lower
    has_female_role = "女" in const_lower or "♀" in const_lower

    strict_male_only = any(k in const_lower for k in ["必须男", "必男", "硬性要求男", "需男"])
    strict_female_only = any(k in const_lower for k in ["必须女", "必女", "硬性要求女", "需女"])
    only_male_roles = has_male_role and not has_female_role
    only_female_roles = has_female_role and not has_male_role

    if (strict_male_only or only_male_roles) and gender != "男" and not accept_cc:
        sev = "critical" if strict_male_only else "warning"
        issues.append(MatchIssue(
            "role",
            f"本车配置「{constraints}」需男性，玩家{player.nickname}性别{gender}且不接受反串",
            sev
        ))
    elif (strict_female_only or only_female_roles) and gender != "女" and not accept_cc:
        sev = "critical" if strict_female_only else "warning"
        issues.append(MatchIssue(
            "role",
            f"本车配置「{constraints}」需女性，玩家{player.nickname}性别{gender}且不接受反串",
            sev
        ))
    return issues


def check_book_read_rule(car: Car, registration: Registration, player: Player) -> List[MatchIssue]:
    issues = []
    if car.require_unread and registration.read_this_book:
        issues.append(MatchIssue(
            "book",
            f"本车要求未读本，玩家{player.nickname}已读本《{car.name}》",
            "critical"
        ))
    return issues


def check_experience(car: Car, registration: Registration, player: Player) -> List[MatchIssue]:
    issues = []
    if car.min_experience > 0 and player.experience_count < car.min_experience:
        exp_str = f"{player.experience_count}个" if player.experience_count > 0 else "0个（萌新）"
        issues.append(MatchIssue(
            "experience",
            f"本车要求≥{car.min_experience}个硬核本经验，玩家仅{exp_str}",
            "warning"
        ))
    return issues


def check_notes_conflict(car: Car, registration: Registration, player: Player) -> List[MatchIssue]:
    issues = []
    if not registration.notes:
        return issues

    trigger_words = [
        ("迟到", "有迟到前科需留意"),
        ("跳车", "有跳车记录，高风险"),
        ("天眼", "天眼玩家，严重警告"),
        ("挂机", "容易挂机，可能影响体验"),
        ("杠精", "有抬杠倾向"),
        ("社交", "社恐/社牛描述需确认气氛匹配"),
        ("情感", "偏好情感本，硬核对其可能较吃力"),
        ("鸽子", "有放鸽子记录"),
    ]
    for keyword, desc in trigger_words:
        if keyword in registration.notes:
            sev = "critical" if keyword in ("跳车", "天眼", "鸽子") else "warning"
            issues.append(MatchIssue("notes", f"备注雷点「{keyword}」：{desc}", sev))
    return issues


def analyze_match(car: Car, registration: Registration, player: Player) -> MatchResult:
    result = MatchResult(registration, player)

    checks = [
        check_book_read_rule,
        check_gender_role_match,
        check_time_match,
        check_experience,
        check_notes_conflict,
    ]
    for check_fn in checks:
        for issue in check_fn(car, registration, player):
            result.issues.append(issue)
            if issue.severity == "critical":
                result.severity_score += 100
            elif issue.severity == "warning":
                result.severity_score += 10
            else:
                result.severity_score += 1
    return result


def triage_registrations(db, car: Car, registrations: List[Registration],
                         filter_status: str = "all",
                         sort_by: str = "score") -> Dict[str, List[MatchResult]]:
    """
    分诊 + 筛选 + 排序
    filter_status: all / pending / eligible（可进正车，无critical）/ approved / bench
    sort_by: score / experience / time / created
    """
    from storage import get_player

    results = []
    for reg in registrations:
        player = get_player(db, reg.player_id)
        if not player:
            continue
        results.append(analyze_match(car, reg, player))

    # --- 筛选 ---
    if filter_status == "pending":
        results = [r for r in results if r.registration.status == "pending"]
    elif filter_status == "eligible":
        results = [r for r in results if not r.has_critical]
    elif filter_status == "approved":
        results = [r for r in results if r.registration.status == "approved"]
    elif filter_status == "bench":
        results = [r for r in results if r.registration.status == "bench"]
    elif filter_status == "conflict":
        results = [r for r in results if r.has_critical]

    # --- 排序 ---
    def _time_key(r: MatchResult) -> int:
        mn, _ = _parse_time_availability(r.registration.available_time)
        return mn if mn >= 0 else 99999

    if sort_by == "experience":
        results.sort(key=lambda r: r.player.experience_count, reverse=True)
    elif sort_by == "time":
        results.sort(key=_time_key)
    elif sort_by == "created":
        results.sort(key=lambda r: r.registration.created_at)
    else:  # score（默认）
        results.sort(key=lambda r: r.match_score, reverse=True)

    # --- 三段式 ---
    conflict = [r for r in results if r.has_critical]
    warning = [r for r in results if not r.has_critical and r.has_warning]
    match = [r for r in results if not r.has_critical and not r.has_warning]

    return {"conflict": conflict, "warning": warning, "match": match, "all": results}
