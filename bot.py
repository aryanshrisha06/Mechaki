# StrategyBot - Zone Rush bot (single file, standard library only).
#
# Idea: every turn, score every cell I could work on as  (points it will earn me) / (turns it costs),
# walk to the best one, and use SHIELD only at the moment a rival is about to complete a take.
#
#   take neutral cell   : 1 stay
#   upgrade own cell    : 3 stays   (doubles the cell's income, and makes it hard to raid)
#   raid rival cell     : 1 stay (level 1) / 3 stays (upgraded) + one-off bonus 8*value*level
#
# Rival progress, shield cooldowns and scores are tracked from the board each turn.

PARAMS = {
    "w_deprive": 0.2,       # how much I value taking income away from a rival (vs. gaining it myself)
    "leader_boost": 1.5,    # extra weight on hurting the current leader
    "prior_shield": 2.0,    # prior "rival shielded when I attacked" count ...
    "prior_n": 5.0,         # ... out of this many attempts
    "shield_l1_min": 1,     # shield a level-1 cell only if its value >= this (4 = never)
    "comp_factor": 1.0,     # discount for neutral cells a rival can reach first
    "commit": 1.15,         # bonus for finishing the job I'm standing on
}

SIDE = 8
TURNS = 80
DIRS = (("NORTH", 0, -1), ("EAST", 1, 0), ("SOUTH", 0, 1), ("WEST", -1, 0))
_S = None


def _new_mem():
    return {
        "t": 0, "owned": 0, "transpose": False,
        "prev_owner": None, "prev_level": None, "prev_pos": None, "prev_action": None,
        "prev_cell_owner": None, "prev_frozen_me": False,
        "prog": 0, "est": {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0},
        "last_pos": {}, "age": {}, "prev_frozen": {}, "cd_until": {}, "frozen_until": {},
        "caught": {}, "attempts": {}, "arr": {}, "stay": {}, "tok": None,
    }


def _flatten(board):
    if board and isinstance(board[0], (list, tuple)):
        return [c for row in board for c in row]
    return list(board)


