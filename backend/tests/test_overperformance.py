from datetime import date, timedelta

from app.overperformance import BaselineInput, compute_baselines, is_overperforming

D0 = date(2026, 1, 1)


def days(n: int) -> date:
    return D0 + timedelta(days=n)


def test_no_baseline_before_min_videos():
    videos = [BaselineInput(id=f"v{i}", format="long", published_at=days(i), views=1000) for i in range(3)]
    results = {r.id: r for r in compute_baselines(videos, window=10, min_videos=3)}
    # First 3 videos (0, 1, 2 prior videos seen) all fall below min_videos=3
    assert results["v0"].avg_views_baseline is None
    assert results["v1"].avg_views_baseline is None
    assert results["v2"].avg_views_baseline is None
    assert results["v2"].median_views_baseline is None
    assert results["v2"].overperform_ratio_median is None


def test_baseline_uses_trailing_window_only():
    # 4 prior videos at 1000 views each, min_videos=3 -> v4 gets a baseline
    videos = [BaselineInput(id=f"v{i}", format="long", published_at=days(i), views=1000) for i in range(4)]
    videos.append(BaselineInput(id="v4", format="long", published_at=days(4), views=5000))
    results = {r.id: r for r in compute_baselines(videos, window=10, min_videos=3)}
    assert results["v4"].avg_views_baseline == 1000.0
    assert results["v4"].overperform_ratio == 5.0
    assert results["v4"].median_views_baseline == 1000.0
    assert results["v4"].overperform_ratio_median == 5.0


def test_median_baseline_ignores_a_single_viral_outlier():
    # 5 prior videos: four at 1000 views, one viral one at 100,000. The mean
    # gets dragged way up by the outlier; the median shrugs it off.
    videos = [BaselineInput(id=f"v{i}", format="long", published_at=days(i), views=1000) for i in range(4)]
    videos.append(BaselineInput(id="v4", format="long", published_at=days(4), views=100_000))
    videos.append(BaselineInput(id="v5", format="long", published_at=days(5), views=3000))
    results = {r.id: r for r in compute_baselines(videos, window=10, min_videos=3)}
    # mean of [1000,1000,1000,1000,100000] = 20800; median = 1000
    assert results["v5"].avg_views_baseline == 20_800.0
    assert results["v5"].median_views_baseline == 1000.0
    assert round(results["v5"].overperform_ratio, 4) == round(3000 / 20_800, 4)
    assert results["v5"].overperform_ratio_median == 3.0


def test_baseline_window_caps_lookback():
    # 15 prior videos: first 5 at 100 views, last 10 at 1000 views.
    # window=10 should only average the most recent 10 (all at 1000).
    videos = [BaselineInput(id=f"v{i}", format="long", published_at=days(i), views=100) for i in range(5)]
    videos += [BaselineInput(id=f"v{i}", format="long", published_at=days(i), views=1000) for i in range(5, 15)]
    videos.append(BaselineInput(id="v15", format="long", published_at=days(15), views=2000))
    results = {r.id: r for r in compute_baselines(videos, window=10, min_videos=3)}
    assert results["v15"].avg_views_baseline == 1000.0


def test_formats_never_mix_baselines():
    long_videos = [BaselineInput(id=f"long{i}", format="long", published_at=days(i), views=10_000) for i in range(5)]
    short_videos = [BaselineInput(id=f"short{i}", format="short", published_at=days(i), views=100) for i in range(5)]
    long_videos.append(BaselineInput(id="long5", format="long", published_at=days(10), views=20_000))
    results = {r.id: r for r in compute_baselines(long_videos + short_videos, window=10, min_videos=3)}
    # long5's baseline must come only from long-form history (10k avg), not
    # be dragged down by the unrelated 100-view shorts.
    assert results["long5"].avg_views_baseline == 10_000.0


def test_zero_view_baseline_gives_no_ratio_not_a_crash():
    videos = [BaselineInput(id=f"v{i}", format="long", published_at=days(i), views=0) for i in range(4)]
    results = {r.id: r for r in compute_baselines(videos, window=10, min_videos=3)}
    assert results["v3"].avg_views_baseline == 0.0
    assert results["v3"].overperform_ratio is None
    assert results["v3"].median_views_baseline == 0.0
    assert results["v3"].overperform_ratio_median is None


def test_is_overperforming():
    assert is_overperforming(2.5, 2.0) is True
    assert is_overperforming(1.9, 2.0) is False
    assert is_overperforming(None, 2.0) is False
