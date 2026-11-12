
import random

import simulator as sim
import bot_v4

TOTAL_GAMES = 100
TOTAL_TURNS = 80
BASE_SEED = 20261113


def reset_bot_memory():
    bot_v4.turn_number = 0
    bot_v4.previous_position = None
    bot_v4.previous_action = None
    bot_v4.previous_enemy_positions = {}
    bot_v4.stay_streak = 0


def run_one_game(our_bot_id, seed):
    random.seed(seed)
    reset_bot_memory()

    board = sim.make_board()
    frozen = {i: 0 for i in range(1, 5)}
    shield_cd = {i: 0 for i in range(1, 5)}
    progress = {i: 0 for i in range(1, 5)}
    scores = {i: 0 for i in range(1, 5)}
    priority = 1

    for turn in range(1, TOTAL_TURNS + 1):
        positions = {
            i: sim.get_position(board, i)
            for i in range(1, 5)
        }

        frozen_at_start = frozen.copy()
        cooldown_at_start = shield_cd.copy()
        actions = {}

        for bot_id in range(1, 5):
            state = sim.make_state(
                board, bot_id, priority, frozen, shield_cd
            )

            if bot_id == our_bot_id:
                action = bot_v4.act(state)
            else:
                action = sim.opponent_action(state)

            if action not in state.legal_actions:
                action = "STAY"

            actions[bot_id] = action

        new_positions, effective_stay = sim.resolve_movement(
            board, positions, actions, priority
        )

        shielded_owners, newly_frozen = sim.resolve_shields(
            board,
            actions,
            new_positions,
            effective_stay,
            frozen_at_start,
            progress
        )

        sim.resolve_captures(
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

        # Score all owned cells.
        for row in board:
            for cell in row:
                if cell.owner != 0:
                    multiplier = 2 if cell.is_upgraded else 1
                    scores[cell.owner] += (
                        cell.base_points * multiplier
                    )

        # Update freezing and shield cooldowns.
        for bot_id in range(1, 5):
            if bot_id in newly_frozen:
                frozen[bot_id] = 2
            elif frozen_at_start[bot_id] > 0:
                frozen[bot_id] = max(
                    0, frozen_at_start[bot_id] - 1
                )

            if actions[bot_id] == "SHIELD":
                shield_cd[bot_id] = 4
            elif cooldown_at_start[bot_id] > 0:
                shield_cd[bot_id] = max(
                    0, cooldown_at_start[bot_id] - 1
                )

        priority = (priority % 4) + 1

    our_score = scores[our_bot_id]

    opponent_scores = [
        scores[i]
        for i in range(1, 5)
        if i != our_bot_id
    ]

    best_opponent = max(opponent_scores)

    if our_score > best_opponent:
        result = "W"
    elif our_score == best_opponent:
        result = "D"
    else:
        result = "L"

    return result, our_score, sum(opponent_scores) / 3.0


def run_benchmark():
    wins = draws = losses = 0
    total_our_score = 0.0
    total_opponent_score = 0.0

    seat_stats = {
        seat: {
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "score": 0.0
        }
        for seat in range(1, 5)
    }

    print("=" * 48)
    print("          ZONE RUSH BOT V4 BENCHMARK")
    print("=" * 48)
    print(f"Games: {TOTAL_GAMES} | Games per seat: {TOTAL_GAMES // 4}")
    print(f"Turns per game: {TOTAL_TURNS}")
    print("Bot tested: bot_v4")
    print("Opponents: simulator.py existing three opponents")
    print("Note: custom simulator, not official-engine results")
    print("-" * 48)

    for game in range(TOTAL_GAMES):
        seat = (game % 4) + 1

        result, our_score, opponent_average = run_one_game(
            seat,
            BASE_SEED + game
        )

        if result == "W":
            wins += 1
            seat_stats[seat]["wins"] += 1
        elif result == "D":
            draws += 1
            seat_stats[seat]["draws"] += 1
        else:
            losses += 1
            seat_stats[seat]["losses"] += 1

        total_our_score += our_score
        total_opponent_score += opponent_average

        seat_stats[seat]["games"] += 1
        seat_stats[seat]["score"] += our_score

        if (game + 1) % 10 == 0:
            print(
                f"Completed {game + 1:3d}/{TOTAL_GAMES} | "
                f"Wins: {wins} | Draws: {draws} | "
                f"Losses: {losses}"
            )

    avg_our = total_our_score / TOTAL_GAMES
    avg_opp = total_opponent_score / TOTAL_GAMES

    print("\n" + "=" * 48)
    print("                 FINAL RESULTS")
    print("=" * 48)
    print(f"Wins: {wins} | Draws: {draws} | Losses: {losses}")
    print(f"Win rate: {wins / TOTAL_GAMES * 100:.2f}%")
    print(f"Average our score: {avg_our:.2f}")
    print(f"Average opponent score: {avg_opp:.2f}")
    print(f"Average score difference: {avg_our - avg_opp:.2f}")

    print("\n--- STARTING POSITION PERFORMANCE ---")

    for seat, stats in seat_stats.items():
        average = stats["score"] / max(1, stats["games"])

        print(
            f"Bot {seat}: {stats['wins']} wins / "
            f"{stats['games']} games "
            f"| Average score: {average:.2f}"
        )

    print("=" * 48)


if __name__ == "__main__":
    run_benchmark()
