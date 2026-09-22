"""Analyze backtest results and generate comparison reports."""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def calculate_metrics(trades_df: pd.DataFrame) -> dict:
    """Calculate key performance metrics from trades."""
    if trades_df.empty:
        return {}

    # Convert points to numeric
    trades_df = trades_df.copy()
    trades_df['points'] = pd.to_numeric(trades_df['points'], errors='coerce')
    trades_df = trades_df.dropna(subset=['points'])

    if trades_df.empty:
        return {}

    total_trades = len(trades_df)
    winning_trades = (trades_df['points'] > 0).sum()
    losing_trades = (trades_df['points'] < 0).sum()

    winning_points = trades_df[trades_df['points'] > 0]['points'].sum()
    losing_points = abs(trades_df[trades_df['points'] < 0]['points'].sum())

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    avg_win = (winning_points / winning_trades) if winning_trades > 0 else 0
    avg_loss = (losing_points / losing_trades) if losing_trades > 0 else 0
    profit_factor = (winning_points / losing_points) if losing_points > 0 else 0
    total_points = trades_df['points'].sum()
    max_loss = trades_df['points'].min()
    max_gain = trades_df['points'].max()

    # Consecutive losses
    trades_df['is_loss'] = trades_df['points'] < 0
    consecutive_losses = 0
    current_streak = 0
    for is_loss in trades_df['is_loss']:
        if is_loss:
            current_streak += 1
            consecutive_losses = max(consecutive_losses, current_streak)
        else:
            current_streak = 0

    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
        'total_points': total_points,
        'max_gain': max_gain,
        'max_loss': max_loss,
        'consecutive_losses': consecutive_losses,
    }


def print_metrics(name: str, metrics: dict):
    """Print metrics in formatted table."""
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")
    print(f"  Total Trades:          {metrics.get('total_trades', 0)}")
    print(f"  Winning Trades:        {metrics.get('winning_trades', 0)} ({metrics.get('win_rate', 0):.1f}%)")
    print(f"  Losing Trades:         {metrics.get('losing_trades', 0)}")
    print(f"  ─" * 30)
    print(f"  Avg Win:               {metrics.get('avg_win', 0):+.2f} pts")
    print(f"  Avg Loss:              {metrics.get('avg_loss', 0):+.2f} pts")
    print(f"  Win/Loss Ratio:        {(metrics.get('avg_win', 0) / metrics.get('avg_loss', 1)):.2f}:1")
    print(f"  Profit Factor:         {metrics.get('profit_factor', 0):.2f}x")
    print(f"  ─" * 30)
    print(f"  Total Points:          {metrics.get('total_points', 0):+.2f} pts")
    print(f"  Best Trade:            {metrics.get('max_gain', 0):+.2f} pts")
    print(f"  Worst Trade:           {metrics.get('max_loss', 0):+.2f} pts")
    print(f"  Consecutive Losses:    {metrics.get('consecutive_losses', 0)}")
    print(f"{'=' * 60}\n")


def compare_results(baseline_file: str, improved_file: str):
    """Compare two backtest results."""
    try:
        baseline_df = pd.read_csv(baseline_file)
        improved_df = pd.read_csv(improved_file)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return

    baseline_metrics = calculate_metrics(baseline_df)
    improved_metrics = calculate_metrics(improved_df)

    print("\n" + "=" * 80)
    print("  BACKTEST COMPARISON ANALYSIS")
    print("=" * 80)

    print_metrics("BASELINE", baseline_metrics)
    print_metrics("IMPROVED", improved_metrics)

    # Calculate differences
    print("\n" + "=" * 80)
    print("  IMPROVEMENT ANALYSIS")
    print("=" * 80 + "\n")

    metrics_to_compare = [
        ('total_trades', 'Total Trades', lambda x: f"{x:.0f}", False),
        ('win_rate', 'Win Rate %', lambda x: f"{x:.1f}%", True),
        ('avg_win', 'Avg Win', lambda x: f"{x:+.2f}", True),
        ('avg_loss', 'Avg Loss', lambda x: f"{x:+.2f}", False),
        ('profit_factor', 'Profit Factor', lambda x: f"{x:.2f}x", True),
        ('total_points', 'Total Points', lambda x: f"{x:+.2f}", True),
        ('consecutive_losses', 'Consecutive Losses', lambda x: f"{x:.0f}", False),
    ]

    improvements = 0
    regressions = 0

    for key, label, fmt, is_better_higher in metrics_to_compare:
        baseline_val = baseline_metrics.get(key, 0)
        improved_val = improved_metrics.get(key, 0)
        delta = improved_val - baseline_val
        delta_pct = (delta / abs(baseline_val) * 100) if baseline_val != 0 else 0

        emoji = "✅" if (delta > 0 and is_better_higher) or (delta < 0 and not is_better_higher) else "❌" if delta != 0 else "→"

        if emoji == "✅":
            improvements += 1
        elif emoji == "❌":
            regressions += 1

        print(f"  {label:.<30} {fmt(baseline_val):>15} → {fmt(improved_val):>15}  {delta:+.2f} ({delta_pct:+.1f}%)  {emoji}")

    print("\n" + "=" * 80)
    if improvements > regressions and regressions == 0:
        print("  ✅ VERDICT: IMPROVEMENT VALIDATED - IMPLEMENT THIS CHANGE")
    elif improvements > regressions:
        print(f"  🤔 VERDICT: MIXED RESULTS ({improvements} improvements, {regressions} regressions) - INVESTIGATE")
    else:
        print("  ❌ VERDICT: REGRESSION DETECTED - DO NOT IMPLEMENT")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        # Single file analysis
        try:
            df = pd.read_csv(sys.argv[1])
            metrics = calculate_metrics(df)
            print_metrics("BACKTEST RESULTS", metrics)
        except FileNotFoundError:
            print(f"Error: File {sys.argv[1]} not found")
            sys.exit(1)
    elif len(sys.argv) == 3:
        # Comparison analysis
        compare_results(sys.argv[1], sys.argv[2])
    else:
        print("Usage:")
        print("  python analyze_backtest.py <results.csv>")
        print("  python analyze_backtest.py <baseline.csv> <improved.csv>")
        sys.exit(1)
