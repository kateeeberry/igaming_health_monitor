"""Генератор СИНТЕТИЧНОГО iGaming-датасету для проєкту «Health & Abuse Monitor».

Усе вигадано: гравців, пристроїв, суми. Реальних даних і PII немає.
Датасет: 3 000 гравців, 70 днів (пн 2026-08-10 .. нд 2026-10-18 = 10 повних тижнів).

Таблиці (створюються окремо від навчальної бази й від старих демо-таблиць):
  players(player_id, device_id, ftd_date)
  player_game_daily(player_id, activity_date, game_category, bets_count,
                    real_bet_amount, bonus_bet_amount, win_amount)
  player_cash_daily(player_id, activity_date, deposit_count, deposit_amount, withdrawal_amount)
  ground_truth(player_id, is_abuser, pattern)   <- «правильні відповіді»; правила їх НЕ бачать
  daily_performance (VIEW над player_game_daily)

Закладені патерни (ground_truth.pattern):
  порушники: bonus_abuser, win_spike, fast_withdrawal, multi_account
  «пастки» для хибних спрацювань (is_abuser = false): decoy_high_roller, decoy_bonus_lover,
  decoy_shared_device, decoy_lucky_win; решта: normal.

Запуск:
  python generate_synthetic.py                 # лише генерація + перевірки + CSV у ./out (БД не чіпає)
  python generate_synthetic.py --write         # ще й запис у синтетичну БД (SYNTH_DATABASE_URL у .env)

Модель спрощена (див. коментарі): ціль не фінансова точність, а правдоподібні розподіли й відомі
порушники для перевірки правил. Рядок підключення береться ЛИШЕ з .env (SYNTH_DATABASE_URL).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 20261020
N_PLAYERS = 3000
START = date(2026, 8, 10)  # понеділок
DAYS = 70
CATS = ["Slots", "Live Casino", "Table Games"]
RTP = {"Slots": 0.917, "Live Casino": 0.97, "Table Games": 0.98}  # номінальний RTP
CV_BET = {"Slots": 4.0, "Live Casino": 1.2, "Table Games": 1.0}  # волатильність однієї ставки
HIT_P, HIT_MULT = 0.004, (5.0, 15.0)  # рідкісні великі виграші у слотах (природний шум, не порушення)
AVG_BET = {"Slots": 1.0, "Live Casino": 5.0, "Table Games": 4.0}
CAMPAIGN_DAYS = range(49, 56)  # 2026-09-28 .. 2026-10-04: бонусна кампанія для всіх
COURSE_DB_HOST_MARKER = "ep-sparkling-cake-b1u3cnah"  # навчальна БД курсу: сюди писати ЗАБОРОНЕНО

ROLE_COUNTS = {
    "bonus_abuser": 30,
    "win_spike": 10,
    "fast_withdrawal": 30,
    "multi_account": 32,  # 8 груп по 4 акаунти з одним device_id
    "decoy_high_roller": 20,
    "decoy_bonus_lover": 30,
    "decoy_shared_device": 20,  # 10 пар (легітимно: сім'я/спільний пристрій)
    "decoy_lucky_win": 15,
}
ABUSER_ROLES = {"bonus_abuser", "win_spike", "fast_withdrawal", "multi_account"}
LOOP_ROLES = {"normal", "decoy_high_roller", "decoy_bonus_lover", "decoy_shared_device",
              "decoy_lucky_win", "win_spike"}  # решта генерується окремо


def d(day_idx: int) -> date:
    return START + timedelta(days=int(day_idx))


def day_ratio(rng, cat, t):
    """Відношення виграш/ставка за день для одного гравця (спеціальні ролі)."""
    bets = max(1.0, t / AVG_BET[cat])
    shape = max(0.3, bets / CV_BET[cat] ** 2)
    return rng.gamma(shape, RTP[cat] / shape)


def money(x):
    return np.round(x, 2)


def generate(rng: np.random.Generator):
    n = N_PLAYERS
    ids = np.array([f"P{i + 1:05d}" for i in range(n)])

    # --- ролі випадково розкидані по ID, щоб ID нічого не підказував -----------------
    roles = np.array(["normal"] * n, dtype=object)
    order = rng.permutation(n)
    pos = 0
    role_idx: dict[str, np.ndarray] = {}
    for role, cnt in ROLE_COUNTS.items():
        role_idx[role] = order[pos:pos + cnt]
        roles[role_idx[role]] = role
        pos += cnt

    # --- пристрої: за замовчуванням один унікальний на гравця -------------------------
    dev_ids = rng.permutation(n * 2)[:n]
    device = np.array([f"DV{x:05d}" for x in dev_ids], dtype=object)
    ma = role_idx["multi_account"].reshape(8, 4)  # 8 груп по 4
    for g in range(8):
        device[ma[g]] = f"DV{90000 + g}"
    sd = role_idx["decoy_shared_device"].reshape(10, 2)
    for g in range(10):
        device[sd[g]] = f"DV{95000 + g}"

    # --- FTD: 60% «старі» (FTD до вікна), 40% нові; порушники -- нові, останні ~6 тижнів ----
    ftd_day = np.where(rng.random(n) < 0.6, -rng.integers(1, 400, n), rng.integers(0, DAYS, n))
    for role in ("bonus_abuser", "fast_withdrawal"):
        ftd_day[role_idx[role]] = rng.integers(28, 62, len(role_idx[role]))
    ftd_day[role_idx["win_spike"]] = rng.integers(0, 40, len(role_idx["win_spike"]))  # спершу звичайні
    grp_start = rng.integers(30, 58, 8)
    for g in range(8):
        ftd_day[ma[g]] = grp_start[g] + rng.integers(0, 3, 4)

    # --- параметри поведінки ---------------------------------------------------------------
    p_active = rng.beta(2, 5, n)                      # частота активних днів
    churn_day = np.where(rng.random(n) < 0.25, rng.integers(10, DAYS, n), 10_000)
    dep_med = np.exp(rng.normal(np.log(40), 0.7, n))  # типовий депозит
    dep_base = dep_med.copy()                         # базовий масштаб (для обороту)
    reload_p = rng.beta(2, 6, n)                      # ймовірність поповнення в активний день
    abf = np.exp(rng.normal(0, 0.4, n))               # множник середньої ставки
    prefs = rng.dirichlet([7, 2, 1], n)
    cum = np.cumsum(prefs, axis=1)
    turn_mult = np.ones(n)
    turn_mult[role_idx["decoy_high_roller"]] = 15.0
    dep_med[role_idx["decoy_high_roller"]] *= 25.0
    bonus_prob = np.full(n, 0.08)
    bonus_prob[role_idx["decoy_bonus_lover"]] = 0.6
    bonus_lo = np.full(n, 0.10)
    bonus_hi = np.full(n, 0.50)
    bonus_lo[role_idx["decoy_bonus_lover"]] = 0.40
    bonus_hi[role_idx["decoy_bonus_lover"]] = 0.65
    in_loop = np.isin(roles, list(LOOP_ROLES))

    game_parts: list[pd.DataFrame] = []
    cash_parts: list[pd.DataFrame] = []

    # =============== основний цикл по днях (векторизовано по гравцях) ===================
    for day in range(DAYS):
        dow = d(day).weekday()
        factor = 1.0 + 0.25 * (dow >= 5) - 0.10 * (dow == 0)
        if day in CAMPAIGN_DAYS:
            factor *= 1.15
        eligible = in_loop & (ftd_day <= day) & (day < churn_day)
        active = eligible & (rng.random(n) < np.clip(p_active * factor, 0, 0.95))
        ftd_today = in_loop & (ftd_day == day)
        reload_ = active & (ftd_day < day) & (rng.random(n) < reload_p)
        dep_flag = ftd_today | reload_
        # FTD-день: депозит завжди; гравець грає в цей день з імовірністю 0.9
        active = active | (ftd_today & (rng.random(n) < 0.9))

        dep_count = np.where(dep_flag, 1 + (rng.random(n) < 0.05), 0)
        dep_amt = np.where(dep_flag, dep_count * dep_med * np.exp(rng.normal(0, 0.4, n)), 0.0)
        wd_amt = np.zeros(n)

        idx = np.flatnonzero(active)
        if len(idx):
            m = len(idx)
            t_total = dep_base[idx] * np.exp(rng.normal(np.log(4), 0.6, m)) * turn_mult[idx]
            bonus_p = np.where(day in CAMPAIGN_DAYS, np.maximum(bonus_prob[idx], 0.25), bonus_prob[idx])
            has_bonus = rng.random(m) < bonus_p
            share = np.where(has_bonus, rng.uniform(bonus_lo[idx], bonus_hi[idx]), 0.0)
            cat1 = (rng.random(m)[:, None] > cum[idx]).sum(1).clip(0, 2)
            two = rng.random(m) < 0.2
            cat2 = (cat1 + rng.integers(1, 3, m)) % 3
            net_real = np.zeros(m)
            for part_cat, part_share, mask in ((cat1, np.where(two, 0.6, 1.0), np.ones(m, bool)),
                                               (cat2, np.full(m, 0.4), two)):
                sel = np.flatnonzero(mask)
                if not len(sel):
                    continue
                cat_names = np.array(CATS)[part_cat[sel]]
                t_c = t_total[sel] * part_share[sel]
                bonus = t_c * share[sel]
                real = t_c - bonus
                avg_bet = np.array([AVG_BET[c] for c in cat_names]) * abf[idx[sel]]
                bets = np.maximum(1, np.rint(t_c / avg_bet)).astype(int)
                cv = np.array([CV_BET[c] for c in cat_names])
                shape = np.maximum(0.3, bets / cv ** 2)  # більше ставок -> менший розкид RTP за день
                rtp = np.array([RTP[c] for c in cat_names])
                ratio = rng.gamma(shape, rtp / shape)
                hit = (cat_names == "Slots") & (rng.random(len(sel)) < HIT_P)
                ratio = np.where(hit, ratio * rng.uniform(*HIT_MULT, len(sel)), ratio)
                win = t_c * ratio
                net_real[sel] += win * (1 - share[sel]) - real
                game_parts.append(pd.DataFrame({
                    "player_id": ids[idx[sel]], "activity_date": d(day), "game_category": cat_names,
                    "bets_count": bets, "real_bet_amount": money(real), "bonus_bet_amount": money(bonus),
                    "win_amount": money(win)}))
            # звичайні виводи: частина виграшних днів
            wd = (net_real > 0) & (rng.random(m) < 0.35)
            wd_amt[idx] = np.where(wd, rng.uniform(0.4, 0.95, m) * net_real, 0.0)

        cash_mask = (dep_count > 0) | (wd_amt > 0)
        if cash_mask.any():
            cash_parts.append(pd.DataFrame({
                "player_id": ids[cash_mask], "activity_date": d(day),
                "deposit_count": dep_count[cash_mask].astype(int),
                "deposit_amount": money(dep_amt[cash_mask]), "withdrawal_amount": money(wd_amt[cash_mask])}))

    # =============== спеціальні ролі ====================================================
    extra_game: list[dict] = []
    extra_cash: list[dict] = []

    def add_game(pid, day, cat, bets, real, bonus, win):
        extra_game.append(dict(player_id=pid, activity_date=d(day), game_category=cat, bets_count=int(bets),
                               real_bet_amount=round(float(real), 2), bonus_bet_amount=round(float(bonus), 2),
                               win_amount=round(float(win), 2)))

    def add_cash(pid, day, dep_cnt=0, dep=0.0, wd=0.0):
        extra_cash.append(dict(player_id=pid, activity_date=d(day), deposit_count=int(dep_cnt),
                               deposit_amount=round(float(dep), 2), withdrawal_amount=round(float(wd), 2)))

    # bonus_abuser: майже всі ставки за бонусні гроші, кілька виводів
    for i in role_idx["bonus_abuser"]:
        pid, f0 = ids[i], int(ftd_day[i])
        add_cash(pid, f0, 1, rng.uniform(20, 50))
        days = np.sort(rng.choice(np.arange(f0, DAYS), size=min(DAYS - f0, rng.integers(8, 21)), replace=False))
        total_wins = []
        for day in days:
            t = rng.uniform(60, 300)
            s = rng.uniform(0.85, 0.98)
            cat = "Slots" if rng.random() < 0.7 else "Live Casino"
            win = t * day_ratio(rng, cat, t)
            add_game(pid, day, cat, max(1, round(t / AVG_BET[cat])), t * (1 - s), t * s, win)
            total_wins.append((day, win - t))
        for day, extra in [x for x in total_wins if x[1] > 0][:4]:
            add_cash(pid, day, 0, 0, rng.uniform(0.5, 0.9) * extra)

    # fast_withdrawal: депозит -> мінімальний відіграш -> вивід за 0-1 день, повтор
    for i in role_idx["fast_withdrawal"]:
        pid, day = ids[i], int(ftd_day[i])
        for _ in range(int(rng.integers(3, 9))):
            if day > DAYS - 2:
                break
            dep = rng.uniform(30, 150)
            real = dep * rng.uniform(0.6, 1.4)
            bonus = dep * rng.uniform(1, 3)
            cat = "Live Casino" if rng.random() < 0.5 else "Table Games"
            win = (real + bonus) * rng.uniform(0.93, 0.99)
            add_cash(pid, day, 1, dep)
            add_game(pid, day, cat, max(1, round((real + bonus) / AVG_BET[cat])), real, bonus, win)
            add_cash(pid, day + int(rng.integers(0, 2)), 0, 0, rng.uniform(0.85, 1.0) * (dep + 0.3 * bonus))
            day += int(rng.integers(2, 6))

    # multi_account: групи акаунтів з одним device_id, короткі бонусні сесії
    for g in range(8):
        for i in ma[g]:
            pid, f0 = ids[i], int(ftd_day[i])
            add_cash(pid, f0, 1, rng.uniform(20, 40))
            span = np.arange(f0, min(DAYS, f0 + 15))
            days = np.sort(rng.choice(span, size=min(len(span), int(rng.integers(4, 11))), replace=False))
            wins = 0.0
            for day in days:
                t = rng.uniform(30, 120)
                s = rng.uniform(0.6, 0.9)
                win = t * day_ratio(rng, "Slots", t)
                wins += max(0.0, win - t)
                add_game(pid, day, "Slots", max(1, round(t / AVG_BET["Slots"])), t * (1 - s), t * s, win)
            if wins > 0:
                add_cash(pid, int(days[-1]), 0, 0, rng.uniform(0.6, 1.0) * wins)

    # win_spike: звичайна гра (з циклу) + один день з дуже великим виграшем і виводом наступного дня.
    # Перший гравець -- «демо-подія» 16.10.2026 (день 67): ставка 3200, виграш 32500.
    for k, i in enumerate(role_idx["win_spike"]):
        pid = ids[i]
        if k == 0:
            day, bet, win = 67, 3200.0, 32500.0
        else:
            day = min(68, max(int(rng.integers(40, 69)), int(ftd_day[i])))  # не раніше FTD
            bet = float(rng.uniform(100, 400))
            win = bet * float(rng.uniform(20, 40))
        add_game(pid, day, "Slots", max(1, round(bet / 2)), bet, 0.0, win)
        add_cash(pid, day, 1, bet * rng.uniform(0.2, 0.5))
        add_cash(pid, day + 1, 0, 0, rng.uniform(0.7, 1.0) * (win - bet))

    # decoy_lucky_win: невеликий гравець, один випадковий помірний виграш (без патерну виведення)
    for i in role_idx["decoy_lucky_win"]:
        pid = ids[i]
        day = max(int(rng.integers(35, 70)), int(ftd_day[i]))  # не раніше FTD
        bet = float(rng.uniform(20, 100))
        add_game(pid, day, "Slots", max(1, round(bet)), bet, 0.0, bet * float(rng.uniform(12, 25)))
        add_cash(pid, day, 1, bet * 0.5)

    # --- збираємо таблиці ------------------------------------------------------------------
    game = pd.concat(game_parts + [pd.DataFrame(extra_game)], ignore_index=True)
    key = ["player_id", "activity_date", "game_category"]
    game = game.groupby(key, as_index=False).sum(numeric_only=True)
    cash = pd.concat(cash_parts + [pd.DataFrame(extra_cash)], ignore_index=True)
    cash = cash.groupby(["player_id", "activity_date"], as_index=False).sum(numeric_only=True)
    for c in ("bets_count",):
        game[c] = game[c].astype(int)
    for c in ("real_bet_amount", "bonus_bet_amount", "win_amount"):
        game[c] = game[c].round(2)
    for c in ("deposit_count",):
        cash[c] = cash[c].astype(int)
    for c in ("deposit_amount", "withdrawal_amount"):
        cash[c] = cash[c].round(2)

    # FTD-день для кожного гравця має відповідати першому депозиту в вікні (для нових)
    players = pd.DataFrame({"player_id": ids, "device_id": device,
                            "ftd_date": [d(x) if x >= 0 else START + timedelta(days=int(x)) for x in ftd_day]})
    truth = pd.DataFrame({
        "player_id": ids,
        "is_abuser": [r in ABUSER_ROLES for r in roles],
        "pattern": roles})
    return players, game, cash, truth


# ======================= перевірки (незалежний перерахунок із DataFrame) ==================


def validate(players, game, cash, truth) -> None:
    print("\n=== ПЕРЕВІРКИ ===")
    assert players.player_id.is_unique and truth.player_id.is_unique
    assert not game.duplicated(["player_id", "activity_date", "game_category"]).any()
    assert not cash.duplicated(["player_id", "activity_date"]).any()
    assert (game[["bets_count", "real_bet_amount", "bonus_bet_amount", "win_amount"]] >= 0).all().all()
    assert (cash[["deposit_count", "deposit_amount", "withdrawal_amount"]] >= 0).all().all()
    assert set(game.player_id) <= set(players.player_id) and set(cash.player_id) <= set(players.player_id)
    print(f"гравців: {len(players)}, рядків game: {len(game)}, рядків cash: {len(cash)}")
    print("порушників (ground_truth):", int(truth.is_abuser.sum()),
          "| патерни:", truth.pattern.value_counts().to_dict())

    g = game.copy()
    g["stake"] = g.real_bet_amount + g.bonus_bet_amount
    g["week"] = [((x - START).days // 7) + 1 for x in g.activity_date]
    wk = g.groupby("week").agg(stake=("stake", "sum"), win=("win_amount", "sum"), bonus=("bonus_bet_amount", "sum"),
                               players=("player_id", "nunique"), bets=("bets_count", "sum"))
    wk["ggr"] = wk.stake - wk.win
    wk["rtp_pct"] = (100 * wk.win / wk.stake).round(2)
    wk["bonus_share_pct"] = (100 * wk.bonus / wk.stake).round(2)
    print("\nпо тижнях (ставки/виграші/GGR/RTP/бонус-частка):")
    print(wk[["players", "bets", "stake", "win", "ggr", "rtp_pct", "bonus_share_pct"]].round(0).to_string())
    print("\nRTP по категоріях за весь період:")
    cat = g.groupby("game_category").agg(stake=("stake", "sum"), win=("win_amount", "sum"))
    print((100 * cat.win / cat.stake).round(2).to_string())
    print("\nнайбільша денна «чиста перемога» гравця (win - stake), топ-5:")
    pl = g.groupby(["player_id", "activity_date"], as_index=False).agg(stake=("stake", "sum"), win=("win_amount", "sum"))
    pl["net"] = pl.win - pl.stake
    top = pl.sort_values("net", ascending=False).head(5).merge(truth, on="player_id")
    print(top[["activity_date", "stake", "win", "net", "pattern"]].round(0).to_string(index=False))
    dev = players.groupby("device_id").player_id.count()
    print(f"\nпристроїв із >1 акаунтом: {(dev > 1).sum()} (очікувано 8 груп порушників + 10 легітимних пар = 18)")
    print(f"гравців із ≥2 депозитами у вікні: {(cash.groupby('player_id').deposit_count.sum() >= 2).sum()}")


# ============================ запис у БД ==================================================

DDL = [
    "DROP VIEW IF EXISTS daily_performance",
    "DROP TABLE IF EXISTS ground_truth, player_cash_daily, player_game_daily, players",
    """CREATE TABLE players (
        player_id VARCHAR(20) PRIMARY KEY, device_id VARCHAR(20) NOT NULL, ftd_date DATE NOT NULL)""",
    """CREATE TABLE player_game_daily (
        player_id VARCHAR(20) NOT NULL REFERENCES players(player_id),
        activity_date DATE NOT NULL, game_category VARCHAR(30) NOT NULL,
        bets_count INT NOT NULL, real_bet_amount NUMERIC(14,2) NOT NULL,
        bonus_bet_amount NUMERIC(14,2) NOT NULL, win_amount NUMERIC(14,2) NOT NULL,
        PRIMARY KEY (player_id, activity_date, game_category))""",
    """CREATE TABLE player_cash_daily (
        player_id VARCHAR(20) NOT NULL REFERENCES players(player_id),
        activity_date DATE NOT NULL, deposit_count INT NOT NULL,
        deposit_amount NUMERIC(14,2) NOT NULL, withdrawal_amount NUMERIC(14,2) NOT NULL,
        PRIMARY KEY (player_id, activity_date))""",
    """CREATE TABLE ground_truth (
        player_id VARCHAR(20) PRIMARY KEY REFERENCES players(player_id),
        is_abuser BOOLEAN NOT NULL, pattern VARCHAR(30) NOT NULL)""",
]
VIEW = """
CREATE VIEW daily_performance AS
SELECT g.activity_date AS report_date,
       ((g.activity_date - DATE '2026-08-10') / 7 + 1) AS week_num,
       g.game_category,
       COUNT(DISTINCT g.player_id) AS active_players,
       SUM(g.bets_count) AS total_bets_count,
       SUM(g.real_bet_amount) AS real_bet_amount,
       SUM(g.bonus_bet_amount) AS bonus_bet_amount,
       SUM(g.real_bet_amount + g.bonus_bet_amount) AS bet_amount,
       SUM(g.win_amount) AS win_amount,
       SUM(g.real_bet_amount + g.bonus_bet_amount - g.win_amount) AS ggr,
       ROUND(100.0 * SUM(g.win_amount) / NULLIF(SUM(g.real_bet_amount + g.bonus_bet_amount), 0), 2) AS rtp_pct