def _neighbors(n, side, transpose):
    nb = []
    for i in range(n):
        x, y = (i // side, i % side) if transpose else (i % side, i // side)
        d = {}
        for a, dx, dy in DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < side and 0 <= ny < side:
                d[a] = (nx * side + ny) if transpose else (ny * side + nx)
        nb.append(d)
    return nb


def _bfs(nb, src, blocked):
    dist, first = {src: 0}, {src: None}
    q = [src]
    h = 0
    while h < len(q):
        u = q[h]
        h += 1
        for a, v in nb[u].items():
            if v in dist or v in blocked:
                continue
            dist[v] = dist[u] + 1
            first[v] = first[u] or a
            q.append(v)
    return dist, first


def act(state):
    legal = list(state.legal_actions)
    try:
        a = _decide(state, legal)
        if a in legal:
            return a
    except Exception:
        pass
    return "STAY" if "STAY" in legal else legal[0]


def _decide(state, legal):
    global _S
    P = PARAMS
    cells = _flatten(state.board)
    n = len(cells)
    side = int(round(n ** 0.5))
    me = state.bot_id
    owner = [c.owner for c in cells]
    up = [bool(c.is_upgraded) for c in cells]
    lvl = [2 if u else 1 for u in up]
    val = [c.base_points for c in cells]
    home = [bool(c.is_home) for c in cells]
    pos = {}
    for i, c in enumerate(cells):
        if c.occupant:
            pos[c.occupant] = i
    mp = pos[me]

    owned = sum(1 for o in owner if o)
    if _S is None or owned < _S["owned"]:
        _S = _new_mem()
    S = _S
    S["owned"] = owned
    t = S["t"]
    R = TURNS - t

    # --- layout sanity check (row-major expected; fall back to transposed if legal moves disagree)
    moves_legal = {a for a in legal if a in ("NORTH", "EAST", "SOUTH", "WEST")}
    nb = _neighbors(n, side, S["transpose"])
    if not moves_legal <= set(nb[mp]):
        alt = _neighbors(n, side, not S["transpose"])
        if moves_legal <= set(alt[mp]):
            S["transpose"] = not S["transpose"]
            nb = alt

    frozen_me = legal == ["STAY"]
    if state.is_priority_token:
        S["tok"] = (t, me)

    # --- observe: estimated scores, rival tracking, own progress
    po, pl = S["prev_owner"], S["prev_level"]
    if po is not None:
        for b in range(1, 5):
            S["est"][b] += sum(val[i] * lvl[i] for i in range(n) if owner[i] == b)
        for i in range(n):
            if po[i] and owner[i] and owner[i] != po[i]:
                S["est"][owner[i]] += 8 * val[i] * pl[i]
    for r, j in pos.items():
        if r == me:
            continue
        if S["last_pos"].get(r) == j:
            S["age"][r] = S["age"].get(r, 1) + 1
        else:
            S["age"][r] = 1
            if po is not None and po[j] not in (0, r) and not home[j]:
                S["arr"][r] = S["arr"].get(r, 0) + 1
        if S["age"][r] == 2 and po is not None and po[j] not in (0, r) and not home[j]:
            S["stay"][r] = S["stay"].get(r, 0) + 1
        S["last_pos"][r] = j
        fr = bool(cells[j].is_frozen)
        if fr and not S["prev_frozen"].get(r):
            o = owner[j]
            shielder = o if o not in (0, r) else r
            S["cd_until"][shielder] = t + 3
            S["frozen_until"][r] = t + 1
        S["prev_frozen"][r] = fr

    # my progress on the cell I stand on
    if S["prev_pos"] == mp and S["prev_action"] == "STAY" and not S["prev_frozen_me"]:
        if owner[mp] == me and S["prev_cell_owner"] == me and not up[mp]:
            S["prog"] += 1
        elif owner[mp] != me:
            S["prog"] += 1
            S["attempts"] = S["attempts"]
            po_ = S["prev_cell_owner"]
            if po_ not in (None, 0, me):
                S["attempts"][po_] = S["attempts"].get(po_, 0) + 1
        else:
            S["prog"] = 0
    else:
        S["prog"] = 0
    if frozen_me:
        if S["prev_action"] == "STAY" and S["prev_pos"] == mp and owner[mp] not in (0, me):
            o = owner[mp]
            S["caught"][o] = S["caught"].get(o, 0) + 1
            S["cd_until"][o] = t + 3
        S["prog"] = 0

    def p_catch(r, turn_abs):
        if turn_abs <= S["cd_until"].get(r, -1):
            return 0.0
        a = S["attempts"].get(r, 0)
        c = S["caught"].get(r, 0)
        return (c + P["prior_shield"]) / (a + P["prior_n"])

    def q_stay(r):
        return (S["stay"].get(r, 0) + 2.0) / (S["arr"].get(r, 0) + 3.0)

    action = "STAY"
    if frozen_me:
        action = "STAY"
    else:
        action = _choose(state, S, P, legal, cells, nb, owner, up, lvl, val, home, pos, me, mp, t, R,
                         p_catch, q_stay, n)

    # --- bookkeeping for next turn
    S["prev_owner"] = owner
    S["prev_level"] = lvl
    S["prev_pos"] = mp
    S["prev_action"] = action
    S["prev_cell_owner"] = owner[mp]
    S["prev_frozen_me"] = frozen_me
    S["t"] = t + 1
    return action


def _choose(state, S, P, legal, cells, nb, owner, up, lvl, val, home, pos, me, mp, t, R,
            p_catch, q_stay, n):
    others = {r: j for r, j in pos.items() if r != me}
    leader = max(others, key=lambda r: S["est"][r]) if others else None

    # ---------------- shield: only when a rival completes a take on my land this turn
    if "SHIELD" in legal:
        for r, j in others.items():
            if owner[j] != me or home[j] or cells[j].is_frozen or S["frozen_until"].get(r, -1) >= t:
                continue
            need = 3 if up[j] else 1
            if S["age"].get(r, 1) - 1 + 1 < need:
                continue
            v = val[j]
            if need == 1:
                if v < P["shield_l1_min"] or R < 6:
                    continue
                if q_stay(r) < 0.5:
                    continue
            else:
                if q_stay(r) < 0.3:
                    continue
            # do not throw away a nearly finished capture of my own for a small cell
            if S["prog"] >= 1 and owner[mp] != me and v * lvl[j] < 6:
                continue
            return "SHIELD"

    # ---------------- planner
    blocked = set(others.values())
    dist, first = _bfs(nb, mp, blocked)
    rdist = {}
    for r, j in others.items():
        rdist[r], _ = _bfs(nb, j, set())

    best, best_rate = None, 0.0
    for i in range(n):
        if home[i] or i in blocked:
            continue
        d = 0 if i == mp else dist.get(i)
        if d is None:
            continue
        o = owner[i]
        v = val[i]
        if o == 0:
            kind, need = "take", 1
        elif o == me:
            if up[i]:
                continue
            kind, need = "up", 3
        else:
            kind, need = "raid", (3 if up[i] else 1)
            if cells[i].is_frozen and False:
                continue
        prog = S["prog"] if (i == mp and S["prog"] > 0) else 0
        stays = max(1, need - prog)
        k = d + stays
        if k > R:
            continue
        rem = R - k + 1
        if kind == "take":
            gain = v * rem
            mult = 1.0
            for r in others:
                dr = rdist[r].get(i, 99)
                if dr < d or (dr == d and False):
                    mult = P["comp_factor"]
            gain *= mult
        elif kind == "up":
            gain = v * rem
        else:
            w = P["w_deprive"] * (P["leader_boost"] if o == leader else 1.0)
            gain = v * rem + w * v * lvl[i] * rem + 8 * v * lvl[i]
            tt = t + d + (need - 1)
            pc = p_catch(o, tt)
            gain *= (1.0 - pc)
        rate = gain / k
        if i == mp and prog > 0:
            rate *= P["commit"]
        if rate > best_rate:
            best, best_rate = i, rate

    if best is None:
        return "STAY"
    if best == mp:
        return "STAY"
    a = first.get(best)
    return a if a else "STAY"
