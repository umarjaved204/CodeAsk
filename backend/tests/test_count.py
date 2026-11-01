from codeask import config
from codeask.count import eta_seconds, pack_batches


def test_pack_batches_respects_the_limit_and_order():
    assert pack_batches([1000, 1500, 600, 2900, 100], limit=3000) == [[0, 1], [2], [3, 4]]


def test_pack_batches_single_item_over_limit_gets_its_own_request():
    assert pack_batches([3500, 10], limit=3000) == [[0], [1]]


def test_pack_batches_empty():
    assert pack_batches([]) == []


def test_eta_counts_whole_windows():
    w = config.VOYAGE_WINDOW_SECONDS
    assert eta_seconds(0) == 0
    assert eta_seconds(3) == 0  # the first window goes out immediately
    assert eta_seconds(4) == w
    assert eta_seconds(7) == 2 * w
