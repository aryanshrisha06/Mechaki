
import random
from types import SimpleNamespace

from bot import act as our_bot

SIZE = 8
TOTAL_TURNS = 80
random.seed(42)

# Example board from the official rulebook screenshot.
# The actual competition map may vary.
BOARD_VALUES = [
    [1, 1, 1, 2, 2, 1, 1, 1],
    [1, 1, 2, 2, 2, 2, 1, 1],
    [1, 2, 2, 3, 3, 2, 2, 1],
    [2, 2, 3, 3, 3, 3, 2, 2],
    [2, 2, 3, 3, 3, 3, 2, 2],
    [1, 2, 2, 3, 3, 2, 2, 1],
    [1, 1, 2, 2, 2, 2, 1, 1],
    [1, 1, 1, 2, 2, 1, 1, 1]
]

HOMES = {
    1: (0, 0),
    2: (0, 7),
    3: (7, 7),
    4: (7, 0)
}

DIRECTIONS = {
    "NORTH": (-1, 0),
    "EAST": (0, 1),
    "SOUTH": (1, 0),
    "WEST": (0, -1)
}


class Cell:
    def __init__(
        self,
        base_points=1,
        owner=0,
        occupant=0,
        upgraded=False,
        home=False
    ):
        self.base_points = base_points
        self.owner = owner
        self.occupant = occupant
        self.is_upgraded = upgraded
        self.is_home = home
        self.is_frozen = False


def make_board():
    board = []

    for r in range(SIZE):
        row = []

        for c in range(SIZE):
            row.append(
                Cell(base_points=BOARD_VALUES[r][c])
            )

        board.append(row)

    for bot_id, (r, c) in HOMES.items():
        board[r][c] = Cell(
            base_points=1,
            owner=bot_id,
            occupant=bot_id,
            home=True
        )

    return board


def get_position(board, bot_id):
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c].occupant == bot_id:
                return r, c

    return None


def get_legal_actions(board, bot_id, frozen, shield_cd):
    position = get_position(board, bot_id)

    if position is None:
        return ["STAY"]

    if frozen[bot_id] > 0:
        return ["STAY"]

    r, c = position
    actions = ["STAY"]

    for action, (dr, dc) in DIRECTIONS.items():
        nr = r + dr
        nc = c + dc

        if 0 <= nr < SIZE and 0 <= nc < SIZE:
            # A cell occupied at the start of the turn is closed.
            if board[nr][nc].occupant == 0:
                actions.append(action)

    if shield_cd[bot_id] == 0:
        actions.append("SHIELD")

    return actions


def make_state(board, bot_id, priority, frozen, shield_cd):
    # Frozen status belongs to the occupying bot.
    for row in board:
        for cell in row:
            cell.is_frozen = (
                cell.occupant != 0
                and frozen[cell.occupant] > 0
            )

    return SimpleNamespace(
        board=board,
        bot_id=bot_id,
        is_priority_token=(bot_id == priority),
        legal_actions=get_legal_actions(
            board, bot_id, frozen, shield_cd
        )
    )


def opponent_action(state):
    board = state.board
    bot_id = state.bot_id
    legal = state.legal_actions

    position = get_position(board, bot_id)

    if position is None or len(legal) == 1:
        return "STAY"

    r, c = position
    current_cell = board[r][c]

    # Capture or upgrade the cell currently occupied.
    if current_cell.owner != bot_id:
        return "STAY"

    # Simple opponent strategy:
    # Prefer valuable neutral or enemy-owned cells.
    best_action = "STAY"
    best_value = -999

    for action in legal:
        if action not in DIRECTIONS:
            continue

        dr, dc = DIRECTIONS[action]
        nr = r + dr
        nc = c + dc

        cell = board[nr][nc]

        value = cell.base_points

        if cell.owner != bot_id:
            value += 3

        if cell.is_upgraded and cell.owner != bot_id:
            value += 2

        value += random.random() * 0.5

        if value > best_value:
            best_value = value
            best_action = action

    return best_action


def priority_order(priority):
    return [
        ((priority - 1 + i) % 4) + 1
        for i in range(4)
    ]


