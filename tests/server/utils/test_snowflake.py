import time
from concurrent.futures import ThreadPoolExecutor

from supernote.server.utils.snowflake import next_id


def test_snowflake_unique_ids() -> None:
    """Test that generated IDs are unique."""
    ids = set()
    count = 1000
    for _ in range(count):
        ids.add(next_id())

    assert len(ids) == count


def test_snowflake_ordered_ids() -> None:
    """Test that IDs are roughly time-ordered."""
    id1 = next_id()
    time.sleep(0.001)
    id2 = next_id()
    assert id2 > id1


def test_thread_safety() -> None:
    """Test generation from multiple threads."""
    # Using module level next_id

    def generate_batch() -> list[int]:
        return [next_id() for _ in range(100)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(generate_batch) for _ in range(4)]

    all_ids = set()
    for future in futures:
        all_ids.update(future.result())

    assert len(all_ids) == 400