FROM player_game_daily g
GROUP BY g.activity_date, g.game_category
"""


def write_db(players, game, cash, truth) -> None:
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text

    load_dotenv()
    url = os.getenv("SYNTH_DATABASE_URL")
    if not url:
        sys.exit("SYNTH_DATABASE_URL не знайдено в .env (рядок підключення до СИНТЕТИЧНОЇ бази).")
    if COURSE_DB_HOST_MARKER in url:
        sys.exit("СТОП: це навчальна БД курсу. У неї писати не можна. Вкажіть синтетичну базу.")
    engine = create_engine(url)
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
    for name, df in (("players", players), ("player_game_daily", game),
                     ("player_cash_daily", cash), ("ground_truth", truth)):
        df.to_sql(name, engine, if_exists="append", index=False, method="multi", chunksize=2000)
        print(f"записано {name}: {len(df)} рядків")
    try:
        with engine.begin() as conn:
            conn.execute(text(VIEW))
        print("створено view daily_performance")
    except Exception as exc:  # noqa: BLE001
        print(f"УВАГА: view не створено ({type(exc).__name__}: {str(exc).splitlines()[0][:200]})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="записати у синтетичну БД (SYNTH_DATABASE_URL)")
    ap.add_argument("--out", default="out", help="папка для CSV (за замовчуванням ./out)")
    args = ap.parse_args()

    rng = np.random.default_rng(SEED)
    players, game, cash, truth = generate(rng)
    validate(players, game, cash, truth)

    os.makedirs(args.out, exist_ok=True)
    for name, df in (("players", players), ("player_game_daily", game),
                     ("player_cash_daily", cash), ("ground_truth", truth)):
        df.to_csv(os.path.join(args.out, f"{name}.csv"), index=False)
    print(f"\nCSV збережено в ./{args.out}/")
    if args.write:
        write_db(players, game, cash, truth)
    else:
        print("БД не чіпали (запустіть з --write, щоб записати).")


if __name__ == "__main__":
    main()