def resolve_movement(board, positions, actions, priority):
    """
    Resolve all movements simultaneously.

    Returns:
        new_positions
        effective_stay
    """

    destinations = {}
    effective_stay = {}

    # Determine all movement requests using starting positions.
    for bot_id in range(1, 5):
        action = actions[bot_id]

        if action not in DIRECTIONS:
            effective_stay[bot_id] = action == "STAY"
            continue

        r, c = positions[bot_id]
        dr, dc = DIRECTIONS[action]

        target = (r + dr, c + dc)

        # Legal actions should already prevent this.
        # Keep this check for simulator safety.
        if not (0 <= target[0] < SIZE and
                0 <= target[1] < SIZE):
            effective_stay[bot_id] = True
            continue

        # Starting occupied cells are closed.
        if board[target[0]][target[1]].occupant != 0:
            effective_stay[bot_id] = True
            continue

        destinations.setdefault(target, []).append(bot_id)

    winners = {}

    # Resolve destination contests.
    order = priority_order(priority)

    for target, contenders in destinations.items():
        cell = board[target[0]][target[1]]

        owners = [
            bot_id
            for bot_id in contenders
            if cell.owner == bot_id
        ]

        if owners:
            winner = owners[0]
        else:
            winner = min(
                contenders,
                key=lambda bot_id: order.index(bot_id)
            )

        winners[target] = winner

    # Start with all bots remaining at their old positions.
    new_positions = positions.copy()

    # Clear the old positions of successful movers.
    for target, winner in winners.items():
        old_position = positions[winner]

        if old_position is not None:
            old_r, old_c = old_position
            board[old_r][old_c].occupant = 0

        new_positions[winner] = target
        effective_stay[winner] = False

    # Place successful movers at their destinations.
    for target, winner in winners.items():
        nr, nc = target
        board[nr][nc].occupant = winner

    # Any attempted move that did not win counts as STAY.
    for bot_id in range(1, 5):
        if bot_id not in effective_stay:
            effective_stay[bot_id] = True

    return new_positions, effective_stay


def resolve_shields(
    board,
    actions,
    positions,
    effective_stay,
    frozen_at_start,
    progress
):
    """
    Resolve shields after movement.

    Returns:
        shielded_owners
        newly_frozen
    """

    shielded_owners = set()
    newly_frozen = set()

    for bot_id in range(1, 5):
        if actions[bot_id] == "SHIELD":
            shielded_owners.add(bot_id)

    # Find eligible rivals standing on each shield owner's land.
    for owner_id in shielded_owners:
        caught_anyone = False

        for rival_id in range(1, 5):
            if rival_id == owner_id:
                continue

            # Already-frozen bots cannot be caught again.
            if frozen_at_start[rival_id] > 0:
                continue

            # Shield itself does not count as staying.
            if actions[rival_id] == "SHIELD":
                continue

            if not effective_stay[rival_id]:
                continue

            position = positions[rival_id]

            if position is None:
                continue

            r, c = position
            cell = board[r][c]

            if cell.owner == owner_id:
                caught_anyone = True
                newly_frozen.add(rival_id)

                # Interrupt capture or upgrade progress.
                progress[rival_id] = 0

        # Shield backfires if it catches nobody.
        if not caught_anyone:
            newly_frozen.add(owner_id)

        # All cells belonging to the shield owner
        # are protected during this turn.
    return shielded_owners, newly_frozen


def resolve_captures(
    board,
    actions,
    positions,
    effective_stay,
    frozen_at_start,
    newly_frozen,
    shielded_owners,
    progress,
    scores
):
    for bot_id in range(1, 5):

        # A shield action resets progress.
        if actions[bot_id] == "SHIELD":
            progress[bot_id] = 0
            continue

        # Frozen bots cannot make capture progress.
        if frozen_at_start[bot_id] > 0:
            progress[bot_id] = 0
            continue

        # A bot caught by a shield cannot make progress.
        if bot_id in newly_frozen:
            progress[bot_id] = 0
            continue

        # A successful move does not count as STAY.
        if not effective_stay[bot_id]:
            progress[bot_id] = 0
            continue

        position = positions[bot_id]

        if position is None:
            continue

        r, c = position
        cell = board[r][c]

        # Home cells cannot be captured.
        # Their own bot may still upgrade them.
        if cell.is_home and cell.owner != bot_id:
            progress[bot_id] = 0
            continue

        # A shield protects its owner's land this turn.
        if (
            cell.owner != bot_id
            and cell.owner in shielded_owners
        ):
            progress[bot_id] = 0
            continue

        progress[bot_id] += 1

        # Own level-1 cell: upgrade after 3 stays.
        if cell.owner == bot_id:

            if not cell.is_upgraded and progress[bot_id] >= 3:
                cell.is_upgraded = True
                progress[bot_id] = 0

        # Neutral cell: capture after 1 stay.
        elif cell.owner == 0:

            if progress[bot_id] >= 1:
                cell.owner = bot_id
                cell.is_upgraded = False
                progress[bot_id] = 0

        # Rival cell: capture after 1 or 3 stays.
        else:
            previous_level = (
                2 if cell.is_upgraded else 1
            )

            required_stays = (
                3 if cell.is_upgraded else 1
            )

            if progress[bot_id] >= required_stays:

                # One-time raid bonus.
                scores[bot_id] += (
                    8 * cell.base_points * previous_level
                )

                cell.owner = bot_id
                cell.is_upgraded = False
                progress[bot_id] = 0


