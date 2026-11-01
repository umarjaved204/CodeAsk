from codeask import config
from codeask.count import eta_seconds, pack_batches


def test_pack_batches_respects_the_limit_and_order():
    assert pack_batches([1000, 1500, 600, 2900, 100], limit=3000) == [[0, 1], [2], [3, 4]]


def test_pack_batches_single_item_over_limit_gets_its_own_request():
    assert pack_batches([3500, 10], limit=3000) == [[0], [1]]


def test_pack_batches_empty():
    assert pack_batches([]) == []


def test_eta_counts_windows_plus_latency():
    w, lat = config.VOYAGE_WINDOW_SECONDS, config.VOYAGE_REQUEST_LATENCY_S
    assert eta_seconds(0) == 0
    assert eta_seconds(3) == lat  # the first window goes out at once; wait for the last reply
    assert eta_seconds(4) == (w + lat) + lat
    assert eta_seconds(7) == 2 * (w + lat) + lat


def test_eta_matches_m1_measurements():
    # M1 step 9: express 13 requests in 293 s; step 6: requests 21 requests in 448 s.
    assert abs(eta_seconds(13) - 293) <= 0.1 * 293
    assert abs(eta_seconds(21) - 448) <= 0.1 * 448
