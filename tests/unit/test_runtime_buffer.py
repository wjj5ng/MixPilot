"""runtime.buffer 단위 테스트 — ring buffer 정합성·wrap·경계."""

from __future__ import annotations

import numpy as np
import pytest

from mixpilot.runtime import RollingBuffer


class TestConstruction:
    def test_initial_state_is_empty(self) -> None:
        buf = RollingBuffer(capacity_frames=10, num_channels=2)
        assert buf.fill == 0
        assert buf.is_full is False
        assert buf.capacity == 10
        assert buf.num_channels == 2

    def test_snapshot_when_empty_returns_zero_frames(self) -> None:
        buf = RollingBuffer(capacity_frames=10, num_channels=2)
        snap = buf.snapshot()
        assert snap.shape == (0, 2)

    def test_rejects_non_positive_capacity(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            RollingBuffer(capacity_frames=0, num_channels=2)
        with pytest.raises(ValueError, match="capacity"):
            RollingBuffer(capacity_frames=-1, num_channels=2)

    def test_rejects_non_positive_num_channels(self) -> None:
        with pytest.raises(ValueError, match="num_channels"):
            RollingBuffer(capacity_frames=10, num_channels=0)

    def test_custom_dtype(self) -> None:
        buf = RollingBuffer(capacity_frames=4, num_channels=1, dtype=np.float64)
        buf.write(np.array([[1.0], [2.0]], dtype=np.float64))
        snap = buf.snapshot()
        assert snap.dtype == np.float64


class TestPartialFill:
    def test_fill_counter_increments(self) -> None:
        buf = RollingBuffer(capacity_frames=10, num_channels=1)
        buf.write(np.array([[1.0], [2.0], [3.0]], dtype=np.float32))
        assert buf.fill == 3
        assert buf.is_full is False

    def test_snapshot_returns_only_filled_portion(self) -> None:
        buf = RollingBuffer(capacity_frames=10, num_channels=1)
        buf.write(np.array([[1.0], [2.0], [3.0]], dtype=np.float32))
        snap = buf.snapshot()
        assert snap.shape == (3, 1)
        np.testing.assert_array_equal(snap.ravel(), [1.0, 2.0, 3.0])

    def test_multiple_writes_preserve_order(self) -> None:
        buf = RollingBuffer(capacity_frames=10, num_channels=1)
        buf.write(np.array([[1.0], [2.0]], dtype=np.float32))
        buf.write(np.array([[3.0], [4.0], [5.0]], dtype=np.float32))
        snap = buf.snapshot()
        np.testing.assert_array_equal(snap.ravel(), [1.0, 2.0, 3.0, 4.0, 5.0])


class TestExactFill:
    def test_exact_capacity_marks_full(self) -> None:
        buf = RollingBuffer(capacity_frames=4, num_channels=1)
        buf.write(np.arange(4, dtype=np.float32).reshape(-1, 1))
        assert buf.fill == 4
        assert buf.is_full is True

    def test_exact_capacity_snapshot_in_order(self) -> None:
        buf = RollingBuffer(capacity_frames=4, num_channels=1)
        buf.write(np.array([[10.0], [20.0], [30.0], [40.0]], dtype=np.float32))
        snap = buf.snapshot()
        np.testing.assert_array_equal(snap.ravel(), [10.0, 20.0, 30.0, 40.0])


class TestWrapAround:
    def test_wrap_keeps_chronological_order(self) -> None:
        buf = RollingBuffer(capacity_frames=4, num_channels=1)
        # 6개 쓰면 처음 2개는 밀려나고 마지막 4개 [3,4,5,6]만 남는다.
        buf.write(
            np.array([[1.0], [2.0], [3.0], [4.0], [5.0], [6.0]], dtype=np.float32)
        )
        snap = buf.snapshot()
        np.testing.assert_array_equal(snap.ravel(), [3.0, 4.0, 5.0, 6.0])

    def test_wrap_across_two_writes(self) -> None:
        buf = RollingBuffer(capacity_frames=4, num_channels=1)
        buf.write(np.array([[1.0], [2.0], [3.0]], dtype=np.float32))
        buf.write(np.array([[4.0], [5.0]], dtype=np.float32))
        snap = buf.snapshot()
        np.testing.assert_array_equal(snap.ravel(), [2.0, 3.0, 4.0, 5.0])

    def test_single_huge_write_keeps_tail(self) -> None:
        buf = RollingBuffer(capacity_frames=3, num_channels=1)
        # capacity의 3배 → 마지막 3개만 남는다.
        buf.write(np.arange(9, dtype=np.float32).reshape(-1, 1))
        snap = buf.snapshot()
        np.testing.assert_array_equal(snap.ravel(), [6.0, 7.0, 8.0])


class TestMultiChannel:
    def test_2d_input_per_channel_preserved(self) -> None:
        buf = RollingBuffer(capacity_frames=3, num_channels=2)
        buf.write(np.array([[1.0, 10.0], [2.0, 20.0]], dtype=np.float32))
        snap = buf.snapshot()
        np.testing.assert_array_equal(snap, [[1.0, 10.0], [2.0, 20.0]])

    def test_1d_input_to_single_channel_buffer(self) -> None:
        buf = RollingBuffer(capacity_frames=3, num_channels=1)
        buf.write(np.array([1.0, 2.0, 3.0], dtype=np.float32))
        snap = buf.snapshot()
        np.testing.assert_array_equal(snap.ravel(), [1.0, 2.0, 3.0])

    def test_32_channels_m32_scenario(self) -> None:
        buf = RollingBuffer(capacity_frames=100, num_channels=32)
        frames = np.tile(np.arange(32, dtype=np.float32) * 0.01, (50, 1))
        buf.write(frames)
        snap = buf.snapshot()
        assert snap.shape == (50, 32)
        # 각 채널은 동일 DC 값 유지 (float32 정밀도 내).
        for i in range(32):
            np.testing.assert_allclose(snap[:, i], i * 0.01, rtol=1e-6)


class TestValidation:
    def test_rejects_3d_input(self) -> None:
        buf = RollingBuffer(capacity_frames=10, num_channels=2)
        with pytest.raises(ValueError, match="1D or 2D"):
            buf.write(np.zeros((5, 2, 1), dtype=np.float32))

    def test_rejects_channel_mismatch(self) -> None:
        buf = RollingBuffer(capacity_frames=10, num_channels=2)
        with pytest.raises(ValueError, match="channels mismatch"):
            buf.write(np.zeros((5, 3), dtype=np.float32))

    def test_empty_write_is_noop(self) -> None:
        buf = RollingBuffer(capacity_frames=10, num_channels=2)
        buf.write(np.array([[1.0, 2.0]], dtype=np.float32))
        buf.write(np.zeros((0, 2), dtype=np.float32))
        assert buf.fill == 1


class TestSnapshotIsCopy:
    def test_snapshot_modification_does_not_affect_buffer(self) -> None:
        buf = RollingBuffer(capacity_frames=4, num_channels=1)
        buf.write(np.array([[1.0], [2.0], [3.0]], dtype=np.float32))
        snap = buf.snapshot()
        snap[0, 0] = 999.0
        snap2 = buf.snapshot()
        assert snap2[0, 0] == 1.0


class TestReset:
    def test_reset_empties_buffer(self) -> None:
        buf = RollingBuffer(capacity_frames=4, num_channels=1)
        buf.write(np.array([[1.0], [2.0], [3.0]], dtype=np.float32))
        buf.reset()
        assert buf.fill == 0
        assert buf.snapshot().shape == (0, 1)

    def test_write_after_reset_works(self) -> None:
        buf = RollingBuffer(capacity_frames=4, num_channels=1)
        buf.write(np.arange(10, dtype=np.float32).reshape(-1, 1))
        buf.reset()
        buf.write(np.array([[100.0]], dtype=np.float32))
        snap = buf.snapshot()
        np.testing.assert_array_equal(snap.ravel(), [100.0])


class TestDeterminism:
    def test_same_write_sequence_yields_same_snapshot(self) -> None:
        a = RollingBuffer(capacity_frames=10, num_channels=2)
        b = RollingBuffer(capacity_frames=10, num_channels=2)
        for n in [3, 5, 4, 2]:
            arr = np.random.default_rng(42).standard_normal((n, 2)).astype(np.float32)
            a.write(arr)
            b.write(arr)
        np.testing.assert_array_equal(a.snapshot(), b.snapshot())