def run_game(show_actions=True):
    board = make_board()

    frozen = {
        i: 0 for i in range(1, 5)
    }

    shield_cd = {
        i: 0 for i in range(1, 5)
    }

    # Consecutive STAY progress for each bot.
    progress = {
        i: 0 for i in range(1, 5)
    }

    scores = {
        i: 0 for i in range(1, 5)
    }

    priority = 1

    for turn in range(1, TOTAL_TURNS + 1):

        # Save starting positions and status.
        positions = {
            i: get_position(board, i)
            for i in range(1, 5)
        }

        frozen_at_start = frozen.copy()
        cooldown_at_start = shield_cd.copy()

        actions = {}

        # All four bots choose before movement is resolved.
        for bot_id in range(1, 5):

            state = make_state(
                board,
                bot_id,
                priority,
                frozen,
                shield_cd
            )

            if bot_id == 1:
                action = our_bot(state)
            else:
                action = opponent_action(state)

            if action not in state.legal_actions:
                action = "STAY"

            actions[bot_id] = action

        if show_actions and turn <= 10:
            for bot_id in range(1, 5):
                print(
                    f"Turn {turn}, Bot {bot_id}: "
                    f"{actions[bot_id]}"
                )

        # STEP 1: Resolve movement.
        new_positions, effective_stay = resolve_movement(
            board,
            positions,
            actions,
            priority
        )

        # STEP 2: Resolve shields and freezes.
        shielded_owners, newly_frozen = resolve_shields(
            board,
            actions,
            new_positions,
            effective_stay,
            frozen_at_start,
            progress
        )

        # STEP 3: Resolve captures and upgrades.
        resolve_captures(
            board,
            actions,
            new_positions,
            effective_stay,
            frozen_at_start,
            newly_frozen,
            shielded_owners,
            progress,
            scores
        )

        # STEP 4: Score all owned cells.
        for row in board:
            for cell in row:

                if cell.owner != 0:
                    multiplier = (
                        2 if cell.is_upgraded else 1
                    )

                    scores[cell.owner] += (
                        cell.base_points * multiplier
                    )

        # STEP 5: Update freeze timers.
        for bot_id in range(1, 5):

            if bot_id in newly_frozen:
                frozen[bot_id] = 2

            elif frozen_at_start[bot_id] > 0:
                frozen[bot_id] = max(
                    0,
                    frozen_at_start[bot_id] - 1
                )

        # STEP 6: Update shield cooldowns.
        for bot_id in range(1, 5):

            if actions[bot_id] == "SHIELD":
                shield_cd[bot_id] = 4

            elif cooldown_at_start[bot_id] > 0:
                shield_cd[bot_id] = max(
                    0,
                    cooldown_at_start[bot_id] - 1
                )

        # STEP 7: Pass the priority token.
        priority = (priority % 4) + 1

        if turn % 10 == 0:
            print(
                f"Turn {turn:02d} | "
                f"Our score: {scores[1]} | "
                f"Bot 2: {scores[2]} | "
                f"Bot 3: {scores[3]} | "
                f"Bot 4: {scores[4]}"
            )

    print("\n========== FINAL RESULTS ==========")

    ranking = sorted(
        scores,
        key=lambda bot_id: scores[bot_id],
        reverse=True
    )

    for rank, bot_id in enumerate(ranking, start=1):
        print(
            f"{rank}. Bot {bot_id}: "
            f"{scores[bot_id]} points"
        )

    print("===================================")

    if scores[1] == max(scores.values()):
        print("OUR BOT FINISHED JOINT FIRST OR WON!")
    else:
        print(
            f"Bot {ranking[0]} won. "
            "Our bot needs improvement."
        )


if __name__ == "__main__":
    run_game()
