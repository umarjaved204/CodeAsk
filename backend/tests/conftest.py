from collections import Counter

OPT_IN_MARKERS = ("slow", "db")


def pytest_terminal_summary(terminalreporter):
    """Say which opt-in tests did NOT run, so they can't be forgotten."""
    deselected = terminalreporter.stats.get("deselected", [])
    counts = Counter(m for item in deselected for m in OPT_IN_MARKERS
                     if item.get_closest_marker(m))
    if counts:
        parts = ", ".join(f"{n} {m}" for m, n in counts.items())
        terminalreporter.write_line(
            f"not run: {parts} (opt-in: pytest -m slow / pytest -m db)", yellow=True)
